import numpy as np
import pytest
from conftest import TinyEmbedding

from papermind.models import Chunk, SearchFilter, SearchHit
from papermind.retrieval.bm25 import BM25Index
from papermind.retrieval.dense import DenseIndex, normalized
from papermind.retrieval.hybrid import HybridRetriever
from papermind.retrieval.rrf import reciprocal_rank_fusion


def chunk(identifier, content, page=1):
    return Chunk(identifier, identifier.split(":")[0], content, page, "Method")


def test_bm25_keyword_and_chinese_retrieval():
    index = BM25Index(
        [chunk("a:0", "Urban100 PSNR 27.45"), chunk("b:0", "状态空间模型降低参数量")]
    )
    assert index.search("Urban100")[0].chunk.chunk_id == "a:0"
    assert index.search("参数量")[0].chunk.chunk_id == "b:0"
    assert index.search("unrelatedword") == []
    assert index.search("PSNR", filters=SearchFilter(document_ids=())) == []


def test_rrf_uses_rank_and_deduplicates_each_channel():
    a, b = chunk("a:0", "a"), chunk("b:0", "b")
    result = reciprocal_rank_fusion(
        [
            [SearchHit(a, 100), SearchHit(a, 99), SearchHit(b, 1)],
            [SearchHit(b, 0.99)],
        ]
    )
    assert result[0].chunk.chunk_id == "b:0"
    assert next(h for h in result if h.chunk.chunk_id == "a:0").score == pytest.approx(
        1 / 61
    )


def test_faiss_dense_filter_before_topk():
    pytest.importorskip("faiss")
    embed = TinyEmbedding()
    chunks = [chunk("a:0", "mamba", 1), chunk("b:0", "cnn", 2)]
    dense = DenseIndex(
        chunks, embed.encode_documents([c.content for c in chunks]), embed
    )
    assert dense.search("mamba", 1)[0].chunk.document_id == "a"
    assert dense.search("mamba", 1, SearchFilter(page=2))[0].chunk.document_id == "b"
    assert dense.search("mamba", 1, SearchFilter(document_ids=())) == []


@pytest.mark.parametrize(
    "vectors", [np.zeros((1, 3)), [[float("nan"), 1]], [[float("inf"), 1]], [1, 2]]
)
def test_invalid_vectors_are_rejected(vectors):
    with pytest.raises(ValueError):
        normalized(vectors, 1)


def test_hybrid_and_reranker_are_real_distinct_stages():
    pytest.importorskip("faiss")
    embed = TinyEmbedding()
    chunks = [chunk("a:0", "mamba"), chunk("b:0", "cnn")]
    dense = DenseIndex(
        chunks, embed.encode_documents([c.content for c in chunks]), embed
    )

    class ReverseReranker:
        def rerank(self, query, hits, k):
            assert len(hits) == 2
            return list(reversed(hits))[:k]

    retriever = HybridRetriever(BM25Index(chunks), dense, ReverseReranker())
    assert retriever.search("mamba", 1, mode="hybrid")[0].chunk.document_id == "a"
    assert (
        retriever.search("mamba", 1, mode="hybrid_rerank")[0].chunk.document_id == "b"
    )
    with pytest.raises(RuntimeError):
        HybridRetriever(BM25Index(chunks)).search("mamba", mode="dense")
