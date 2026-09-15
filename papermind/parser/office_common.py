from pathlib import Path
from zipfile import BadZipFile, ZipFile


def validate_office_archive(path: Path):
    """限制 Office 解压规模，拒绝 DTD、实体及超大工作表坐标。"""
    from defusedxml.common import DefusedXmlException
    from defusedxml.ElementTree import iterparse

    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(e.file_size for e in entries) > 64 * 1024**2:
                raise ValueError("Office 文件解压后过大，请拆分后上传。")
            if len({e.filename for e in entries}) != len(entries):
                raise ValueError("Office 文件含重复条目，请重新另存为 DOCX/XLSX。")
            nodes = 0
            for entry in entries:
                if entry.file_size > 32 * 1024**2 or entry.flag_bits & 1:
                    raise ValueError(
                        "Office 文件条目过大或已加密，请解密或拆分后上传。"
                    )
                if not entry.filename.endswith((".xml", ".rels")):
                    continue
                with archive.open(entry) as stream:
                    for _, node in iterparse(stream, events=("end",), forbid_dtd=True):
                        nodes += 1
                        if nodes > 500000:
                            raise ValueError("Office 文档结构过大，请拆分后上传。")
                        if (
                            entry.filename.startswith("xl/worksheets/")
                            and node.tag.endswith("}row")
                            and int(node.attrib.get("r", "1")) > 20000
                        ):
                            raise ValueError("工作表超过 20000 行，请拆分后上传。")
                        if entry.filename.startswith(
                            "xl/worksheets/"
                        ) and node.tag.endswith("}c"):
                            from openpyxl.utils.cell import (
                                column_index_from_string,
                                coordinate_from_string,
                            )

                            column, row = coordinate_from_string(
                                node.attrib.get("r", "A1")
                            )
                            if row > 20000 or column_index_from_string(column) > 256:
                                raise ValueError(
                                    "工作表最多支持 20000 行、256 列，请删除多余格式或拆分文件。"
                                )
                        node.clear()
    except (BadZipFile, DefusedXmlException) as exc:
        raise ValueError(
            "Office 文件损坏、已加密或包含不安全 XML，请重新另存为 DOCX/XLSX。"
        ) from exc


def office_dependencies():
    try:
        import defusedxml  # noqa: F401
        import docx  # noqa: F401
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'Word/Excel 解析依赖未安装，请运行：python -m pip install -e ".[office]"'
        ) from exc
