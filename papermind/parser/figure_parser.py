import logging

from papermind.models import Figure

from .assets import AssetBuffer, render_region
from .layout import FIGURE_CAPTION, caption_near, nearby_text, section_at

logger = logging.getLogger(__name__)


def extract_figures(
    page, document, blocks, headings, assets: AssetBuffer, max_figures, max_edge
):
    import pymupdf

    regions = []
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"])
        if (
            rect.width >= 40
            and rect.height >= 40
            and not any(
                (rect & old).get_area() >= 0.9 * rect.get_area() for old, _ in regions
            )
        ):
            regions.append((rect, "embedded_image"))
    # 矢量图没有独立图片对象，通过图注附近的绘图区域定位。
    captions = [b for b in blocks if FIGURE_CAPTION.match(b[4].strip())]
    drawings = page.get_drawings() if captions else []
    for caption in captions:
        if any(caption_near(rect, [caption]) for rect, _ in regions):
            continue
        parts = [
            pymupdf.Rect(d["rect"])
            for d in drawings
            if caption[1] - 260 <= d["rect"].y0 < caption[1]
            and d["rect"].y1 <= caption[1] + 3
            and d["rect"].x1 > caption[0]
            and d["rect"].x0 < caption[2]
        ]
        if parts:
            rect = parts[0]
            for part in parts[1:]:
                rect = rect | part
            if rect.width >= 40 and rect.height >= 30:
                rect = rect + (-4, -4, 4, 4)
                if not any(
                    (rect & old).get_area() >= 0.8 * rect.get_area()
                    for old, _ in regions
                ):
                    regions.append((rect, "caption_vector_region"))
    warnings = document.metadata.setdefault("warnings", [])
    for rect, method in sorted(regions, key=lambda item: (item[0].y0, item[0].x0)):
        if len(document.figures) >= max_figures:
            warning = f"Figure limit ({max_figures}) reached; remaining figures were not extracted"
            if warning not in warnings:
                warnings.append(warning)
            break
        try:
            asset_id = assets.add(render_region(page, rect, max_edge))
        except ValueError as exc:
            warnings.append(f"Page {page.number + 1}: {exc}")
            continue
        except Exception:
            logger.exception("Image extraction failed: page=%s", page.number + 1)
            warnings.append(f"Page {page.number + 1}: image extraction failed")
            continue
        document.figures.append(
            Figure(
                f"fig_{len(document.figures) + 1}",
                page.number + 1,
                caption=caption_near(rect, blocks),
                section=section_at(rect, headings),
                bbox=tuple(rect),
                asset_id=asset_id,
                nearby_text=nearby_text(rect, blocks),
                extraction_method=method,
            )
        )
