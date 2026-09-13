import numpy as np
import pytest

from papermind.config import Settings
from papermind.service import PaperMindService


@pytest.fixture
def service(tmp_path):
    return PaperMindService(Settings(data_dir=tmp_path))


class TinyEmbedding:
    """只用于验证索引数据流的固定向量，不作为真实语义模型。"""

    fingerprint = "test-only:tiny-v1"

    def encode_documents(self, texts):
        return np.asarray(
            [
                [float("mamba" in text.lower()), float("cnn" in text.lower()), 0.1]
                for text in texts
            ],
            dtype=np.float32,
        )

    def encode_query(self, text):
        return self.encode_documents([text])


def ingest(service, text, filename="paper.txt", collection="default"):
    uploaded = service.upload(filename, text.encode("utf-8"), collection)
    service.index(uploaded["document_id"], collection)
    return uploaded["document_id"]
