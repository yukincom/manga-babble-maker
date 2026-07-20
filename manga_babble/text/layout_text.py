"""Place glyph runs centered on the bubble center."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

from manga_babble.schema import normalize_bbox
from manga_babble.text.breaks import split_text_to_chunks
from manga_babble.text.profile import resolve_break_profile

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

        # Font size: fit longest chunk + margins, min 12
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

        # Measure block size (columns = chunks, rightmost = first chunk)
        col_heights = [max(1, len(c)) * pitch for c in chunks]
        block_h = max(col_heights) if col_heights else pitch
        block_w = n_cols * col_gap if n_cols else size

        # Center block on bubble center
        block_left = bcx - block_w / 2
        block_top = bcy - block_h / 2

        # Clamp block inside bubble with margin
        if block_left < x1 + margin:
            block_left = x1 + margin
        if block_top < y1 + margin:
            block_top = y1 + margin
        if block_left + block_w > x2 - margin:
            block_left = max(x1 + margin, x2 - margin - block_w)
        if block_top + block_h > y2 - margin:
            block_top = max(y1 + margin, y2 - margin - block_h)

        # Draw columns right-to-left: first chunk is rightmost
        for ci, chunk in enumerate(chunks):
            # index 0 → right side of block
            col_index_from_right = n_cols - 1 - ci
            cx = block_left + col_index_from_right * col_gap + size * 0.5
            glyphs = list(chunk.replace("\n", ""))
            for ri, ch in enumerate(glyphs):
                cy = block_top + ri * pitch
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
