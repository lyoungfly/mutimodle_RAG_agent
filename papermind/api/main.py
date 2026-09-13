import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from papermind.config import Settings
from papermind.errors import ModelResponseError
from papermind.models import SearchFilter
from papermind.multimodal.sources import enrich_source
from papermind.service import PaperMindService, validate_collection

from .middleware import RequestSizeLimit
from .settings_routes import settings_router

logger = logging.getLogger(__name__)
Collection = Annotated[str, Query(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class IndexRequest(BaseModel):
    document_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    collection_id: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class FilterRequest(BaseModel):
    document_ids: list[str] | None = Field(default=None, max_length=100)
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=200)
    content_type: Literal["text", "table", "figure"] | None = None

    def to_filter(self) -> SearchFilter:
        return SearchFilter(
            None if self.document_ids is None else tuple(self.document_ids),
            self.page,
            self.section,
            self.content_type,
        )


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    collection_id: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal[
        "auto",
        "bm25",
        "dense",
        "hybrid",
        "hybrid_rerank",
        "image",
        "multimodal",
        "multimodal_rerank",
    ] = "auto"
    filters: FilterRequest | None = None

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


def create_app(
    settings: Settings | None = None, service: PaperMindService | None = None
) -> FastAPI:
    service = service or PaperMindService(settings or Settings.from_env())
    app = FastAPI(title="PaperMind", version="0.1.0")
    app.state.service = service
    app.include_router(settings_router(service))
    app.add_middleware(
        RequestSizeLimit, max_bytes=service.settings.max_upload_bytes + 1024 * 1024
    )

    @app.exception_handler(ModelResponseError)
    async def model_output_error(request: Request, exc: ModelResponseError):
        logger.warning("Invalid model response: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError):
        return JSONResponse(
            status_code=404, content={"detail": "Document or source not found"}
        )

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def unavailable(request: Request, exc: RuntimeError):
        logger.exception(
            "Service dependency unavailable: %s", request.url.path, exc_info=exc
        )
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def failed(request: Request, exc: Exception):
        logger.exception("Request failed: %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500, content={"detail": "Request failed; see server logs"}
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "embedding_configured": bool(
                service.embedding or service.settings.embedding_model
            ),
            "reranker_configured": bool(
                service.reranker or service.settings.reranker_model
            ),
            "llm_configured": bool(service.llm or service.settings.llm_model),
            "vlm_configured": bool(service.vlm or service.settings.vlm_model),
            "image_embedding_configured": bool(
                service.image_embedding or service.settings.image_embedding_model
            ),
            "supported_formats": sorted(service.parser.supported),
        }

    @app.post("/documents/upload", status_code=201)
    def upload(
        file: Annotated[UploadFile, File()],
        collection_id: Annotated[str, Form()] = "default",
    ):
        try:
            validate_collection(collection_id)
            content = file.file.read(service.settings.max_upload_bytes + 1)
            if len(content) > service.settings.max_upload_bytes:
                raise HTTPException(413, "Upload exceeds size limit")
            return service.upload(file.filename or "upload.txt", content, collection_id)
        finally:
            file.file.close()

    @app.post("/documents/index")
    def index(body: IndexRequest):
        return service.index(body.document_id, body.collection_id)

    @app.get("/collections")
    def collections():
        return service.store.list_collections()

    @app.get("/documents")
    def documents(collection_id: Collection = "default"):
        return service.store.list_documents(collection_id)

    @app.get("/documents/{document_id}")
    def document(document_id: str, collection_id: Collection = "default"):
        return service.store.get(document_id, collection_id)["body"]

    @app.get("/documents/{document_id}/file")
    def raw_file(document_id: str, collection_id: Collection = "default"):
        record = service.store.get(document_id, collection_id)
        media = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(record["suffix"], "text/plain; charset=utf-8")
        return FileResponse(
            service.store.raw_path(record),
            media_type=media,
            filename=record["filename"],
            content_disposition_type="inline",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/sources/{chunk_id}")
    def source(chunk_id: str, collection_id: Collection = "default"):
        return enrich_source(
            service.store, service.store.source(chunk_id, collection_id), collection_id
        )

    @app.get("/documents/{document_id}/assets/{asset_id}")
    def visual_asset(
        document_id: str, asset_id: str, collection_id: Collection = "default"
    ):
        return Response(
            service.store.asset(document_id, asset_id, collection_id),
            media_type="image/png",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=3600",
            },
        )

    @app.get("/documents/{document_id}/visuals")
    def visuals(document_id: str, collection_id: Collection = "default"):
        document = service.store.get(document_id, collection_id)["body"]
        return {
            "document_id": document_id,
            "title": document["title"],
            "figures": document.get("figures", []),
            "tables": [
                {
                    **table,
                    "rows": table["rows"][:20],
                    "row_offset": 0,
                    "total_rows": len(table["rows"]),
                }
                for table in document.get("tables", [])
            ],
            "warnings": document.get("metadata", {}).get("warnings", []),
        }

    @app.get("/documents/{document_id}/tables/{table_id}")
    def table(
        document_id: str,
        table_id: str,
        collection_id: Collection = "default",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        document = service.store.get(document_id, collection_id)["body"]
        table = next(
            (t for t in document.get("tables", []) if t["table_id"] == table_id), None
        )
        if table is None:
            raise KeyError(table_id)
        return {
            **table,
            "rows": table["rows"][offset : offset + limit],
            "row_offset": offset,
            "total_rows": len(table["rows"]),
        }

    @app.post("/search")
    def search(body: ChatRequest):
        filters = body.filters.to_filter() if body.filters else None
        return [
            asdict(hit)
            for hit in service.search(
                body.question, body.collection_id, body.top_k, filters, body.mode
            )
        ]

    @app.post("/chat")
    def chat(body: ChatRequest):
        filters = body.filters.to_filter() if body.filters else None
        return service.chat(
            body.question, body.collection_id, body.top_k, filters, body.mode
        )

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def demo():
        return FileResponse(static / "index.html")

    return app
