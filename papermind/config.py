import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path = Path("data")
    embedding_model: str = ""
    reranker_model: str = ""
    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_model: str = ""
    llm_api_key: str = ""
    vlm_base_url: str = "http://127.0.0.1:8001/v1"
    vlm_model: str = ""
    vlm_api_key: str = ""
    image_embedding_model: str = ""
    max_figures: int = 64
    max_vlm_figures: int = 16
    max_image_edge: int = 1280
    max_image_pixels: int = 20000000
    max_asset_bytes: int = 32 * 1024 * 1024
    chunk_size: int = 1200
    candidate_k: int = 20
    max_upload_bytes: int = 25 * 1024 * 1024
    max_pages: int = 500
    max_chunks: int = 50000

    def __post_init__(self):
        for name in (
            "chunk_size",
            "candidate_k",
            "max_upload_bytes",
            "max_pages",
            "max_chunks",
            "max_figures",
            "max_vlm_figures",
            "max_image_edge",
            "max_image_pixels",
            "max_asset_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        return cls(
            data_dir=Path(os.getenv("PAPERMIND_DATA_DIR", "data")),
            embedding_model=os.getenv("PAPERMIND_EMBEDDING_MODEL", ""),
            reranker_model=os.getenv("PAPERMIND_RERANKER_MODEL", ""),
            llm_base_url=os.getenv(
                "PAPERMIND_LLM_BASE_URL", "http://127.0.0.1:8001/v1"
            ),
            llm_model=os.getenv("PAPERMIND_LLM_MODEL", ""),
            llm_api_key=os.getenv("PAPERMIND_LLM_API_KEY", ""),
            vlm_base_url=os.getenv(
                "PAPERMIND_VLM_BASE_URL", "http://127.0.0.1:8001/v1"
            ),
            vlm_model=os.getenv("PAPERMIND_VLM_MODEL", ""),
            vlm_api_key=os.getenv("PAPERMIND_VLM_API_KEY", ""),
            image_embedding_model=os.getenv("PAPERMIND_IMAGE_EMBEDDING_MODEL", ""),
            max_figures=int(os.getenv("PAPERMIND_MAX_FIGURES", "64")),
            max_vlm_figures=int(os.getenv("PAPERMIND_MAX_VLM_FIGURES", "16")),
        )
