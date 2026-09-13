from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Paragraph:
    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class Section:
    title: str
    level: int
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass(slots=True)
class Document:
    document_id: str
    title: str
    sections: list[Section] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tables: list["Table"] = field(default_factory=list)
    figures: list["Figure"] = field(default_factory=list)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    content: str
    page: int
    section: str
    content_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Table:
    table_id: str
    page: int
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""
    section: str = ""
    bbox: tuple[float, float, float, float] | None = None
    asset_id: str = ""
    source_figure_id: str = ""
    extraction_method: str = "native"


@dataclass(slots=True)
class Figure:
    figure_id: str
    page: int
    caption: str = ""
    image_path: str = ""
    visual_description: str = ""
    section: str = ""
    bbox: tuple[float, float, float, float] | None = None
    asset_id: str = ""
    nearby_text: str = ""
    extraction_method: str = "embedded_image"
    analysis_status: str = "not_configured"
    visual_model: str = ""


@dataclass(slots=True)
class SearchHit:
    chunk: Chunk
    score: float
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchFilter:
    document_ids: tuple[str, ...] | None = None
    page: int | None = None
    section: str | None = None
    content_type: str | None = None

    def matches(self, chunk: Chunk) -> bool:
        return (
            (self.document_ids is None or chunk.document_id in self.document_ids)
            and (self.page is None or chunk.page == self.page)
            and (
                self.section is None
                or self.section.casefold() in chunk.section.casefold()
            )
            and (self.content_type is None or chunk.content_type == self.content_type)
        )
