import io

import pytest
from PIL import Image

from papermind.config import Settings
from papermind.parser import DocumentParser
from papermind.parser.assets import AssetBuffer
from papermind.service import PaperMindService


def png_bytes(color="red", size=(200, 120)):
    with Image.new("RGB", size, color) as image:
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()


def make_figure_pdf(rotation=0, vector=False):
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=600)
        page.insert_text((40, 45), "1 Method")
        page.insert_text((40, 80), "The network uses red feature blocks.")
        if vector:
            page.draw_rect((40, 110, 200, 210), color=(1, 0, 0), fill=(1, 0, 0))
        else:
            page.insert_image((40, 100, 240, 220), stream=png_bytes())
        page.insert_text((40, 244), "Figure 3. Red feature extraction architecture.")
        page.insert_text((40, 310), "2 Experiments")
        page.insert_text((40, 340), "Evaluation uses a different dataset.")
        page.set_rotation(rotation)
        return pdf.tobytes()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_figure_caption_section_crop_and_rotation(tmp_path, rotation):
    path = tmp_path / "figure.pdf"
    path.write_bytes(make_figure_pdf(rotation))
    assets = AssetBuffer()
    document = DocumentParser().parse(path, "d", path.name, assets)
    assert len(document.figures) == 1
    figure = document.figures[0]
    assert figure.caption.startswith("Figure 3")
    assert figure.section == "1 Method"
    assert "red feature blocks" in figure.nearby_text
    assert figure.page == 1 and figure.bbox
    assert figure.analysis_status == "not_configured"
    with Image.open(io.BytesIO(assets.items[figure.asset_id])) as image:
        assert image.getpixel((image.width // 2, image.height // 2))[0] > 240
        assert image.getpixel((image.width // 2, image.height // 2))[1] < 20


def test_vector_figure_is_rasterized_with_caption(tmp_path):
    path = tmp_path / "vector.pdf"
    path.write_bytes(make_figure_pdf(vector=True))
    assets = AssetBuffer()
    document = DocumentParser().parse(path, "d", path.name, assets)
    assert document.figures[0].extraction_method == "caption_vector_region"
    assert assets.items[document.figures[0].asset_id].startswith(b"\x89PNG")


def test_standalone_image_resize_and_byte_limit(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(png_bytes(size=(600, 400)))
    assets = AssetBuffer()
    document = DocumentParser(max_image_edge=100).parse(path, "d", path.name, assets)
    with Image.open(io.BytesIO(assets.items[document.figures[0].asset_id])) as image:
        assert image.width == 100 and image.height <= 100
    with pytest.raises(ValueError, match="pixel limit"):
        DocumentParser(max_image_pixels=10).parse(path, "d", path.name)
    with pytest.raises(ValueError, match="byte limit"):
        DocumentParser().parse(path, "d", path.name, AssetBuffer(max_bytes=10))


def test_invalid_image_does_not_get_indexed(service):
    document = service.upload("invalid.png", b"Not an image")
    with pytest.raises(ValueError, match="image"):
        service.index(document["document_id"])
    assert service.store.list_documents("default")[0]["indexed"] == 0


def test_native_pdf_table_has_preview_and_correct_section(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "table.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "1 Results")
        page.insert_text((40, 80), "Table 2. Model comparison.")
        for x in (40, 160, 280):
            page.draw_line((x, 100), (x, 190))
        for y in (100, 130, 160, 190):
            page.draw_line((40, y), (280, y))
        for row_index, row in enumerate(
            [["Model", "PSNR"], ["A", "27.3"], ["B", "28.1"]]
        ):
            for col_index, cell in enumerate(row):
                page.insert_text((45 + col_index * 120, 120 + row_index * 30), cell)
        page.insert_text((40, 260), "2 Conclusion")
        pdf.save(path)
    assets = AssetBuffer()
    document = DocumentParser().parse(path, "d", path.name, assets)
    table = document.tables[0]
    assert table.section == "1 Results"
    assert table.caption.startswith("Table 2")
    assert table.headers == ["Model", "PSNR"]
    assert table.rows == [["A", "27.3"], ["B", "28.1"]]
    assert table.asset_id in assets.items


def test_figure_limit_is_visible(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    service = PaperMindService(Settings(data_dir=tmp_path, max_figures=1))
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_image((40, 50, 240, 170), stream=png_bytes("red"))
        page.insert_image((40, 250, 240, 370), stream=png_bytes("blue"))
        upload = service.upload("two.pdf", pdf.tobytes())
    result = service.index(upload["document_id"])
    assert result["figure_count"] == 1
    assert any("Figure limit" in warning for warning in result["warnings"])
