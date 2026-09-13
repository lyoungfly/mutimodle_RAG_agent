import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_multimodal_parsing import make_figure_pdf, png_bytes

from papermind.api.main import create_app
from papermind.config import Settings
from papermind.models import SearchFilter
from papermind.multimodal.vlm import VisionResult
from papermind.service import PaperMindService


class ColorEmbedding:
    """测试向量仅编码颜色，不冒充真实跨模态模型。"""

    fingerprint = "test-only:colors"

    def encode_images(self, images):
        result = []
        for data in images:
            with Image.open(io.BytesIO(data)) as image:
                pixel = image.convert("RGB").getpixel((0, 0))
                result.append([pixel[0] + 1, pixel[2] + 1])
        return np.asarray(result, dtype=np.float32)

    def encode_query(self, text):
        return np.asarray([[1, 0] if "red" in text else [0, 1]], dtype=np.float32)


def test_image_retrieval_persistence_filter_and_collection_isolation(tmp_path):
    pytest.importorskip("faiss")
    service = PaperMindService(
        Settings(data_dir=tmp_path), image_embedding=ColorEmbedding()
    )
    red = service.upload("red.png", png_bytes("red"))
    blue = service.upload("blue.png", png_bytes("blue"))
    service.index(red["document_id"])
    service.index(blue["document_id"])
    assert (
        service.search("red", mode="image")[0].chunk.document_id == red["document_id"]
    )
    assert (
        service.search(
            "red",
            mode="image",
            filters=SearchFilter(document_ids=(blue["document_id"],)),
        )[0].chunk.document_id
        == blue["document_id"]
    )
    assert (
        service.search("red", mode="image", filters=SearchFilter(content_type="table"))
        == []
    )
    assert service.search("red", collection="other") == []
    restarted = PaperMindService(service.settings, image_embedding=ColorEmbedding())
    response = restarted.chat("blue", mode="multimodal")
    assert response["sources"][0]["figure"]["asset_id"]
    assert response["sources"][0]["image_url"].endswith("collection_id=default")
    assert (
        restarted.search("blue", mode="image")[0].chunk.document_id
        == blue["document_id"]
    )


def test_image_bytes_and_index_roll_back_together(tmp_path):
    service = PaperMindService(
        Settings(data_dir=tmp_path), image_embedding=ColorEmbedding()
    )
    upload = service.upload("red.png", png_bytes())
    service.index(upload["document_id"])
    before = service.store.get(upload["document_id"], "default")
    asset = before["body"]["figures"][0]["asset_id"]
    previous_bytes = service.store.asset(upload["document_id"], asset, "default")
    original = service.store.replace_index

    def fail_inside_transaction(*args, **kwargs):
        args = list(args)
        args[6] = {"nonexistent-chunk": np.asarray([1, 0])}
        return original(*args, **kwargs)

    service.store.replace_index = fail_inside_transaction
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        service.index(upload["document_id"])
    assert (
        service.store.asset(upload["document_id"], asset, "default") == previous_bytes
    )
    assert service.store.get(upload["document_id"], "default") == before


def test_pdf_media_endpoints_and_reindex_do_not_leak_assets(service):
    upload = service.upload("figure.pdf", make_figure_pdf())
    result = service.index(upload["document_id"])
    assert result["figure_count"] == 1
    service.index(upload["document_id"])
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM visual_assets").fetchone()[0] == 1
    with TestClient(create_app(service=service)) as client:
        gallery = client.get(f"/documents/{upload['document_id']}/visuals").json()
        figure = gallery["figures"][0]
        url = f"/documents/{upload['document_id']}/assets/{figure['asset_id']}"
        image = client.get(url)
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")
        assert client.get(url + "?collection_id=other").status_code == 404
        assert (
            client.get(f"/documents/{upload['document_id']}/assets/missing").status_code
            == 404
        )
        answer = client.post(
            "/chat",
            json={"question": "Figure 3", "filters": {"content_type": "figure"}},
        ).json()
        assert answer["sources"][0]["figure"]["caption"].startswith("Figure 3")
        assert "image_url" in answer["sources"][0]
        assert client.get("/static/visuals.js").status_code == 200


def test_vlm_table_available_as_structured_source(service):
    class TableVision:
        name = "test-table-vision"

        def analyze(self, *args):
            return VisionResult(
                "A model comparison table",
                [{"headers": ["Model", "PSNR"], "rows": [["A", "27.3"]]}],
            )

    service.vlm = TableVision()
    upload = service.upload("table.png", png_bytes())
    result = service.index(upload["document_id"])
    assert result["visual_analyzed"] == 1 and result["table_count"] == 1
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/chat", json={"question": "PSNR", "filters": {"content_type": "table"}}
        ).json()
        source = response["sources"][0]
        assert source["table"]["extraction_method"] == "vlm"
        table = client.get(
            f"/documents/{upload['document_id']}/tables/fig_1_table_1?limit=1"
        ).json()
        assert table["rows"] == [["A", "27.3"]]
        assert (
            client.get(
                f"/documents/{upload['document_id']}/tables/fig_1_table_1?collection_id=other"
            ).status_code
            == 404
        )
