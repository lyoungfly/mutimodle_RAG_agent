import hashlib
import re
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from urllib.parse import quote

import numpy as np

from papermind.answering import generate_answer
from papermind.chunking.structure_chunker import StructureChunker
from papermind.config import Settings
from papermind.embedding.image_embedding import ClipEmbedding, ImageEmbedding
from papermind.embedding.text_embedding import (
    SentenceTransformerEmbedding,
    TextEmbedding,
)
from papermind.llm.client import CompatibleLLM, LanguageModel
from papermind.model_api import APIConfigStore, apply_endpoints
from papermind.models import Document, SearchFilter
from papermind.multimodal.sources import enrich_source
from papermind.multimodal.vlm import CompatibleVLM, VisionModel, enrich_figures
from papermind.parser import DocumentParser
from papermind.parser.assets import AssetBuffer
from papermind.reranker.reranker import CrossEncoderReranker, Reranker
from papermind.retrieval.bm25 import BM25Index
from papermind.retrieval.dense import DenseIndex, normalized
from papermind.retrieval.hybrid import HybridRetriever
from papermind.storage import DocumentStore


def validate_collection(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise ValueError(
            "collection_id must contain 1–64 letters, digits, underscores or hyphens"
        )
    return value


class PaperMindService:
    def __init__(
        self,
        settings: Settings,
        embedding: TextEmbedding | None = None,
        reranker: Reranker | None = None,
        llm: LanguageModel | None = None,
        vlm: VisionModel | None = None,
        image_embedding: ImageEmbedding | None = None,
    ):
        self.api_config_store = APIConfigStore(settings.data_dir)
        self.api_endpoints = self.api_config_store.load(settings)
        self.settings = apply_endpoints(settings, self.api_endpoints)
        self.store = DocumentStore(settings.data_dir, settings.max_chunks)
        self.parser = DocumentParser(
            settings.max_pages,
            settings.max_figures,
            settings.max_image_edge,
            settings.max_image_pixels,
        )
        self.chunker = StructureChunker(settings.chunk_size)
        self.embedding = embedding
        self.reranker = reranker
        self.llm = llm
        self.vlm = vlm
        self.image_embedding = image_embedding
        self._lock = RLock()
        self._cache: OrderedDict[str, tuple[int, HybridRetriever]] = OrderedDict()

    def api_settings(self) -> dict:
        with self._lock:
            return {
                **{kind: item.public() for kind, item in self.api_endpoints.items()},
                "local_models": {
                    "embedding": self.settings.embedding_model,
                    "reranker": self.settings.reranker_model,
                    "image_embedding": self.settings.image_embedding_model,
                },
            }

    def resolve_api(self, kind: str, patch: dict):
        with self._lock:
            return self.api_endpoints[kind].updated(patch)

    def configure_apis(self, changes: dict):
        with self._lock:
            endpoints = {
                kind: item.updated(changes[kind])
                for kind, item in self.api_endpoints.items()
            }
            settings = apply_endpoints(self.settings, endpoints)
            self.api_config_store.save(endpoints)
            self.api_endpoints, self.settings = endpoints, settings
            self.llm = None
            self.vlm = None

    def _load_models(self):
        if self.settings.embedding_model and self.embedding is None:
            self.embedding = SentenceTransformerEmbedding(self.settings.embedding_model)
        if self.settings.reranker_model and self.reranker is None:
            self.reranker = CrossEncoderReranker(self.settings.reranker_model)
        if self.settings.llm_model and self.llm is None:
            self.llm = CompatibleLLM(
                self.settings.llm_base_url,
                self.settings.llm_model,
                self.settings.llm_api_key,
            )
        if self.settings.image_embedding_model and self.image_embedding is None:
            self.image_embedding = ClipEmbedding(self.settings.image_embedding_model)
        if self.settings.vlm_model and self.vlm is None:
            self.vlm = CompatibleVLM(
                self.settings.vlm_base_url,
                self.settings.vlm_model,
                self.settings.vlm_api_key,
            )

    def upload(
        self, filename: str, content: bytes, collection: str = "default"
    ) -> dict:
        validate_collection(collection)
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in self.parser.supported:
            raise ValueError(
                "Supported formats: PDF, DOCX, XLSX, TXT, MD, CSV, PNG, JPEG, WebP"
            )
        if not content or len(content) > self.settings.max_upload_bytes:
            raise ValueError("File is empty or exceeds the upload size limit")
        identity = hashlib.sha256(
            collection.encode() + b"\0" + suffix.encode() + b"\0" + content
        ).hexdigest()
        document = Document(
            identity, Path(filename).stem, metadata={"filename": filename}
        )
        destination = self.store.root / "uploads" / (identity + suffix)
        with self._lock:
            if not destination.exists():
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=destination.parent, delete=False
                    ) as temp:
                        temp_path = Path(temp.name)
                        temp.write(content)
                    temp_path.replace(destination)
                finally:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
            self.store.register(document, collection, filename, suffix)
        return {
            "document_id": identity,
            "filename": filename,
            "collection_id": collection,
        }

    def index(self, document_id: str, collection: str = "default", before_commit=None) -> dict:
        validate_collection(collection)
        # 解析和编码成功后一次性提交，失败时保留旧索引。
        with self._lock:
            record = self.store.get(document_id, collection)
            assets = AssetBuffer(self.settings.max_asset_bytes)
            document = self.parser.parse(
                self.store.raw_path(record), document_id, record["filename"], assets
            )
            self._load_models()
            enrich_figures(
                document, assets.items, self.vlm, self.settings.max_vlm_figures
            )
            chunks = self.chunker.chunk(document)
            if not chunks:
                raise ValueError(
                    "No extractable content found; scanned PDF requires OCR"
                )
            if len(chunks) > self.settings.max_chunks:
                raise ValueError("Document produces too many chunks")
            vectors = None
            if self.embedding:
                texts = [f"{c.section}\n{c.content}" for c in chunks]
                vectors = normalized(
                    self.embedding.encode_documents(texts), len(chunks)
                )
            image_vectors = {}
            if self.image_embedding and document.figures:
                image_rows = normalized(
                    self.image_embedding.encode_images(
                        [assets.items[f.asset_id] for f in document.figures]
                    ),
                    len(document.figures),
                )
                anchors = {}
                for chunk in chunks:
                    if chunk.content_type == "figure":
                        anchors.setdefault(chunk.metadata["figure_id"], chunk.chunk_id)
                image_vectors = {
                    anchors[f.figure_id]: image_rows[i]
                    for i, f in enumerate(document.figures)
                }
            if before_commit:
                before_commit()
            self.store.replace_index(
                document,
                collection,
                chunks,
                vectors,
                self.embedding.fingerprint if self.embedding else "",
                assets.items,
                image_vectors,
                self.image_embedding.fingerprint if self.image_embedding else "",
            )
            self._cache.pop(collection, None)
        return {
            "document_id": document_id,
            "chunk_count": len(chunks),
            "warnings": document.metadata.get("warnings", []),
            "dense_indexed": vectors is not None,
            "figure_count": len(document.figures),
            "table_count": len(document.tables),
            "image_indexed": bool(image_vectors),
            "visual_analyzed": sum(
                f.analysis_status == "complete" for f in document.figures
            ),
        }

    def retriever(self, collection: str) -> HybridRetriever:
        validate_collection(collection)
        with self._lock:
            self._load_models()
            revision = self.store.revision(collection)
            cached = self._cache.get(collection)
            if cached and cached[0] == revision:
                self._cache.move_to_end(collection)
                return cached[1]
            revision, chunks, vectors, fingerprints, image_rows = (
                self.store.snapshot_with_images(collection)
            )
            dense = None
            if self.embedding and chunks:
                if fingerprints != {self.embedding.fingerprint} or any(
                    v is None for v in vectors
                ):
                    raise RuntimeError(
                        "Embedding configuration changed; reindex every document in this collection"
                    )
                dense = DenseIndex(
                    chunks,
                    np.stack([np.frombuffer(v, dtype="<f4") for v in vectors]),
                    self.embedding,
                )
            image_index = None
            if self.image_embedding and any(c.content_type == "figure" for c in chunks):
                expected = {
                    c.metadata["figure_id"] + ":" + c.document_id
                    for c in chunks
                    if c.content_type == "figure"
                }
                if len(image_rows) != len(expected) or any(
                    row["fingerprint"] != self.image_embedding.fingerprint
                    for row in image_rows
                ):
                    raise RuntimeError(
                        "Image embedding configuration changed; reindex documents with figures"
                    )
                by_id = {c.chunk_id: c for c in chunks}
                image_index = DenseIndex(
                    [by_id[row["chunk_id"]] for row in image_rows],
                    np.stack(
                        [
                            np.frombuffer(row["vector"], dtype="<f4")
                            for row in image_rows
                        ]
                    ),
                    self.image_embedding,
                    score_name="image",
                )
            retriever = HybridRetriever(
                BM25Index(chunks),
                dense,
                self.reranker,
                self.settings.candidate_k,
                image_index,
            )
            self._cache[collection] = (revision, retriever)
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            return retriever

    def search(
        self,
        question: str,
        collection: str = "default",
        k: int = 5,
        filters: SearchFilter | None = None,
        mode: str = "auto",
    ):
        if not question.strip() or len(question) > 8000 or not 1 <= k <= 100:
            raise ValueError(
                "Question must contain 1–8000 characters; k must be between 1 and 100"
            )
        return self.retriever(collection).search(question, k, filters, mode)

    def chat(
        self,
        question: str,
        collection: str = "default",
        k: int = 5,
        filters: SearchFilter | None = None,
        mode: str = "auto",
        workspace_mode: str = "research",
    ) -> dict:
        if workspace_mode not in {"research", "enterprise"}:
            raise ValueError("Unsupported workspace mode")
        start = time.perf_counter()
        hits = self.search(question, collection, k, filters, mode)
        sources = []
        for i, hit in enumerate(hits, 1):
            source = self.store.source(hit.chunk.chunk_id, collection)
            source = enrich_source(self.store, source, collection)
            source.update(
                id=i,
                score=hit.score,
                scores=hit.scores,
                url=f"/documents/{hit.chunk.document_id}/file?collection_id={quote(collection)}"
                + (f"#page={hit.chunk.page}" if hit.chunk.page > 0 else ""),
            )
            sources.append(source)
        llm = self.llm
        if workspace_mode == "enterprise" and isinstance(llm, CompatibleLLM):
            llm = llm.for_enterprise()
        response = generate_answer(question, hits, sources, llm)
        response["workspace_mode"] = workspace_mode
        response["latency"] = round(time.perf_counter() - start, 4)
        retriever = self.retriever(collection)
        response["retrieval_mode"] = retriever.resolve_mode(mode)
        return response
