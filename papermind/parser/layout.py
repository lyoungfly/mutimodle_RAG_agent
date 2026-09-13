import re

CAPTION = re.compile(r"^(?:(?:fig(?:ure)?\.?|table)\s*\d+|[图表]\s*\d+)", re.IGNORECASE)
FIGURE_CAPTION = re.compile(r"^(?:fig(?:ure)?\.?\s*\d+|图\s*\d+)", re.IGNORECASE)
TABLE_CAPTION = re.compile(r"^(?:table\s*\d+|表\s*\d+)", re.IGNORECASE)


def caption_near(bbox, blocks, kind="figure") -> str:
    pattern = FIGURE_CAPTION if kind == "figure" else TABLE_CAPTION
    candidates = []
    for block in blocks:
        if not pattern.match(block[4].strip()):
            continue
        overlap = min(bbox[2], block[2]) - max(bbox[0], block[0])
        if overlap <= 0:
            continue
        below = block[1] >= bbox[3] - 8
        above = block[3] <= bbox[1] + 8
        if not below and not above:
            continue
        distance = max(0, block[1] - bbox[3]) if below else max(0, bbox[1] - block[3])
        if distance <= 90:
            preferred = below if kind == "figure" else above
            candidates.append((distance + (0 if preferred else 30), block[4].strip()))
    return min(candidates)[1] if candidates else ""


def section_at(bbox, headings):
    applicable = [(y, title) for y, title in headings if y <= bbox[1]]
    return max(applicable, key=lambda x: x[0])[1] if applicable else ""


def nearby_text(bbox, blocks, limit=1800):
    candidates = []
    for block in blocks:
        text = block[4].strip()
        if CAPTION.match(text):
            continue
        if min(bbox[2], block[2]) <= max(bbox[0], block[0]):
            continue
        distance = max(0, block[1] - bbox[3], bbox[1] - block[3])
        if distance < 180:
            candidates.append((distance, block[1], text))
    chosen = sorted(sorted(candidates)[:3], key=lambda x: x[1])
    return "\n".join(text for _, _, text in chosen)[:limit]
