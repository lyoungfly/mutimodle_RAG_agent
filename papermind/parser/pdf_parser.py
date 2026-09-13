import logging
import re
from pathlib import Path

from papermind.models import Document, Paragraph, Section, Table

from .assets import AssetBuffer, render_region
from .figure_parser import extract_figures
from .layout import caption_near, section_at

logger = logging.getLogger(__name__)


def parse_pdf(
    path: Path,
    document: Document,
    max_pages: int,
    assets: AssetBuffer | None = None,
    max_figures: int = 64,
    max_image_edge: int = 1280,
) -> Document:
    assets = assets if assets is not None else AssetBuffer()
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires the papermind[pdf] extra") from exc
    warnings = []
    document.metadata["warnings"] = warnings
    try:
        pdf = pymupdf.open(path)
    except pymupdf.FileDataError as exc:
        raise ValueError("Invalid or damaged PDF") from exc
    with pdf:
        if pdf.needs_pass:
            raise ValueError("Encrypted PDF requires decryption before upload")
        if len(pdf) > max_pages:
            raise ValueError(f"PDF exceeds the {max_pages} page limit")
        document.title = pdf.metadata.get("title") or document.title
        document.metadata["page_count"] = len(pdf)
        current = Section(document.title, 1)
        document.sections.append(current)
        for number, page in enumerate(pdf, start=1):
            headings = [(float("-inf"), current.title)]
            blocks = page.get_text("blocks", sort=True)
            text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
            if not text_blocks:
                warnings.append(f"Page {number}: no extractable text; OCR is required")
            for block in text_blocks:
                text = block[4].strip()
                # 首版使用保守的标题规则，避免把普通短句误判为章节。
                heading = re.match(r"^(\d+(?:\.\d+)*\.?)\s+[A-Z][^\n]{1,100}$", text)
                if heading or text.lower() in {"abstract", "references", "conclusion"}:
                    level = len(heading[1].rstrip(".").split(".")) if heading else 1
                    current = Section(text, level)
                    document.sections.append(current)
                    headings.append((block[1], current.title))
                else:
                    current.paragraphs.append(Paragraph(text, number, tuple(block[:4])))
            try:
                for table in page.find_tables().tables:
                    rows = [[str(c or "") for c in row] for row in table.extract()]
                    if rows:
                        asset_id = ""
                        try:
                            asset_id = assets.add(
                                render_region(page, table.bbox, max_image_edge)
                            )
                        except ValueError as exc:
                            warnings.append(
                                f"Page {number}: table preview unavailable: {exc}"
                            )
                        document.tables.append(
                            Table(
                                f"table_{len(document.tables) + 1}",
                                number,
                                rows[0],
                                rows[1:],
                                caption=caption_near(table.bbox, text_blocks, "table"),
                                section=section_at(table.bbox, headings),
                                bbox=tuple(table.bbox),
                                asset_id=asset_id,
                            )
                        )
            except Exception:
                logger.exception(
                    "Table extraction failed: document=%s page=%s",
                    document.document_id,
                    number,
                )
                warnings.append(f"Page {number}: table extraction failed")
            try:
                extract_figures(
                    page,
                    document,
                    text_blocks,
                    headings,
                    assets,
                    max_figures,
                    max_image_edge,
                )
            except Exception:
                logger.exception(
                    "Figure extraction failed: document=%s page=%s",
                    document.document_id,
                    number,
                )
                warnings.append(f"Page {number}: figure extraction failed")
    document.metadata["warnings"] = warnings
    return document
