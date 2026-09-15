import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from papermind.enterprise.authorization import require_admin
from papermind.service import validate_collection

from .access_middleware import COOKIE, local_request
from .settings_routes import validated


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")
    password: str = Field(min_length=12, max_length=256)


class GrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    collection_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    user_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    role: Literal["viewer", "editor", "none"]


class DocumentGrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    collection_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    document_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    restricted: bool
    user_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    role: Literal["viewer", "editor", "none"] = "none"


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    active: bool


def access_router(access, service):
    router = APIRouter()
    attempts, attempt_lock = OrderedDict(), RLock()

    def throttle(request):
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with attempt_lock:
            recent = [t for t in attempts.get(key, []) if now - t < 300]
            if len(recent) >= 10:
                raise HTTPException(429, "登录尝试过于频繁，请五分钟后重试。")
            attempts[key] = recent + [now]
            attempts.move_to_end(key)
            while len(attempts) > 2048:
                attempts.popitem(last=False)

    def set_session(response, request, token):
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=12 * 3600, path="/")

    @router.get("/access", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).parent / "static" / "access.html")

    @router.get("/api/access/me")
    def me(request: Request):
        enabled = access.enabled()
        actor = request.state.actor
        return {"enabled": enabled, "authenticated": enabled and actor is not None,
                "user": actor.public() if enabled and actor else None,
                "csrf_token": actor.csrf_token if actor else "",
                "can_bootstrap": not enabled and local_request(request)}

    @router.post("/api/access/bootstrap")
    async def bootstrap(request: Request, response: Response):
        if not local_request(request):
            raise HTTPException(403, "首次管理员仅能从服务运行电脑的 localhost 页面创建。")
        throttle(request)
        body = await validated(request, Credentials)
        user = await run_in_threadpool(access.create_user, body.username, body.password, True)
        token, actor = await run_in_threadpool(access.login, body.username, body.password)
        set_session(response, request, token)
        access.audit(actor.id, "access.enabled", "system")
        return {"user": user, "csrf_token": actor.csrf_token, "enabled": True}

    @router.post("/api/access/login")
    async def login(request: Request, response: Response):
        throttle(request)
        body = await validated(request, Credentials)
        result = await run_in_threadpool(access.login, body.username, body.password)
        if not result:
            access.audit("anonymous", "login.failed")
            raise HTTPException(401, "用户名或密码不正确。")
        token, actor = result
        set_session(response, request, token)
        access.audit(actor.id, "login.succeeded")
        return {"user": actor.public(), "csrf_token": actor.csrf_token}

    @router.post("/api/access/logout")
    def logout(request: Request, response: Response):
        access.logout(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/api/access/users")
    def users(request: Request):
        require_admin(access, request.state.actor)
        with access.db() as db:
            rows = db.execute("SELECT id,username,role,active FROM users ORDER BY username").fetchall()
        return {"users": [dict(row) for row in rows]}

    @router.post("/api/access/users", status_code=201)
    async def create_user(request: Request):
        require_admin(access, request.state.actor)
        if not access.enabled():
            raise HTTPException(409, "请先创建首位管理员。")
        body = await validated(request, Credentials)
        user = await run_in_threadpool(access.create_user, body.username, body.password)
        access.audit(request.state.actor.id, "user.created", user["id"])
        return user

    @router.put("/api/access/users/{user_id}")
    def update_user(user_id: str, body: AccountInput, request: Request):
        require_admin(access, request.state.actor)
        with access.db() as db:
            user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "成员不存在。")
            if user[0] == "admin":
                raise HTTPException(409, "不能在此停用管理员。")
            db.execute("UPDATE users SET active=? WHERE id=?", (int(body.active), user_id))
            if not body.active:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        access.audit(request.state.actor.id, "user.updated", user_id, {"active": body.active})
        return {"ok": True}

    @router.get("/api/access/grants")
    def grants(request: Request, collection_id: str = "enterprise"):
        require_admin(access, request.state.actor)
        validate_collection(collection_id)
        documents = service.store.list_documents(collection_id)
        with access.db() as db:
            rows = db.execute("SELECT user_id,role FROM collection_grants WHERE collection=?", (collection_id,)).fetchall()
            policies = {row[0]: bool(row[1]) for row in db.execute("SELECT * FROM document_policies")}
            identities = {doc["document_id"] for doc in documents}
            document_grants = [dict(row) for row in db.execute("SELECT * FROM document_grants") if row["document_id"] in identities]
        return {"grants": [dict(r) for r in rows],
                "documents": [{**d, "restricted": policies.get(d["document_id"], False)} for d in documents],
                "document_grants": document_grants}

    @router.put("/api/access/grants")
    def grant(body: GrantInput, request: Request):
        require_admin(access, request.state.actor)
        access.grant(body.collection_id, body.user_id, body.role)
        access.audit(request.state.actor.id, "collection.grant", body.collection_id, {"user_id": body.user_id, "role": body.role})
        return {"ok": True}

    @router.put("/api/access/document-grants")
    def document_grant(body: DocumentGrantInput, request: Request):
        require_admin(access, request.state.actor)
        service.store.get(body.document_id, body.collection_id)
        access.grant(body.collection_id, body.user_id, body.role, body.document_id, body.restricted)
        access.audit(request.state.actor.id, "document.grant", body.document_id, {"user_id": body.user_id, "role": body.role, "restricted": body.restricted})
        return {"ok": True}

    @router.get("/api/access/audit")
    def audit(request: Request):
        require_admin(access, request.state.actor)
        with access.db() as db:
            events = db.execute("SELECT id,at,actor,action,target,detail FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return {"events": [dict(e) for e in events]}

    return router
