from threading import Lock
from typing import Protocol

import numpy as np


class TextEmbedding(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    def encode_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedding:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, trust_remote_code=False)
        self._lock = Lock()

    @property
    def fingerprint(self) -> str:
        return f"sentence-transformers:{self.model_name}"

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            return self.model.encode_document(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

    def encode_query(self, text: str) -> np.ndarray:
        with self._lock:
            return self.model.encode_query(
                [text], normalize_embeddings=True, show_progress_bar=False
            )
