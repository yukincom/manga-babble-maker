"""Place glyph runs centered on the bubble center (vertical Japanese)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

from manga_babble.schema import normalize_bbox
from manga_babble.text.breaks import split_text_to_chunks
from manga_babble.text.profile import resolve_break_profile

MIN_FONT_PX = 12

# Horizontal glyphs that should be rotated 90° CW for vertical writing
_VERTICAL_ROTATE = set(
    "ー−‐–—〜～…‥：；―ｰ"
)


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


def _draw_vertical_glyph(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    ch: str,
    cx: float,
    cy: float,
    font: ImageFont.ImageFont,
    size: int,
    fill=(0, 0, 0, 255),
) -> None:
    """Draw one character; rotate long-vowel / dash / ellipsis for tate-gaki."""
    if ch not in _VERTICAL_ROTATE:
        try:
            tb = draw.textbbox((0, 0), ch, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = size, size
        draw.text((cx - tw / 2, cy), ch, fill=fill, font=font)
        return

    # Render on a temp canvas, rotate 90° CW so ー becomes vertical
    pad = max(4, size // 2)
    canvas = Image.new("RGBA", (size * 3, size * 3), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canvas)
    try:
        tb = cd.textbbox((0, 0), ch, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ox, oy = -tb[0], -tb[1]
    except Exception:
        tw, th = size, size
        ox, oy = 0, 0
    cd.text((pad + ox, pad + oy), ch, fill=fill, font=font)
    cropped = canvas.crop((pad, pad, pad + max(1, tw), pad + max(1, th)))
    rotated = cropped.rotate(-90, expand=True, resample=Image.Resampling.BICUBIC)
    rw, rh = rotated.size
    dest = (int(round(cx - rw / 2)), int(round(cy + (size - rh) / 2)))
    img.alpha_composite(rotated, dest=dest)


def draw_text_on_bubbles(
    width: int,
    height: int,
    bubbles: list[dict[str, Any]],
    *,
    options: dict[str, Any] | None = None,
) -> Image.Image:
    """
    Draw text for each bubble.
    - Chunks from split_text_to_chunks (explicit　 first)
    - Each chunk = one vertical column (top→bottom)
    - Columns right→left
    - Entire block centered on bubble center
    - Long vowel ー etc. rotated for vertical writing
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    options = options or {}

    for b in sorted(bubbles, key=lambda x: x.get("order", 0)):
        text = str(b.get("text") or "")
        if not text:
            continue
        meta = b.get("meta") or {}
        prof = resolve_break_profile(
            options,
            speaker=b.get("speaker") or b.get("speaker_face_id"),
            line_meta=meta,
        )
        chunks = split_text_to_chunks(
            text,
            profile=prof,
            options=options,
            speaker=b.get("speaker"),
            line_meta=meta,
            placement=meta.get("placement"),
        )
        if not chunks:
            continue

        x1, y1, x2, y2 = normalize_bbox(b["bubble_bbox"])
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        bcx, bcy = (x1 + x2) / 2, (y1 + y2) / 2

        max_len = max(len(c) for c in chunks)
        n_cols = len(chunks)
        margin_guess = float(MIN_FONT_PX)
        avail_h = max(1.0, bh - 2 * margin_guess)
        avail_w = max(1.0, bw - 2 * margin_guess)
        size = int(min(avail_h / max(max_len, 1), avail_w / max(n_cols, 1), 22))
        size = max(MIN_FONT_PX, size)
        pitch = size * 1.08
        col_gap = size * 1.15
        margin = float(size)
        font = _load_font(size)

        col_heights = [max(1, len(c)) * pitch for c in chunks]
        block_h = max(col_heights) if col_heights else pitch
        block_w = n_cols * col_gap if n_cols else size

        block_left = bcx - block_w / 2
        block_top = bcy - block_h / 2

        if block_left < x1 + margin:
            block_left = x1 + margin
        if block_top < y1 + margin:
            block_top = y1 + margin
        if block_left + block_w > x2 - margin:
            block_left = max(x1 + margin, x2 - margin - block_w)
        if block_top + block_h > y2 - margin:
            block_top = max(y1 + margin, y2 - margin - block_h)

        for ci, chunk in enumerate(chunks):
            col_index_from_right = n_cols - 1 - ci
            cx = block_left + col_index_from_right * col_gap + size * 0.5
            glyphs = list(chunk.replace("\n", ""))
            for ri, ch in enumerate(glyphs):
                cy = block_top + ri * pitch
                _draw_vertical_glyph(img, draw, ch, cx, cy, font, size)

    return img
