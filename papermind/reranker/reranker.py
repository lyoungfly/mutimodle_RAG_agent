from threading import Lock
from typing import Protocol

import numpy as np

from papermind.models import SearchHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[SearchHit], k: int) -> list[SearchHit]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name, trust_remote_code=False)
        self._lock = Lock()

    def rerank(self, query: str, hits: list[SearchHit], k: int) -> list[SearchHit]:
        if not hits:
            return []
        with self._lock:
            scores = np.asarray(
                self.model.predict(
                    [(query, f"{h.chunk.section}\n{h.chunk.content}") for h in hits],
                    batch_size=16,
                    show_progress_bar=False,
                )
            ).reshape(-1)
        if len(scores) != len(hits) or not np.isfinite(scores).all():
            raise ValueError("Reranker must return one finite score per candidate")
        ranked = [
            SearchHit(h.chunk, float(s), {**h.scores, "reranker": float(s)})
            for h, s in zip(hits, scores)
        ]
        return sorted(ranked, key=lambda h: (-h.score, h.chunk.chunk_id))[:k]
