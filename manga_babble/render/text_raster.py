"""Raster text preview — dense packing, not spread across the whole bubble.

Rules:
  - Font size >= 12px
  - Wrap / multi-column only if len >= 12
  - Vertical: top→bottom, columns right→left
  - ~1 character margin inside bubble
  - Glyphs stacked with ~1.05 * size pitch (not frame-height / n)
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

from manga_babble.schema import normalize_bbox

MIN_FONT_PX = 12


def _load_font(size: int) -> ImageFont.ImageFont:
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


def _chars(text: str) -> list[str]:
    return [ch for ch in text if ch not in (" ", "\t", "\n")]


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
        chars = _chars(text)
        n = max(1, len(chars))

        # Font: prefer ~14–18, never below 12; fit if bubble is small
        size = MIN_FONT_PX
        pitch = size * 1.08
        margin = float(size)  # 1 character margin

        if n < 12:
            cols_n, rows_n = 1, n
        else:
            rows_n = max(6, int((bh - 2 * margin) / pitch))
            cols_n = max(1, (n + rows_n - 1) // rows_n)

        # Grow font if room (still dense packing)
        avail_h = max(1.0, bh - 2 * margin)
        avail_w = max(1.0, bw - 2 * margin)
        fit = int(min(avail_h / max(rows_n, 1), avail_w / max(cols_n, 1), 22))
        size = max(MIN_FONT_PX, min(fit, 22))
        pitch = size * 1.08
        margin = float(size)
        font = _load_font(size)

        # Column-major: fill top→bottom, then next column to the left
        columns: list[list[str]] = []
        if n < 12:
            columns = [chars]
        else:
            rows_n = max(1, int((bh - 2 * margin) / pitch))
            for i in range(0, n, rows_n):
                columns.append(chars[i : i + rows_n])

        # Start from top of inner box; rightmost column first
        inner_top = y1 + margin
        inner_right = x2 - margin
        col_gap = size * 1.15

        for ci, col in enumerate(reversed(columns)):
            cx = inner_right - ci * col_gap - size * 0.5
            for ri, ch in enumerate(col):
                cy = inner_top + ri * pitch
                try:
                    tb = draw.textbbox((0, 0), ch, font=font)
                    tw, th = tb[2] - tb[0], tb[3] - tb[1]
                except Exception:
                    tw, th = size, size
                draw.text(
                    (cx - tw / 2, cy),
                    ch,
                    fill=(0, 0, 0, 255),
                    font=font,
                )
    return img
