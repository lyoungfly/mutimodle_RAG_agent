from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import TinyEmbedding, ingest

from papermind.config import Settings
from papermind.models import SearchFilter
from papermind.service import PaperMindService


def test_restart_reindex_and_collection_isolation(service):
    doc_id = ingest(service, "Urban100 PSNR is 27.38")
    first = service.chat("Urban100")
    assert first["mode"] == "evidence_only"
    assert first["sources"][0]["page"] == 1
    assert first["sources"][0]["url"].endswith("#page=1")
    service.index(doc_id)
    assert service.store.list_documents("default")[0]["chunk_count"] == 1
    restarted = PaperMindService(service.settings)
    assert restarted.search("Urban100")[0].chunk.document_id == doc_id
    assert restarted.search("Urban100", collection="other") == []
    with pytest.raises(KeyError):
        restarted.store.source(first["sources"][0]["chunk_id"], "other")


def test_failure_keeps_previous_index(service):
    doc_id = ingest(service, "Urban100 PSNR is 27.38")

    class FailingParser:
        def parse(self, *args):
            raise ValueError("Malformed document")

    service.parser = FailingParser()
    with pytest.raises(ValueError):
        service.index(doc_id)
    assert service.search("Urban100")[0].chunk.document_id == doc_id


def test_concurrent_ingestion_and_query(service):
    def worker(index):
        doc_id = ingest(
            service, f"Mamba architecture variant{index}", f"paper{index}.txt"
        )
        assert service.search(
            f"variant{index}", filters=SearchFilter(document_ids=(doc_id,))
        )
        return doc_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(worker, range(8)))
    assert len(set(ids)) == len(service.store.list_documents("default")) == 8


def test_persisted_dense_vectors_and_model_change(tmp_path):
    pytest.importorskip("faiss")
    settings = Settings(data_dir=tmp_path)
    service = PaperMindService(settings, embedding=TinyEmbedding())
    doc_id = ingest(service, "Mamba architecture")
    restarted = PaperMindService(settings, embedding=TinyEmbedding())
    assert restarted.search("Mamba", mode="dense")[0].chunk.document_id == doc_id
    restarted.embedding.fingerprint = "test-only:changed-model"
    restarted._cache.clear()
    with pytest.raises(RuntimeError, match="reindex"):
        restarted.search("Mamba")


def test_empty_question_and_unsupported_file(service):
    with pytest.raises(ValueError):
        service.upload("attack.html", b"<script>alert(1)</script>")
    with pytest.raises(ValueError):
        service.search(" ")
    assert service.chat("missing")["abstained"] is True
    with pytest.raises(ValueError):
        service.upload("paper.txt", b"test", "../unsafe")


def test_chunk_limit_is_transactional(tmp_path):
    service = PaperMindService(Settings(data_dir=tmp_path, max_chunks=1))
    first = ingest(service, "First evidence")
    uploaded = service.upload("second.txt", b"Second evidence")
    with pytest.raises(ValueError, match="chunk limit"):
        service.index(uploaded["document_id"])
    assert service.search("First")[0].chunk.document_id == first
    assert not service.store.get(uploaded["document_id"], "default")["indexed"]
