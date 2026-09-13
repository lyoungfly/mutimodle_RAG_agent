from typing import Any

from papermind.errors import ModelResponseError
from papermind.llm.client import LanguageModel
from papermind.models import SearchHit

REFUSAL = "当前知识库中的资料不足以回答该问题。"


def generate_answer(
    question: str, hits: list[SearchHit], sources: list[dict], llm: LanguageModel | None
) -> dict[str, Any]:
    if not hits:
        return {
            "answer": REFUSAL,
            "sources": [],
            "abstained": True,
            "mode": "no_evidence",
        }
    if llm is None:
        excerpts = [f"{hit.chunk.content} [{i}]" for i, hit in enumerate(hits, 1)]
        return {
            "answer": "未配置生成模型，以下为检索证据（图像描述如有生成，会单独标注）：\n\n"
            + "\n\n".join(excerpts),
            "sources": sources,
            "abstained": False,
            "mode": "evidence_only",
        }
    evidence = [
        {
            "id": i,
            "content": h.chunk.content,
            "section": h.chunk.section,
            "content_type": h.chunk.content_type,
            "metadata": h.chunk.metadata,
        }
        for i, h in enumerate(hits, 1)
    ]
    result = llm.answer(question, evidence)
    if result.get("abstain") is True:
        return {
            "answer": REFUSAL,
            "sources": [],
            "abstained": True,
            "mode": "generated",
        }
    claims = result.get("claims")
    if result.get("abstain") is not False or not isinstance(claims, list) or not claims:
        raise ModelResponseError("Model response does not contain validated claims")
    if len(claims) > 50:
        raise ModelResponseError("Model returned too many claims")
    lines, used = [], set()
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("text"), str)
            or not claim["text"].strip()
        ):
            raise ModelResponseError("Model returned an invalid claim")
        ids = claim.get("citations")
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(i) is not int or not 1 <= i <= len(hits) for i in ids)
        ):
            raise ModelResponseError("Model returned a missing or nonexistent citation")
        used.update(ids)
        lines.append(
            claim["text"].strip() + " " + "".join(f"[{i}]" for i in dict.fromkeys(ids))
        )
    return {
        "answer": "\n\n".join(lines),
        "sources": [s for s in sources if s["id"] in used],
        "abstained": False,
        "mode": "generated",
    }
