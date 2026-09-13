import pytest

from papermind.chunking.structure_chunker import StructureChunker, split_text
from papermind.models import Document, Paragraph, Section, Table
from papermind.parser import DocumentParser


def test_chunk_boundaries_and_hierarchy():
    document = Document(
        "d",
        "Paper",
        [
            Section("3 Method", 1, [Paragraph("A" * 100, 1)]),
            Section(
                "3.1 Detail",
                2,
                [
                    Paragraph("First sentence. Second sentence.", 1),
                    Paragraph("Next page.", 2),
                ],
            ),
        ],
    )
    chunks = StructureChunker(32).chunk(document)
    assert all(len(c.content) <= 32 for c in chunks)
    assert "".join(c.content for c in chunks if c.section == "3 Method") == "A" * 100
    details = [c for c in chunks if c.section == "3.1 Detail"]
    assert {c.page for c in details} == {1, 2}
    assert all(c.metadata["parent_section"] == "3 Method" for c in details)
    assert chunks == StructureChunker(32).chunk(document)


def test_split_sentence_and_multilingual_boundary():
    assert split_text("第一句话。第二句话。第三句话。", 10) == [
        "第一句话。第二句话。",
        "第三句话。",
    ]


def test_structured_csv_is_preserved(tmp_path):
    path = tmp_path / "table.csv"
    path.write_text('Model,Params,PSNR\n"Model, A",4M,27.38\n', encoding="utf-8")
    document = DocumentParser().parse(path, "d", path.name)
    assert document.tables[0].rows == [["Model, A", "4M", "27.38"]]
    chunks = StructureChunker().chunk(document)
    assert chunks[0].content_type == "table"
    assert chunks[0].metadata == {"table_id": "table_1", "row_index": 0}


def test_empty_tables_and_text_do_not_create_fake_evidence():
    document = Document("d", "Empty", tables=[Table("t", 1, ["Model"], [])])
    assert StructureChunker().chunk(document) == []


def test_pdf_page_and_coordinates(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "test.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "1 Method")
        page.insert_text((72, 110), "Mamba is the test architecture.")
        page = pdf.new_page()
        page.insert_text((72, 72), "Urban100 PSNR is 27.38 in this synthetic fixture.")
        pdf.save(path)
    document = DocumentParser().parse(path, "d", "test.pdf")
    chunks = StructureChunker().chunk(document)
    assert [c.page for c in chunks] == [1, 2]
    assert all(c.section == "1 Method" for c in chunks)
    assert all(c.metadata["bboxes"] for c in chunks)
    with pytest.raises(ValueError, match="page limit"):
        DocumentParser(max_pages=1).parse(path, "d", "test.pdf")


def test_scanned_pdf_warning(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "empty.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    document = DocumentParser().parse(path, "d", path.name)
    assert "OCR" in document.metadata["warnings"][0]


def test_damaged_pdf_has_actionable_error(tmp_path):
    pytest.importorskip("pymupdf")
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="damaged PDF"):
        DocumentParser().parse(path, "d", path.name)
