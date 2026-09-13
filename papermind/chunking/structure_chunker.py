import re

from papermind.models import Chunk, Document


def split_text(text: str, limit: int) -> list[str]:
    """优先在句末或空白切分；无边界的超长片段才按字符兜底。"""
    pieces = []
    while len(text) > limit:
        candidates = list(re.finditer(r"[。！？.!?]\s*|\s+", text[: limit + 1]))
        end = candidates[-1].end() if candidates else limit
        end = min(end, limit)
        pieces.append(text[:end].strip())
        text = text[end:].strip()
    if text:
        pieces.append(text)
    return [piece for piece in pieces if piece]


class StructureChunker:
    def __init__(self, max_chars: int = 1200):
        if max_chars < 16:
            raise ValueError("max_chars must be at least 16")
        self.max_chars = max_chars

    def chunk(self, document: Document) -> list[Chunk]:
        chunks = []
        parents: list[tuple[int, str]] = []

        def add(content, page, section, kind="text", **metadata):
            chunks.append(
                Chunk(
                    f"{document.document_id}:{len(chunks)}",
                    document.document_id,
                    content,
                    page,
                    section,
                    kind,
                    metadata,
                )
            )

        for section in document.sections:
            while parents and parents[-1][0] >= section.level:
                parents.pop()
            parent = " / ".join(title for _, title in parents)
            parents.append((section.level, section.title))
            buffer, page, boxes = "", 1, []
            for paragraph in section.paragraphs:
                for part in split_text(paragraph.text, self.max_chars):
                    if buffer and (
                        page != paragraph.page
                        or len(buffer) + len(part) + 2 > self.max_chars
                    ):
                        add(
                            buffer,
                            page,
                            section.title,
                            parent_section=parent,
                            bboxes=boxes,
                        )
                        buffer, boxes = "", []
                    page = paragraph.page
                    buffer = f"{buffer}\n\n{part}" if buffer else part
                    if paragraph.bbox:
                        boxes.append(paragraph.bbox)
            if buffer:
                add(buffer, page, section.title, parent_section=parent, bboxes=boxes)
        for table in document.tables:
            # 按行切分并重复表头，保留行号以定位完整结构化数据。
            header = " | ".join(table.headers)
            for row_index, row in enumerate(table.rows):
                content = f"{table.caption}\n{header}\n" + " | ".join(row)
                for part in split_text(content, self.max_chars):
                    add(
                        part,
                        table.page,
                        table.section,
                        "table",
                        table_id=table.table_id,
                        row_index=row_index,
                        **(
                            {
                                "extraction_method": "vlm",
                                "source_figure_id": table.source_figure_id,
                            }
                            if table.extraction_method == "vlm"
                            else {}
                        ),
                    )
        for figure in document.figures:
            for part in split_text(
                (
                    f"Figure {figure.figure_id}\n{figure.caption}\n"
                    f"Nearby text: {figure.nearby_text}\n"
                    + (
                        f"VLM description (model-generated): {figure.visual_description}"
                        if figure.visual_description
                        else "Visual content has not been analyzed."
                    )
                ).strip(),
                self.max_chars,
            ):
                add(
                    part,
                    figure.page,
                    figure.section,
                    "figure",
                    figure_id=figure.figure_id,
                    analysis_status=figure.analysis_status,
                    visual_model=figure.visual_model,
                )
        return chunks
