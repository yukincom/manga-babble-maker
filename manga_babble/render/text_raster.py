"""Raster text layer only (no bubble frame). Simple vertical-friendly layout."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

from manga_babble.schema import normalize_bbox


def _load_font(size: int) -> ImageFont.ImageFont:
    # Prefer common JP-capable fonts on macOS; fall back to default.
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _vertical_chars(text: str) -> list[str]:
    # Keep newlines as column breaks
    cols: list[list[str]] = [[]]
    for ch in text:
        if ch == "\n":
            cols.append([])
            continue
        if ch in (" ", "\t"):
            continue
        cols[-1].append(ch)
    # Manga vertical: columns right-to-left
    return cols


def draw_text_layer(
    width: int,
    height: int,
    bubbles: list[dict[str, Any]],
) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for b in sorted(bubbles, key=lambda x: x.get("order", 0)):
        text = str(b.get("text") or "")
        if not text:
            continue
        x1, y1, x2, y2 = normalize_bbox(b["bubble_bbox"])
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        # Font size from bubble height / char rows estimate
        n = max(1, len(text.replace("\n", "").replace(" ", "")))
        cols = max(1, min(4, (n + 5) // 6))
        rows = max(1, (n + cols - 1) // cols)
        size = int(min(bh / (rows + 1.5), bw / (cols + 1.0), 36))
        size = max(10, size)
        font = _load_font(size)

        columns = _vertical_chars(text)
        # If single long column, split by rows capacity
        if len(columns) == 1 and len(columns[0]) > rows + 2:
            chars = columns[0]
            columns = []
            for i in range(0, len(chars), rows):
                columns.append(chars[i : i + rows])

        col_w = bw / (len(columns) + 1)
        # Right-to-left columns
        for ci, col in enumerate(reversed(columns)):
            cx = x2 - col_w * (ci + 1)
            for ri, ch in enumerate(col):
                cy = y1 + (bh * (ri + 1)) / (len(col) + 1)
                # Center glyph roughly
                try:
                    bbox = draw.textbbox((0, 0), ch, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except Exception:
                    tw, th = size, size
                draw.text(
                    (cx - tw / 2, cy - th / 2),
                    ch,
                    fill=(0, 0, 0, 255),
                    font=font,
                )
    return img
