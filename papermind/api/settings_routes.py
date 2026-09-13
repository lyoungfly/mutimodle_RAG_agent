import ipaddress
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from papermind.model_api import APIEndpoint


class EndpointInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm: EndpointInput
    vlm: EndpointInput


def local_access(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "testclient"
    if not local:
        raise HTTPException(403, "API 配置仅允许从运行 PaperMind 的本机访问")
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
        raise HTTPException(403, "请使用 localhost 或 127.0.0.1 打开配置页")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "不允许跨站访问模型 API 配置")


async def validated(request: Request, schema):
    try:
        return schema.model_validate(await request.json())
    except (ValidationError, ValueError):
        # 不返回 Pydantic 的 input 字段，避免无效请求中的密钥被回显。
        raise HTTPException(
            422, "配置格式不正确，请检查开关、地址、模型名称和密钥长度"
        ) from None


def probe(endpoint: APIEndpoint, kind: str) -> dict:
    if not endpoint.model:
        raise ValueError("请先填写模型名称，再测试连接")
    content = "Reply with OK."
    if kind == "vlm":
        content = [
            {
                "type": "text",
                "text": "Describe the color in this test image in one word.",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAANUlEQVR4nO3QsQ0AMAzDsLT//9yeoCkbeYAN6LzZdZf3x0GSKEmUJEoSJYmSREmiJFGSaMoHo8QBPwYSAhsAAAAASUVORK5CYII="
                },
            },
        ]
    headers = (
        {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    )
    try:
        # 测试不带论文内容，不跟随重定向，防止密钥被转发到其他服务。
        with httpx.Client(
            timeout=httpx.Timeout(25, connect=8), follow_redirects=False
        ) as client:
            response = client.post(
                f"{endpoint.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": endpoint.model,
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": content}],
                },
            )
        if response.status_code >= 300:
            messages = {
                401: "密钥无效或未填写，请检查 API Key。",
                403: "没有访问权限，请检查密钥权限或模型授权。",
                404: "地址或模型不存在，请检查 Base URL 和模型 ID。",
                429: "请求受限或额度不足，请检查服务商额度后重试。",
            }
            return {
                "ok": False,
                "message": messages.get(
                    response.status_code,
                    f"服务返回 HTTP {response.status_code}，请核对接口兼容性与模型参数。",
                ),
            }
        text = response.json()["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError
    except httpx.TimeoutException:
        return {
            "ok": False,
            "message": "连接超时，请检查网络或等待模型服务启动后重试。",
        }
    except httpx.HTTPError:
        return {
            "ok": False,
            "message": "无法连接服务，请检查 API 地址、网络及 HTTPS 证书。",
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return {
            "ok": False,
            "message": "服务已响应，但未返回兼容的文本内容；请检查模型和接口格式。",
        }
    return {
        "ok": True,
        "message": "测试请求成功。"
        + (
            "已提交测试图片；实际图表识别质量需用文献验证。"
            if kind == "vlm"
            else "可以保存并用于回答。"
        )
        + " 测试不会保存配置。",
    }


def settings_router(service) -> APIRouter:
    router = APIRouter(dependencies=[Depends(local_access)])

    @router.get("/settings", include_in_schema=False)
    def page():
        return FileResponse(
            Path(__file__).parent / "static" / "settings.html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/settings")
    def current():
        return service.api_settings()

    @router.put("/api/settings")
    async def save(request: Request):
        body = await validated(request, SettingsInput)
        # 文件写入和模型切换由服务锁统一管理。
        await run_in_threadpool(service.configure_apis, body.model_dump())
        return {
            "message": "已保存并立即生效。视觉模型变更后，请重新索引需要分析图表的文献。",
            **service.api_settings(),
        }

    @router.post("/api/settings/test/{kind}")
    async def test(kind: Literal["llm", "vlm"], request: Request):
        body = await validated(request, EndpointInput)
        endpoint = await run_in_threadpool(service.resolve_api, kind, body.model_dump())
        return await run_in_threadpool(probe, endpoint, kind)

    return router
