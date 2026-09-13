import os

import pytest
from conftest import ingest

from papermind.config import Settings
from papermind.service import PaperMindService


@pytest.mark.skipif(
    os.getenv("PAPERMIND_RUN_MODEL_TESTS") != "1",
    reason="Set PAPERMIND_RUN_MODEL_TESTS=1 to download and test actual model weights",
)
def test_real_embedding_reranking_and_restart(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        reranker_model="cross-encoder/ms-marco-TinyBERT-L2-v2",
    )
    service = PaperMindService(settings)
    relevant = ingest(
        service,
        "A neural network restores high resolution images from low resolution inputs.",
        "vision.txt",
    )
    ingest(
        service,
        "The kitchen serves soup and freshly baked bread every morning.",
        "food.txt",
    )
    for mode in ("dense", "hybrid", "hybrid_rerank"):
        hits = service.search("How are low resolution images restored?", mode=mode)
        assert hits[0].chunk.document_id == relevant
    assert "reranker" in hits[0].scores
    restarted = PaperMindService(
        settings, embedding=service.embedding, reranker=service.reranker
    )
    assert (
        restarted.search("image restoration", mode="dense")[0].chunk.document_id
        == relevant
    )
