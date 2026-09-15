"""Agent 的受控工具：集合由服务端固定，所有证据使用稳定编号。"""

import hashlib
import json
import time
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from urllib.parse import quote

from papermind.models import SearchFilter


class AgentStopped(RuntimeError):
    """任务取消或达到运行预算；不向模型转换为可忽略的工具消息。"""


class AgentContext:
    def __init__(self, service, collection, emit, cancelled):
        self.service = service
        self.collection = collection
        self.emit = emit
        self.cancelled = cancelled
        self.started = time.monotonic()
        self.lock = RLock()
        self.tool_calls = self.model_calls = self.sequence = 0
        self.evidence: dict[str, dict] = {}
        self.calculations: dict[str, dict] = {}
        self.document_ids: set[str] = set()

    def check(self):
        if self.cancelled():
            raise AgentStopped("任务已取消。")
        if time.monotonic() - self.started >= 300:
            raise AgentStopped("任务达到 300 秒运行预算，请拆分任务后重试。")

    def progress(self, stage, message, *, tool="", status="running"):
        with self.lock:
            self.sequence += 1
            self.emit({"sequence": self.sequence, "stage": stage, "tool": tool,
                       "status": status, "message": message})

    def before_model(self):
        self.check()
        self.model_calls += 1
        if self.model_calls > 12:
            raise AgentStopped("任务达到 12 次模型调用预算，请拆分任务后重试。")
        self.progress("model", "正在规划下一步操作或整理有来源的结论。")

    @contextmanager
    def call(self, name):
        # 即使服务商返回并行工具请求，业务工具也按顺序执行。
        with self.lock:
            self.check()
            self.tool_calls += 1
            if self.tool_calls > 20:
                raise AgentStopped("任务达到 20 次工具调用预算，请拆分任务后重试。")
            self.progress("tool", "正在执行工具。", tool=name)
            yield
            self.check()
            self.progress("tool", "工具执行完成。", tool=name, status="completed")

    def remember_document(self, document_id):
        if document_id not in self.document_ids and len(self.document_ids) >= 200:
            raise AgentStopped("涉及文档超过 200 份，请缩小知识库或问题范围。")
        self.document_ids.add(document_id)

    def remember(self, identity, source):
        evidence_id = "e_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        if evidence_id not in self.evidence and len(self.evidence) >= 64:
            raise AgentStopped("任务证据超过 64 条，请拆分分析范围。")
        self.remember_document(source["document_id"])
        item = {**source, "evidence_id": evidence_id}
        self.evidence[evidence_id] = item
        return item

    def source_snapshot(self, source, *, expanded=False):
        document_id = source["document_id"]
        record = self.service.store.get(document_id, self.collection)
        metadata = source.get("metadata", {})
        location = metadata.get("source", {})
        body = json.dumps(record["body"], ensure_ascii=False, sort_keys=True)
        content = source["content"]
        if expanded:
            document = record["body"]
            if source.get("content_type") == "table":
                table = next((item for item in document.get("tables", [])
                              if item["table_id"] == metadata.get("table_id")), None)
                if table:
                    offset = max(0, metadata.get("row_index", 0) - 3)
                    rows = table["rows"][offset:offset + 20]
                    content = json.dumps({"headers": table["headers"], "rows": rows,
                                          "row_offset": offset, "total_rows": len(table["rows"])}, ensure_ascii=False)
                    location = {**table.get("source", {}), "row_offset": offset,
                                "preview_row_count": len(rows), "table_id": table["table_id"]}
            elif source.get("content_type") == "text":
                paragraphs = [paragraph["text"]
                              for section in document.get("sections", [])
                              if section["title"] == source.get("section")
                              for paragraph in section.get("paragraphs", [])
                              if paragraph["page"] == source.get("page")
                              and (not location or paragraph.get("source", {}) == location)]
                if paragraphs:
                    content = "\n\n".join(paragraphs)
        item = {
            "kind": "document", "document_id": document_id,
            "chunk_id": source["chunk_id"], "filename": source["filename"],
            "section": source.get("section", ""), "page": source.get("page", 0),
            "content_type": source.get("content_type", "text"),
            "source": location, "content": content[:6000],
            "content_truncated": len(content) > 6000,
            "scope": "source_context" if expanded else "retrieval_chunk",
            "extraction_method": metadata.get("extraction_method", "native"),
            "analysis_status": metadata.get("analysis_status", ""),
            "document_version": hashlib.sha256(body.encode()).hexdigest(),
            "url": f"/documents/{quote(document_id)}/file?collection_id={quote(self.collection)}",
        }
        if item["page"] > 0:
            item["url"] += f"#page={item['page']}"
        return self.remember(
            source["chunk_id"] + ":" + item["document_version"] + ":" + item["scope"], item
        )


def make_tools(context):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, ConfigDict, Field, create_model

    from papermind.enterprise.tables import (
        TableAnalysisRequest, analyze_table as calculate, list_tables as catalog,
    )

    class SearchArgs(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        question: str = Field(min_length=1, max_length=2000)
        document_ids: list[str] = Field(default_factory=list, max_length=20)
        k: int = Field(default=5, ge=1, le=8)

    class SourceArgs(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        evidence_id: str = Field(min_length=1, max_length=100)

    class CatalogArgs(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)

    AnalysisToolArgs = create_model(
        "AnalysisToolArgs", __config__=ConfigDict(extra="forbid", strict=True),
        **{name: (field.annotation, deepcopy(field))
           for name, field in TableAnalysisRequest.model_fields.items()
           if name != "collection_id"},
    )

    def search_knowledge(question, document_ids=None, k=5):
        with context.call("search_knowledge"):
            filters = SearchFilter(document_ids=tuple(document_ids)) if document_ids else None
            hits = context.service.search(question, context.collection, k, filters)
            sources = []
            for hit in hits:
                context.check()
                with context.service._lock:
                    source = context.service.store.source(hit.chunk.chunk_id, context.collection)
                    sources.append(context.source_snapshot(source))
            return {"evidence": sources}

    def get_source(evidence_id):
        with context.call("get_source"):
            source = context.evidence.get(evidence_id)
            if source is None:
                return {"error": "只能读取此前检索或计算返回的 evidence_id。"}
            with context.service._lock:
                context.service.store.get(source["document_id"], context.collection)
                if source["kind"] == "calculation":
                    return {"evidence": source}
                current = context.service.store.source(source["chunk_id"], context.collection)
                updated = context.source_snapshot(current, expanded=True)
            return {"evidence": updated,
                    "version_changed": updated["document_version"] != source["document_version"]}

    def list_tables():
        with context.call("list_tables"):
            tables = catalog(context.service.store, context.collection)
            visible = tables[:100]
            for table in visible:
                context.remember_document(table["document_id"])
            result = {"tables": visible, "truncated": len(tables) > 100}
            if len(json.dumps(result, ensure_ascii=False)) > 30000:
                raise ValueError("表结构描述过大，请缩小知识库或先检索目标文档。")
            return result

    def analyze_table(**kwargs):
        with context.call("analyze_table"):
            try:
                spec = TableAnalysisRequest.model_validate({**kwargs, "collection_id": context.collection})
                result = calculate(context.service.store, context.collection, spec)
            except ValueError as exc:
                error = str(exc)[:500] if type(exc) is ValueError else "统计参数不符合要求，请核对操作类型、列索引与筛选条件。"
                return {"error": error, "action": "修正筛选条件或报告资料缺口，不要自行估算。"}
            context.check()
            calculation_id = result["calculation_id"]
            context.calculations[calculation_id] = result
            groups = [{key: value for key, value in group.items() if key != "row_numbers"}
                      for group in result.get("groups", [])]
            item = {
                "kind": "calculation", "calculation_id": calculation_id,
                "document_id": result["document_id"], "filename": result["filename"],
                "source": result.get("source", {}), "table_id": result["table_id"],
                "content": json.dumps({"summary": result.get("summary"),
                                       "groups": groups}, ensure_ascii=False),
            }
            evidence = context.remember(calculation_id, item)
            # 全部源行编号留在服务端快照；模型只需结果和有限预览。
            preview = {key: value for key, value in result.items()
                       if key not in {"selected_row_numbers", "groups", "snapshot"}}
            preview["groups"] = groups
            if len(json.dumps(preview, ensure_ascii=False)) > 30000:
                return {"error": "计算结果已保存，但超过模型上下文限制。请增加筛选条件缩小范围。"}
            return {"evidence": evidence, "calculation": preview}

    definitions = [
        ("search_knowledge", search_knowledge, SearchArgs,
         "检索当前授权知识库，可按此前返回的 document_ids 限定文档；返回稳定证据编号及来源。"),
        ("get_source", get_source, SourceArgs,
         "按此前返回的 evidence_id 读取来源快照或计算记录；不能读取任意路径。"),
        ("list_tables", list_tables, CatalogArgs,
         "列出当前授权知识库的表格、文档 ID 和列索引，统计前先读取字段。"),
        ("analyze_table", analyze_table, AnalysisToolArgs,
         "对已索引表格执行筛选及统计。列索引从 0 开始。不得自行在回答中心算替代此工具。"),
    ]
    return [StructuredTool.from_function(func=func, name=name, description=description,
                                        args_schema=schema)
            for name, func, schema, description in definitions]
