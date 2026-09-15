"""企业表格的受控运算；请求不包含代码，原始单元格始终作为数据处理。"""

import hashlib
import json
import operator
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from urllib.parse import quote

from papermind.storage import DocumentStore

from .table_models import TableAnalysisRequest, TableFilter

MAX_ROWS = 20000
MAX_CELLS = 100000
MAX_GROUPS = 200
MAX_TEXT = 8_000_000
POLICY_VERSION = "decimal-table-v1"
MISSING_FORMULA = "[公式结果不可用]"
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?")
COMPARISONS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}
POLICY = {
    "column_index_base": 0,
    "filter_join": "and",
    "text_comparison": "Unicode NFC、去除首尾空白后区分大小写；eq/ne 按文本比较",
    "numeric_input": "仅接受十进制数及科学计数法；不自动转换单位、百分号、货币或千位分隔符",
    "missing_numeric": "选中行的数值列及数值筛选列存在空值、公式缺失或非数字时拒绝运算",
    "count": "计数包含所有选中数据行，包括空白行；表头不额外推断或移除",
    "mean": "平均值保留 40 位有效数字，ROUND_HALF_EVEN；其余数值运算使用 Decimal",
}


def _digest(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clean(value: str) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("单元格必须为文本且长度不超过 8192 字符，请整理资料后重新上传。")
    return unicodedata.normalize("NFC", value).strip()


def _decimal(value: str, position: str) -> Decimal:
    text = _clean(value)
    if text == MISSING_FORMULA:
        raise ValueError(f"{position} 的公式结果不可用，请在 Excel 重算、保存并重新上传。")
    if not text:
        raise ValueError(f"{position} 为空值，不能参与数值运算；请补齐或用明确的筛选条件排除。")
    if len(text) > 128 or NUMBER.fullmatch(text) is None:
        raise ValueError(f"{position} 不是纯数值；不自动忽略文本、单位、百分号或千位分隔符。")
    value = Decimal(text)
    if len(value.as_tuple().digits) > 64 or abs(value.adjusted()) > 100 or abs(value.as_tuple().exponent) > 100:
        raise ValueError(f"{position} 的数值精度或数量级超出计算限制。")
    return value


def _number(value: Decimal) -> str:
    if not value:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _source(record: dict, table: dict, collection: str) -> dict:
    location = dict(table.get("source") or {})
    location.update(
        document_id=record["id"], filename=record["filename"], table_id=table["table_id"],
        page=table.get("page", 0), section=table.get("section", ""),
        extraction_method=table.get("extraction_method", "native"),
        file_url=f"/documents/{quote(record['id'], safe='')}/file?collection_id={quote(collection, safe='')}",
    )
    location.setdefault("format", record["suffix"].lstrip("."))
    return location


def _table_data(table: dict) -> tuple[list[str], list[list[str]]]:
    headers, rows = table.get("headers"), table.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise ValueError("表格结构无效，请重新解析文档。")
    width = len(headers)
    if len(rows) > MAX_ROWS or width * (len(rows) + 1) > MAX_CELLS:
        raise ValueError("表格分析限 20000 行、100000 个单元格，请拆分资料。")
    if not width:
        if rows:
            raise ValueError("表格缺少列定义，不能分析。")
        return [], []
    total_text = 0
    for row in [headers, *rows]:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError("表格行的列数不一致，不能自动补齐或丢弃数据。")
        for cell in row:
            _clean(cell)
            total_text += len(cell)
            if total_text > MAX_TEXT:
                raise ValueError("表格文本超过 800 万字符，请拆分资料。")
    return headers, rows


def _row_numbers(table: dict, record: dict, count: int) -> tuple[list[int], str]:
    supplied = table.get("row_numbers")
    if supplied:
        if len(supplied) != count or any(type(n) is not int or n < 1 for n in supplied) or len(set(supplied)) != count:
            raise ValueError("表格的原始行号无效，无法可靠溯源。")
        return supplied, "原始工作表行号" if record["suffix"] == ".xlsx" else "原始表格行号"
    if record["suffix"] == ".xlsx":
        if count:
            raise ValueError("Excel 缺少原始行号，请重新上传以恢复单元格溯源。")
        return [], "原始工作表行号"
    if record["suffix"] == ".csv":
        return list(range(2, count + 2)), "CSV 逻辑记录号（含首条表头，不等同于物理文本行号）"
    return list(range(1, count + 1)), "解析后的数据行序号（不含表头）"


def list_tables(store: DocumentStore, collection: str) -> list[dict]:
    """仅返回指定知识库中的表结构；调用方负责从身份固定 collection。"""
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", collection) is None:
        raise ValueError("知识库标识无效。")
    result = []
    for document in store.list_documents(collection):
        record = store.get(document["document_id"], collection)
        for table in record["body"].get("tables", []):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            result.append({
                "document_id": record["id"], "filename": record["filename"],
                "table_id": table["table_id"], "caption": table.get("caption", ""),
                "headers": headers,
                "columns": [{"index": i, "name": name, "label": f"{i + 1}. {name or '未命名列'}"} for i, name in enumerate(headers)],
                "row_count": len(rows), "column_count": len(headers),
                "source": _source(record, table, collection),
                "warnings": record["body"].get("metadata", {}).get("warnings", []),
            })
            if len(result) > 1000:
                raise ValueError("知识库超过 1000 张表格，请按业务拆分知识库后分析。")
    return result


def _matches(row: list[str], row_number: int, filters: list[TableFilter]) -> bool:
    matched = True
    # 全部条件均检查，避免筛选顺序悄悄掩盖数值列中的坏数据。
    for condition in filters:
        left, right = _clean(row[condition.column]), _clean(condition.value)
        if condition.operator in COMPARISONS:
            position = f"行 {row_number}、列 {condition.column + 1}"
            accepted = COMPARISONS[condition.operator](
                _decimal(left, position), _decimal(right, "筛选条件"),
            )
        elif condition.operator == "contains":
            accepted = right in left
        elif condition.operator == "eq":
            accepted = left == right
        else:
            accepted = left != right
        matched = accepted and matched
    return matched


def _aggregate(operation: str, selected: list[tuple[int, list[str]]], spec: TableAnalysisRequest) -> tuple[int | str | None, list[dict]]:
    grouped = spec.group_by is not None
    values, groups = [], {}
    with localcontext() as context:
        context.prec = 256
        for row_number, row in selected:
            number = _decimal(row[spec.column], f"行 {row_number}、列 {spec.column + 1}") if spec.column is not None else None
            if number is not None:
                values.append(number)
            if grouped:
                label = _clean(row[spec.group_by])
                if label == MISSING_FORMULA:
                    raise ValueError(f"行 {row_number} 的分组列缺少公式结果，不能建立可靠分组。")
                if label not in groups:
                    if len(groups) >= MAX_GROUPS:
                        raise ValueError("分组结果超过 200 组，请增加筛选条件；不会截断或合并分组。")
                    groups[label] = {"count": 0, "value": Decimal(0), "row_numbers": []}
                group = groups[label]
                group["count"] += 1
                group["row_numbers"].append(row_number)
                if number is not None:
                    group["value"] += number
        if operation in {"count", "group_count"}:
            value = len(selected)
        elif operation in {"sum", "group_sum"}:
            value = _number(sum(values, Decimal(0)))
        elif not values:
            value = None
        elif operation == "mean":
            total = sum(values, Decimal(0))
            with localcontext() as mean_context:
                mean_context.prec = 40
                mean_context.rounding = ROUND_HALF_EVEN
                value = _number(total / len(values))
        else:
            value = _number(min(values) if operation == "min" else max(values))
        result = [{
            "key": key, "label": key or "（空白）", "count": group["count"],
            "value": group["count"] if operation == "group_count" else _number(group["value"]),
            "row_numbers": group["row_numbers"],
        } for key, group in sorted(groups.items())]
    return value, result


def analyze_table(store: DocumentStore, collection: str, spec: TableAnalysisRequest | dict) -> dict:
    """执行完整选中行上的统计；输出预览限制不会影响计算结果。"""
    spec = TableAnalysisRequest.model_validate(spec)
    if collection != spec.collection_id:
        raise ValueError("分析请求的知识库与服务端授权知识库不一致。")
    record = store.get(spec.document_id, collection)
    table = next((t for t in record["body"].get("tables", []) if t["table_id"] == spec.table_id), None)
    if table is None:
        raise KeyError(spec.table_id)
    headers, rows = _table_data(table)
    columns = [spec.column, spec.group_by, *(item.column for item in spec.filters)]
    if any(column is not None and column >= len(headers) for column in columns):
        raise ValueError("列索引超出表格范围；column 和 group_by 从 0 开始。")
    for condition in spec.filters:
        if condition.operator in COMPARISONS:
            _decimal(condition.value, "筛选条件")
    row_numbers, row_number_kind = _row_numbers(table, record, len(rows))
    selected = [(number, row) for number, row in zip(row_numbers, rows) if _matches(row, number, spec.filters)]
    value, groups = _aggregate(spec.operation, selected, spec)
    source = _source(record, table, collection)
    source["row_number_kind"] = row_number_kind
    parameters = spec.model_dump(exclude={"document_id", "table_id", "collection_id"})
    table_hash = _digest(table)
    identity = {"policy_version": POLICY_VERSION, "collection_id": collection, "document_id": record["id"], "table_id": table["table_id"], "table_sha256": table_hash, "parameters": parameters}
    warnings = list(record["body"].get("metadata", {}).get("warnings", []))
    warnings.extend([
        "统计仅依据当前解析表格；单元格文本不执行为公式、指令或代码。",
        "文字筛选和分组去除首尾空白并进行 Unicode NFC 规范化；原始预览保持不变。",
    ])
    if len(set(map(_clean, headers))) != len(headers):
        warnings.append("存在重名列，所有操作均按列索引区分，不合并同名字段。")
    if any(MISSING_FORMULA in row for row in rows):
        warnings.append("表内存在无缓存公式；当前操作未使用的列不会影响结果，计数仍包含这些行。")
    if table.get("extraction_method") == "vlm":
        warnings.append("当前表格来自视觉模型识别，数值准确性仍需对照原图核实。")
    if not selected:
        warnings.append("没有符合条件的数据行：计数和求和为 0，均值及极值为空。")
    if spec.operation == "mean":
        warnings.append(POLICY["mean"])
    preview_count = min(50, 2000 // max(1, len(headers)))
    preview = [{"row_number": n, "values": row} for n, row in selected[:preview_count]]
    if len(preview) < len(selected):
        warnings.append(f"仅预览前 {len(preview)} 行；统计与原始行号列表包含全部 {len(selected)} 行。")
    return {
        "calculation_id": "calc_" + _digest(identity),
        "collection_id": collection, "document_id": record["id"],
        "filename": record["filename"], "table_id": table["table_id"],
        "source": source, "headers": headers, "parameters": parameters,
        "selected_row_numbers": [number for number, _ in selected],
        "summary": {"operation": spec.operation, "value": value, "total_rows": len(rows), "selected_rows": len(selected), "excluded_rows": len(rows) - len(selected), "group_count": len(groups), "preview_rows": len(preview)},
        "groups": groups, "rows": preview, "warnings": warnings, "policy": POLICY,
        "snapshot": {**identity, "source": source, "source_path": source["file_url"], "headers": headers, "row_count": len(rows)},
    }
