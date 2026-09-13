import io
from threading import Lock
from typing import Protocol

import numpy as np


class ImageEmbedding(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def encode_images(self, images: list[bytes]) -> np.ndarray: ...

    def encode_query(self, text: str) -> np.ndarray: ...


class ClipEmbedding:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, trust_remote_code=False)
        self.fingerprint = f"clip:{model_name}"
        self._lock = Lock()

    def encode_images(self, images: list[bytes]) -> np.ndarray:
        from PIL import Image

        batches = []
        with self._lock:
            for start in range(0, len(images), 8):
                loaded = []
                try:
                    for data in images[start : start + 8]:
                        with Image.open(io.BytesIO(data)) as image:
                            loaded.append(image.convert("RGB"))
                    batches.append(
                        self.model.encode(
                            loaded,
                            batch_size=8,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                        )
                    )
                finally:
                    for image in loaded:
                        image.close()
        return (
            np.concatenate(batches) if batches else np.empty((0, 0), dtype=np.float32)
        )

    def encode_query(self, text: str) -> np.ndarray:
        with self._lock:
            return self.model.encode(
                [text], normalize_embeddings=True, show_progress_bar=False
            )
