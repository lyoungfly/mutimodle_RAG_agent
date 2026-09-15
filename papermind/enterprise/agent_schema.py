"""企业分析结果的结构与引用约束。"""

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


ShortText = Annotated[str, Field(min_length=1, max_length=2000)]
EvidenceId = Annotated[str, Field(min_length=1, max_length=100)]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: ShortText
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=12)


class AnalysisResult(BaseModel):
    """只能依据工具证据填写；建议与事实分开，资料不足时列出缺口。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: ShortText
    summary_evidence_ids: list[EvidenceId] = Field(max_length=12)
    findings: list[Finding] = Field(max_length=30)
    conflicts: list[Finding] = Field(max_length=10)
    recommendations: list[ShortText] = Field(max_length=15)
    missing_information: list[ShortText] = Field(max_length=15)


def validate_analysis(value: object, evidence: list[dict]) -> dict:
    try:
        result = AnalysisResult.model_validate(value).model_dump()
    except (ValueError, TypeError) as exc:
        raise ValueError("Agent 未返回符合约定的分析结构，请缩小任务范围后重试。") from exc
    known = {item["evidence_id"] for item in evidence}
    references = [result["summary_evidence_ids"]]
    references.extend(item["evidence_ids"] for item in result["findings"])
    references.extend(item["evidence_ids"] for item in result["conflicts"])
    if any(len(ids) != len(set(ids)) or not set(ids) <= known for ids in references):
        raise ValueError("Agent 引用了不存在或重复的证据，结果未发布。")
    if not result["summary_evidence_ids"]:
        if result["findings"] or result["conflicts"] or not result["missing_information"]:
            raise ValueError("分析摘要缺少来源引用，结果未发布。")
        result["summary"] = "当前资料不足以形成有据可查的结论，请补充所列资料。"
        result["recommendations"] = []
    return result


def validate_report(result: dict) -> dict:
    """导出只接受已完成任务的有界快照，不重新调用模型。"""
    if not isinstance(result, dict):
        raise ValueError("报告结果格式不正确。")
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(raw.encode("utf-8")) > 2_000_000:
        raise ValueError("报告快照超过 2 MB，请拆分分析任务。")
    evidence = result.get("evidence", [])
    calculations = result.get("calculations", [])
    document_ids = result.get("document_ids", [])
    if (
        not isinstance(evidence, list) or len(evidence) > 64
        or not isinstance(calculations, list) or len(calculations) > 20
        or not isinstance(document_ids, list) or len(document_ids) > 200
        or any(not isinstance(item, str) for item in document_ids)
    ):
        raise ValueError("报告来源数量或格式超出限制。")
    ids = set()
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("evidence_id"), str)
            or item["evidence_id"] in ids
            or item.get("document_id") not in document_ids
        ):
            raise ValueError("报告证据缺少唯一编号或对应文档。")
        ids.add(item["evidence_id"])
    calculation_ids = set()
    for item in calculations:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("calculation_id"), str)
            or item["calculation_id"] in calculation_ids
            or item.get("document_id") not in document_ids
        ):
            raise ValueError("报告计算记录缺少唯一编号或对应文档。")
        calculation_ids.add(item["calculation_id"])
    if any(
        item.get("kind") == "calculation"
        and item.get("calculation_id") not in calculation_ids
        for item in evidence
    ):
        raise ValueError("报告计算引用缺少计算记录。")
    fields = {name: result.get(name) for name in AnalysisResult.model_fields}
    validated = validate_analysis(fields, evidence)
    if not isinstance(result.get("question"), str) or not 1 <= len(result["question"]) <= 8000:
        raise ValueError("报告任务描述格式不正确。")
    return {**result, **validated}
