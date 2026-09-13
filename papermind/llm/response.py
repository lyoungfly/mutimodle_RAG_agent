import json
import re

from papermind.errors import ModelResponseError


class IncompleteModelResponse(ModelResponseError):
    def __init__(self, message: str, *, truncated: bool = False):
        super().__init__(message)
        self.truncated = truncated


def parse_completion(body: object) -> dict:
    """只解析最终回答；不从推理或混杂文本中猜测 JSON。"""
    try:
        choice = body["choices"][0]
        message = choice["message"]
        if not isinstance(choice, dict) or not isinstance(message, dict):
            raise TypeError
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelResponseError(
            "模型接口响应结构不兼容，请检查模型和 API 地址。"
        ) from exc
    if choice.get("finish_reason") == "length":
        raise IncompleteModelResponse(
            "模型输出达到长度上限，回答被截断；请缩小问题范围后重试。",
            truncated=True,
        )
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise ModelResponseError("模型服务拒绝了本次请求，请调整问题后重试。")
    content = message.get("content")
    if isinstance(content, list):
        if not all(
            isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            for part in content
        ):
            raise ModelResponseError(
                "模型返回了不兼容的内容格式，请使用支持文本 JSON 输出的模型。"
            )
        content = "".join(part["text"] for part in content)
    if content is None or (isinstance(content, str) and not content.strip()):
        raise IncompleteModelResponse("模型返回了空回答，请重试或检查模型输出配置。")
    if not isinstance(content, str):
        raise ModelResponseError(
            "模型返回了不兼容的内容格式，请使用支持文本 JSON 输出的模型。"
        )
    content = content.strip().lstrip("\ufeff").strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*\n(.*?)\n\s*```", content, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        content = fenced.group(1).strip()
    try:
        result = json.loads(content)
    except ValueError as exc:
        raise IncompleteModelResponse(
            "模型未返回有效 JSON，请重试或切换到支持 JSON 输出的模型。"
        ) from exc
    if not isinstance(result, dict):
        raise ModelResponseError(
            "模型输出必须是 JSON 对象，请检查模型的 JSON 输出能力。"
        )
    return result


def rejects_json_format(response) -> bool:
    """仅在上游明确拒绝可选参数时降级，保留其他配置错误。"""
    if response.status_code not in {400, 422}:
        return False
    try:
        error = response.json()["error"]
        message = error.get("message", "").lower()
        return ("response_format" in message or "json_object" in message) and any(
            word in message
            for word in (
                "not supported",
                "unsupported",
                "not support",
                "unknown",
                "unrecognized",
                "not permitted",
                "not allowed",
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
