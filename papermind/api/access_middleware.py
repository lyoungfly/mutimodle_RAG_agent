import hmac
import ipaddress

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from papermind.enterprise.access_store import Principal

COOKIE = "papermind_session"


def local_request(request):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = request.client is not None and request.client.host == "testclient"
    return local and request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}


class AccessMiddleware:
    def __init__(self, app, access):
        self.app, self.access = app, access

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = request.url.path, request.method
        enabled = await run_in_threadpool(self.access.enabled)
        actor = await run_in_threadpool(self.access.session, request.cookies.get(COOKIE)) if enabled else None
        if not enabled and local_request(request):
            actor = Principal("local", "本机工作空间", "admin")
        scope.setdefault("state", {})["actor"] = actor
        public = path in {"/", "/settings", "/access", "/health", "/api/access/me", "/api/access/login", "/api/access/bootstrap"} or path.startswith("/static/")
        error, status = None, 403
        if not public and actor is None:
            error, status = ("请先登录后访问资料。", 401) if enabled else ("请从本机访问，或先在本机启用成员访问管理。", 403)
        if method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
                error = "不允许跨站提交请求。"
            if enabled and actor and path not in {"/api/access/login", "/api/access/bootstrap"}:
                if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), actor.csrf_token):
                    error = "会话校验失败，请刷新页面后重试。"
        if error:
            await run_in_threadpool(self.access.audit, actor.id if actor else "anonymous", "access.denied", path, {"method": method, "status": status})
            return await JSONResponse({"detail": error}, status_code=status)(scope, receive, send)

        async def no_cache(message):
            if message["type"] == "http.response.start" and not path.startswith("/static/"):
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, no_cache)
