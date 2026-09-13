import hashlib
import io
import warnings
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AssetBuffer:
    max_bytes: int = 32 * 1024 * 1024
    items: dict[str, bytes] = field(default_factory=dict)
    size: int = 0

    def add(self, png: bytes) -> str:
        asset_id = hashlib.sha256(png).hexdigest()
        if asset_id not in self.items:
            if self.size + len(png) > self.max_bytes:
                raise ValueError("Document image assets exceed the byte limit")
            self.items[asset_id] = png
            self.size += len(png)
        return asset_id


def image_to_png(path: Path, max_edge: int, max_pixels: int) -> bytes:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError(
            "Image parsing requires the papermind[vision] extra"
        ) from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.width * image.height > max_pixels:
                    raise ValueError("Image exceeds the pixel limit")
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Image content must be PNG, JPEG or WebP")
                frame = ImageOps.exif_transpose(image)
                try:
                    frame.thumbnail((max_edge, max_edge))
                    with frame.convert("RGB") as rgb:
                        buffer = io.BytesIO()
                        rgb.save(buffer, format="PNG")
                        return buffer.getvalue()
                finally:
                    frame.close()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Invalid, damaged or oversized image") from exc


def render_region(page, bbox, max_edge: int) -> bytes:
    import pymupdf

    # 图像位置是未旋转的 PDF 坐标；先转换到渲染坐标再裁剪。
    rect = pymupdf.Rect(bbox) * page.rotation_matrix
    rect = rect & page.rect
    if rect.is_empty or rect.is_infinite:
        raise ValueError("Invalid image region")
    scale = min(2.0, max_edge / max(rect.width, rect.height))
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        clip=rect,
        colorspace=pymupdf.csRGB,
        alpha=False,
    )
    return pixmap.tobytes("png")
