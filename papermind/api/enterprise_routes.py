from typing import Literal
import json

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from papermind.enterprise.authorization import AuthorizedService, authorize, allowed_documents
from papermind.enterprise.jobs import JobCancelled
from papermind.enterprise.tables import TableAnalysisRequest, analyze_table, list_tables


class IndexTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    collection_id: str = Field(default="enterprise", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    document_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    collection_id: str = Field(default="enterprise", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    question: str = Field(min_length=1, max_length=8000)


def enterprise_router(service, access, jobs):
    router = APIRouter(prefix="/api/enterprise")

    def visible(job, actor):
        if actor is None or (actor.id != job["owner"] and actor.role != "admin"):
            raise HTTPException(404, "任务不存在或无权访问。")
        authorize(access, actor, job["collection"])
        for identity in job.get("document_ids") or []:
            authorize(access, actor, job["collection"], document_id=identity)
        return job

    def public(job):
        return {k: v for k, v in job.items() if k not in {"owner", "document_ids"}}

    @router.get("/tables")
    def tables(request: Request, collection_id: str = Query(default="enterprise", pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
        authorize(access, request.state.actor, collection_id)
        scoped = AuthorizedService(service, access, request.state.actor, collection_id)
        return {"tables": list_tables(scoped.store, collection_id)}

    @router.post("/analyze", status_code=202)
    def analyze(body: TableAnalysisRequest, request: Request):
        actor, collection = request.state.actor, body.collection_id
        authorize(access, actor, collection, document_id=body.document_id)
        service.store.get(body.document_id, collection)
        scoped = AuthorizedService(service, access, actor, collection, [body.document_id])

        def work(emit, cancelled):
            if cancelled():
                raise JobCancelled()
            emit({"stage": "calculation", "message": "读取结构化表格，按指定条件执行计算。"})
            result = analyze_table(scoped.store, collection, body)
            authorize(access, actor, collection, document_id=body.document_id)
            return {**result, "document_ids": [body.document_id]}

        job = jobs.submit(actor.id, collection, "analysis", work, [body.document_id])
        access.audit(actor.id, "analysis.submitted", job["id"], {"document_id": body.document_id})
        return public(job)

    @router.post("/index", status_code=202)
    def index(body: IndexTask, request: Request):
        actor = request.state.actor
        authorize(access, actor, body.collection_id, write=True, document_id=body.document_id)
        service.store.get(body.document_id, body.collection_id)

        def work(emit, cancelled):
            if cancelled():
                raise JobCancelled()
            authorize(access, actor, body.collection_id, write=True, document_id=body.document_id)
            emit({"stage": "index", "message": "正在解析资料并建立索引；首次模型加载可能需要较长时间。"})

            def before_commit():
                if cancelled():
                    raise JobCancelled()
                authorize(access, actor, body.collection_id, write=True, document_id=body.document_id)

            result = service.index(body.document_id, body.collection_id, before_commit=before_commit)
            return {**result, "document_ids": [body.document_id]}

        job = jobs.submit(actor.id, body.collection_id, "index", work, [body.document_id])
        access.audit(actor.id, "index.submitted", job["id"], {"document_id": body.document_id})
        return public(job)

    @router.post("/agent", status_code=202)
    def agent(body: AgentTask, request: Request):
        if not body.question.strip():
            raise ValueError("请填写具体的分析任务。")
        actor, collection = request.state.actor, body.collection_id
        identities = [d["document_id"] for d in allowed_documents(service, access, actor, collection) if d["indexed"]]
        if not identities:
            raise ValueError("当前知识库没有已索引资料，请先上传并建立索引。")
        if len(identities) > 200:
            raise ValueError("当前任务范围超过 200 份资料，请按业务主题拆分知识库。")
        scoped = AuthorizedService(service, access, actor, collection, identities)

        def work(emit, cancelled):
            from papermind.enterprise.agent import run_agent
            authorize(access, actor, collection)
            return run_agent(scoped, collection, body.question.strip(), emit, cancelled)

        job = jobs.submit(actor.id, collection, "agent", work, identities)
        access.audit(actor.id, "agent.submitted", job["id"], {"collection": collection})
        return public(job)

    @router.get("/jobs")
    def list_jobs(request: Request, collection_id: str = "enterprise"):
        actor = request.state.actor
        authorize(access, actor, collection_id)
        result = []
        for job in jobs.list(actor.id, collection_id, admin=actor.role == "admin"):
            try:
                result.append(public(visible(job, actor)))
            except HTTPException:
                continue
        return {"jobs": result}

    @router.get("/jobs/{identity}")
    def get_job(identity: str, request: Request):
        return public(visible(jobs.get(identity), request.state.actor))

    @router.post("/jobs/{identity}/cancel")
    def cancel_job(identity: str, request: Request):
        visible(jobs.get(identity), request.state.actor)
        result = jobs.cancel(identity)
        access.audit(request.state.actor.id, "job.cancel_requested", identity)
        return public(result)

    @router.get("/jobs/{identity}/report")
    def report(identity: str, request: Request, format: Literal["json", "docx", "pdf"] = "docx"):
        job = visible(jobs.get(identity), request.state.actor)
        if job["status"] != "succeeded" or job["result"] is None:
            raise HTTPException(409, "任务尚未完成，无法生成报告。")
        if job["kind"] == "index" and format != "json":
            raise HTTPException(422, "索引任务仅提供 JSON 结果。")
        from papermind.enterprise.reports import render_report
        payload = (json.dumps(job["result"], ensure_ascii=False, indent=2).encode("utf-8")
                   if job["kind"] == "index" else render_report(job["result"], format))
        # 生成文件期间权限可能改变，发送前再次核验。
        visible(job, request.state.actor)
        access.audit(request.state.actor.id, "report.downloaded", identity, {"format": format})
        types = {"json": "application/json", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        return Response(payload, media_type=types[format], headers={
            "Content-Disposition": f'attachment; filename="IndustrialInsight-{identity[:12]}.{format}"',
            "X-Content-Type-Options": "nosniff",
        })

    return router
