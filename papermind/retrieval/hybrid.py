from papermind.models import SearchFilter, SearchHit
from papermind.reranker.reranker import Reranker

from .bm25 import BM25Index
from .dense import DenseIndex
from .rrf import reciprocal_rank_fusion


class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Index,
        dense: DenseIndex | None = None,
        reranker: Reranker | None = None,
        candidate_k: int = 20,
        image: DenseIndex | None = None,
    ):
        self.bm25, self.dense, self.reranker = bm25, dense, reranker
        self.candidate_k = candidate_k
        self.image = image

    def resolve_mode(self, mode: str) -> str:
        if mode != "auto":
            return mode
        if self.image:
            return "multimodal_rerank" if self.reranker else "multimodal"
        if self.dense:
            return "hybrid_rerank" if self.reranker else "hybrid"
        return "bm25"

    def search(
        self,
        query: str,
        k: int = 5,
        filters: SearchFilter | None = None,
        mode: str = "auto",
    ) -> list[SearchHit]:
        mode = self.resolve_mode(mode)
        if mode not in {
            "bm25",
            "dense",
            "hybrid",
            "hybrid_rerank",
            "image",
            "multimodal",
            "multimodal_rerank",
        }:
            raise ValueError(f"Unknown retrieval mode: {mode}")
        if mode in {"dense", "hybrid", "hybrid_rerank"} and self.dense is None:
            raise RuntimeError(
                "Dense retrieval requires PAPERMIND_EMBEDDING_MODEL and indexed vectors"
            )
        if mode in {"hybrid_rerank", "multimodal_rerank"} and self.reranker is None:
            raise RuntimeError("Reranking requires PAPERMIND_RERANKER_MODEL")
        if mode in {"image", "multimodal", "multimodal_rerank"} and self.image is None:
            raise RuntimeError(
                "Image retrieval requires PAPERMIND_IMAGE_EMBEDDING_MODEL and indexed images"
            )
        count = max(k, self.candidate_k)
        if mode == "bm25":
            return self.bm25.search(query, k, filters)
        if mode == "dense":
            return self.dense.search(query, k, filters)
        if mode == "image":
            return self.image.search(query, k, filters)
        rankings = [self.bm25.search(query, count, filters)]
        if self.dense:
            rankings.append(self.dense.search(query, count, filters))
        if mode in {"multimodal", "multimodal_rerank"}:
            rankings.append(self.image.search(query, count, filters))
        hits = reciprocal_rank_fusion(rankings)[:count]
        if mode in {"hybrid_rerank", "multimodal_rerank"}:
            return self.reranker.rerank(query, hits, k)
        return hits[:k]
