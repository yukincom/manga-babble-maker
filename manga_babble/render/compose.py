"""Optional preview composite (art + bubble + text)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def compose_preview(
    art_path: str | Path | None,
    bubble: Image.Image,
    text: Image.Image,
    *,
    width: int,
    height: int,
) -> Image.Image:
    if art_path and Path(art_path).is_file():
        base = Image.open(art_path).convert("RGBA")
        if base.size != (width, height):
            base = base.resize((width, height), Image.Resampling.BILINEAR)
    else:
        base = Image.new("RGBA", (width, height), (240, 240, 240, 255))
    out = base.copy()
    out.alpha_composite(bubble)
    out.alpha_composite(text)
    return out
