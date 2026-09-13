import numpy as np

from papermind.embedding.image_embedding import ImageEmbedding
from papermind.embedding.text_embedding import TextEmbedding
from papermind.models import Chunk, SearchFilter, SearchHit


def normalized(vectors: np.ndarray, rows: int) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != rows or vectors.shape[1] == 0:
        raise ValueError("Embedding shape does not match input")
    if not np.isfinite(vectors).all():
        raise ValueError("Embeddings contain non-finite values")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Embedding model returned a zero vector")
    return np.ascontiguousarray(vectors / norms)


class DenseIndex:
    def __init__(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        embedding: TextEmbedding | ImageEmbedding,
        score_name: str = "dense",
    ):
        import faiss

        self.chunks = tuple(chunks)
        self.embedding = embedding
        self.score_name = score_name
        self.vectors = normalized(vectors, len(chunks))
        self.index = faiss.IndexFlatIP(self.vectors.shape[1])
        self.index.add(self.vectors)

    def search(
        self, query: str, k: int = 20, filters: SearchFilter | None = None
    ) -> list[SearchHit]:
        if k <= 0 or not self.chunks:
            return []
        vector = normalized(self.embedding.encode_query(query), 1)
        if vector.shape[1] != self.vectors.shape[1]:
            raise ValueError("Query embedding dimension changed; rebuild the index")
        if filters is None:
            distances, indices = self.index.search(vector, min(k, len(self.chunks)))
            pairs = zip(indices[0].tolist(), distances[0].tolist())
        else:
            # 先过滤候选，再做精确余弦检索，避免 TopK 后过滤漏召回。
            ids = [i for i, chunk in enumerate(self.chunks) if filters.matches(chunk)]
            if not ids:
                return []
            scores = self.vectors[ids] @ vector[0]
            order = np.argsort(-scores, kind="stable")[:k]
            pairs = ((ids[i], float(scores[i])) for i in order)
        return [
            SearchHit(self.chunks[i], score, {self.score_name: score})
            for i, score in pairs
            if i >= 0
        ]
