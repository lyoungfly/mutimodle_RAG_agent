"""模型连接配置：校验、脱敏展示与原子持久化。"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from papermind.config import Settings

KINDS = ("llm", "vlm")


def normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("API 地址不能包含空格或控制字符")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError("API 地址格式不正确") from None
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or port == 0
    ):
        raise ValueError(
            "请填写 http(s) API 基础地址，不要包含密钥、查询参数或网页片段"
        )
    path = url.path.removesuffix("/chat/completions").rstrip("/")
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


@dataclass(frozen=True, repr=False)
class APIEndpoint:
    enabled: bool
    base_url: str
    model: str
    api_key: str = ""

    def public(self) -> dict:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "has_api_key": bool(self.api_key),
        }

    def updated(self, patch: dict) -> "APIEndpoint":
        data = {**self.public(), **patch}
        url = normalize_url(data["base_url"])
        model = data["model"].strip()
        if data["enabled"] and not model:
            raise ValueError("启用模型前，请填写服务商提供的模型 ID")
        if any(ord(c) < 32 for c in model):
            raise ValueError("模型名称不能包含控制字符")
        key = patch.get("api_key")
        clear = patch.get("clear_api_key", False)
        if clear and key:
            raise ValueError("不能同时填写新密钥和清除密钥")
        if key is None and not clear and self.api_key and url != self.base_url:
            raise ValueError("API 地址已改变，请重新填写对应密钥，或勾选清除旧密钥")
        key = "" if clear else self.api_key if key is None else key.strip()
        if any(ord(c) < 32 or ord(c) > 126 for c in key):
            raise ValueError("密钥含有无效字符，请重新复制 API Key")
        return APIEndpoint(data["enabled"], url, model, key)


def apply_endpoints(settings: Settings, endpoints: dict[str, APIEndpoint]) -> Settings:
    changes = {}
    for kind, endpoint in endpoints.items():
        changes.update(
            {
                f"{kind}_base_url": endpoint.base_url,
                f"{kind}_model": endpoint.model if endpoint.enabled else "",
                f"{kind}_api_key": endpoint.api_key,
            }
        )
    return replace(settings, **changes)


class APIConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir.resolve() / "model-api.json"

    def load(self, settings: Settings) -> dict[str, APIEndpoint]:
        endpoints = {
            kind: APIEndpoint(
                bool(getattr(settings, f"{kind}_model")),
                getattr(settings, f"{kind}_base_url"),
                getattr(settings, f"{kind}_model"),
                getattr(settings, f"{kind}_api_key"),
            )
            for kind in KINDS
        }
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                for kind in KINDS:
                    endpoints[kind] = APIEndpoint(**saved[kind]).updated({})
            except (ValueError, TypeError, KeyError, AttributeError):
                raise RuntimeError(
                    "本地模型 API 配置文件格式无效，请检查 model-api.json"
                ) from None
        return endpoints

    def save(self, endpoints: dict[str, APIEndpoint]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(
                    {kind: asdict(item) for kind, item in endpoints.items()},
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
