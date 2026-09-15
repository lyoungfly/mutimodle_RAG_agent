import csv
import io
import re
from pathlib import Path

from papermind.models import Document, Figure, Paragraph, Section, Table

from .assets import AssetBuffer, image_to_png


class DocumentParser:
    supported = frozenset(
        {
            ".pdf",
            ".txt",
            ".md",
            ".csv",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".docx",
            ".xlsx",
        }
    )

    def __init__(
        self,
        max_pages: int = 500,
        max_figures: int = 64,
        max_image_edge: int = 1280,
        max_image_pixels: int = 20000000,
    ):
        self.max_pages = max_pages
        self.max_figures = max_figures
        self.max_image_edge = max_image_edge
        self.max_image_pixels = max_image_pixels

    def parse(
        self,
        path: Path,
        document_id: str,
        filename: str,
        assets: AssetBuffer | None = None,
    ) -> Document:
        assets = assets if assets is not None else AssetBuffer()
        suffix = Path(filename).suffix.lower()
        if suffix not in self.supported:
            raise ValueError(f"Unsupported document format: {suffix}")
        document = Document(
            document_id, Path(filename).stem, metadata={"filename": filename}
        )
        if suffix in {".docx", ".xlsx"}:
            from .office_common import office_dependencies, validate_office_archive

            office_dependencies()
            try:
                validate_office_archive(path)
                if suffix == ".docx":
                    from .docx_parser import parse_docx

                    return parse_docx(path, document)
                from .xlsx_parser import parse_xlsx

                return parse_xlsx(path, document)
            except (ValueError, RuntimeError):
                raise
            except Exception as exc:
                raise ValueError(
                    "Office 文件无法解析，请确认未加密，并重新另存为 DOCX/XLSX。"
                ) from exc
        if suffix == ".pdf":
            from .pdf_parser import parse_pdf

            return parse_pdf(
                path,
                document,
                self.max_pages,
                assets,
                self.max_figures,
                self.max_image_edge,
            )
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            png = image_to_png(path, self.max_image_edge, self.max_image_pixels)
            document.figures.append(
                Figure(
                    "fig_1",
                    1,
                    asset_id=assets.add(png),
                    section=document.title,
                    extraction_method="uploaded_image",
                )
            )
            document.metadata["page_count"] = 1
            return document
        content = path.read_text(encoding="utf-8-sig")
        if suffix == ".csv":
            rows = list(csv.reader(io.StringIO(content)))
            if not rows or not rows[0]:
                raise ValueError("CSV has no header")
            if any(len(row) != len(rows[0]) for row in rows[1:]):
                raise ValueError("CSV rows have inconsistent column counts")
            document.tables.append(
                Table("table_1", 1, rows[0], rows[1:], document.title)
            )
            return document
        current = Section(document.title, 1)
        document.sections.append(current)
        for block in re.split(r"\n\s*\n", content.strip()):
            for part in re.split(r"(?m)^(?=#{1,6}\s)", block):
                lines = part.strip().splitlines()
                if not lines:
                    continue
                heading = re.match(r"^(#{1,6})\s+(.+)$", lines[0])
                if heading:
                    current = Section(heading[2].strip(), len(heading[1]))
                    document.sections.append(current)
                    lines = lines[1:]
                text = "\n".join(lines).strip()
                if text:
                    current.paragraphs.append(Paragraph(text, 1))
        return document
