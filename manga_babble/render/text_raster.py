"""Raster text layer — delegates to center-based layout + break pipeline."""

from __future__ import annotations

from typing import Any

from PIL import Image

from manga_babble.text.layout_text import draw_text_on_bubbles


def draw_text_layer(
    width: int,
    height: int,
    bubbles: list[dict[str, Any]],
    *,
    options: dict[str, Any] | None = None,
) -> Image.Image:
    return draw_text_on_bubbles(width, height, bubbles, options=options)
