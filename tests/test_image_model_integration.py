import os

import numpy as np
import pytest
from test_multimodal_parsing import png_bytes

from papermind.config import Settings
from papermind.embedding.image_embedding import ClipEmbedding
from papermind.models import Chunk
from papermind.retrieval.dense import DenseIndex
from papermind.service import PaperMindService


@pytest.mark.skipif(
    os.getenv("PAPERMIND_RUN_IMAGE_MODEL_TESTS") != "1",
    reason="Opt in to download and run the actual CLIP model",
)
def test_real_clip_image_text_similarity(tmp_path):
    embedding = ClipEmbedding("sentence-transformers/clip-ViT-B-32")
    images = [png_bytes("red", (224, 224)), png_bytes("blue", (224, 224))]
    vectors = embedding.encode_images(images)
    assert vectors.shape[0] == 2 and np.isfinite(vectors).all()
    chunks = [
        Chunk("red:0", "red", "red image", 1, "", "figure"),
        Chunk("blue:0", "blue", "blue image", 1, "", "figure"),
    ]
    index = DenseIndex(chunks, vectors, embedding, score_name="image")
    assert index.search("a solid red color", 1)[0].chunk.document_id == "red"
    assert index.search("a solid blue color", 1)[0].chunk.document_id == "blue"
    settings = Settings(data_dir=tmp_path)
    service = PaperMindService(settings, image_embedding=embedding)
    ids = []
    for name, content in zip(("one.png", "two.png"), images):
        uploaded = service.upload(name, content)
        ids.append(uploaded["document_id"])
        assert service.index(ids[-1])["image_indexed"]
    restarted = PaperMindService(settings, image_embedding=embedding)
    for mode in ("image", "multimodal"):
        assert (
            restarted.search("a solid red color", mode=mode)[0].chunk.document_id
            == ids[0]
        )
        assert (
            restarted.search("a solid blue color", mode=mode)[0].chunk.document_id
            == ids[1]
        )
