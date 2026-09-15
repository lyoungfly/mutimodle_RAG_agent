import io
from dataclasses import asdict
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from papermind.api.main import create_app
from papermind.chunking.structure_chunker import StructureChunker
from papermind.parser import DocumentParser
from papermind.storage import document_from_dict

docx = pytest.importorskip("docx")
openpyxl = pytest.importorskip("openpyxl")


def word_bytes():
    document = docx.Document()
    document.add_heading("维护要求", 1)
    document.add_paragraph("冷却系统每周检查一次。")
    document.add_heading("检查步骤", 2)
    document.add_paragraph("检查水泵和过滤器。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "设备"
    table.cell(0, 1).text = "检查周期"
    table.cell(1, 0).text = "水泵"
    table.cell(1, 1).text = "每周"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def workbook_bytes():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "六月"
    sheet.append([])
    sheet.append(["设备", "故障次数"])
    sheet.append(["冷却水泵", 3])
    sheet.append([])
    sheet.append(["过滤器", 2])
    sheet.append(["合计", "=SUM(B3:B5)"])
    hidden = book.create_sheet("隐藏记录")
    hidden.sheet_state = "hidden"
    hidden.append(["不应索引"])
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def parse(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return DocumentParser().parse(path, "test", name)


def test_word_paragraphs_tables_and_roundtrip(tmp_path):
    document = parse(tmp_path, "manual.docx", word_bytes())
    chunks = StructureChunker().chunk(document)
    fact = next(c for c in chunks if "每周检查" in c.content)
    assert fact.page == 0
    assert fact.metadata["source"] == {
        "format": "docx",
        "paragraph": 2,
        "heading_path": "维护要求",
    }
    detail = next(c for c in chunks if "检查水泵" in c.content)
    assert detail.metadata["source"]["heading_path"] == "维护要求 / 检查步骤"
    table = document.tables[0]
    assert table.rows == [["设备", "检查周期"], ["水泵", "每周"]]
    assert table.row_numbers == [1, 2]
    assert document_from_dict(asdict(document)) == document
    split = StructureChunker(16).chunk(document)
    assert all(len(c.content) <= 16 for c in split)
    assert all(c.metadata.get("source") for c in split)


def test_excel_preserves_gaps_and_missing_formula(tmp_path):
    document = parse(tmp_path, "records.xlsx", workbook_bytes())
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.row_numbers == [3, 5, 6]
    assert table.headers == ["设备", "故障次数"]
    assert table.rows[-1][1] == "[公式结果不可用]"
    assert any("1 个公式" in w for w in document.metadata["warnings"])
    chunks = StructureChunker().chunk(document)
    assert [c.metadata["source"]["cell_range"] for c in chunks] == [
        "A3:B3",
        "A5:B5",
        "A6:B6",
    ]
    assert all(c.page == 0 for c in chunks)
    assert document_from_dict(asdict(document)) == document


def rewrite_zip(content, name, transform):
    buffer = io.BytesIO()
    with (
        ZipFile(io.BytesIO(content)) as source,
        ZipFile(buffer, "w", ZIP_DEFLATED) as target,
    ):
        for entry in source.infolist():
            raw = source.read(entry.filename)
            target.writestr(
                entry.filename, transform(raw) if entry.filename == name else raw
            )
    return buffer.getvalue()


def test_formula_cache_is_used_without_evaluating(tmp_path):
    content = rewrite_zip(
        workbook_bytes(),
        "xl/worksheets/sheet1.xml",
        lambda raw: raw.replace(
            b"<f>SUM(B3:B5)</f><v></v>", b"<f>SUM(B3:B5)</f><v>5</v>"
        ),
    )
    document = parse(tmp_path, "cached.xlsx", content)
    assert document.tables[0].rows[-1][1] == "5"
    assert not any("缺少缓存" in w for w in document.metadata["warnings"])


@pytest.mark.parametrize("suffix", ["docx", "xlsx"])
def test_damaged_office_files_have_clear_error(tmp_path, suffix):
    with pytest.raises(ValueError, match="Office 文件"):
        parse(tmp_path, f"bad.{suffix}", b"not an office document")


def test_unsafe_xml_is_rejected(tmp_path):
    content = rewrite_zip(
        workbook_bytes(),
        "xl/worksheets/sheet1.xml",
        lambda raw: b'<!DOCTYPE worksheet [<!ENTITY x "unsafe">]>' + raw,
    )
    with pytest.raises(ValueError, match="不安全 XML"):
        parse(tmp_path, "unsafe.xlsx", content)


def test_huge_sparse_coordinates_are_rejected(tmp_path):
    content = rewrite_zip(
        workbook_bytes(),
        "xl/worksheets/sheet1.xml",
        lambda raw: raw.replace(b'r="B6"', b'r="B999999"'),
    )
    with pytest.raises(ValueError, match="20000"):
        parse(tmp_path, "huge.xlsx", content)


def test_enterprise_api_ingest_search_sources_and_isolation(service):
    with TestClient(create_app(service=service)) as client:
        for filename, content, query, kind in [
            ("manual.docx", word_bytes(), "冷却系统每周检查", "docx"),
            ("records.xlsx", workbook_bytes(), "冷却水泵", "xlsx"),
        ]:
            uploaded = client.post(
                "/documents/upload",
                data={"collection_id": "enterprise"},
                files={"file": (filename, content)},
            )
            assert uploaded.status_code == 201
            identity = uploaded.json()["document_id"]
            indexed = client.post(
                "/documents/index",
                json={"document_id": identity, "collection_id": "enterprise"},
            )
            assert indexed.status_code == 200
            response = client.post(
                "/chat",
                json={
                    "workspace_mode": "enterprise",
                    "question": query,
                    "collection_id": "enterprise",
                    "mode": "bm25",
                },
            )
            assert response.status_code == 200
            answer = response.json()
            assert answer["workspace_mode"] == "enterprise"
            source = next(s for s in answer["sources"] if s["document_id"] == identity)
            assert source["metadata"]["source"]["format"] == kind
            assert "#page=" not in source["url"]
            raw = client.get(f"/documents/{identity}/file?collection_id=enterprise")
            assert raw.content == content
            assert "attachment" in raw.headers["content-disposition"]
            assert "openxmlformats" in raw.headers["content-type"]
            assert (
                client.get(
                    f"/documents/{identity}/file?collection_id=default"
                ).status_code
                == 404
            )
        assert client.get("/documents?collection_id=default").json() == []
        assert (
            client.post(
                "/chat", json={"question": "test", "workspace_mode": "unknown"}
            ).status_code
            == 422
        )
