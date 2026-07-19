"""Raster speech-bubble layer (frame + tail only, no text).

Sprint-now shapes (generic only; user templates for cloud/soft burst later):
  normal / whisper : ellipse (+ short triangle tail; whisper dashed)
  shout            : hard modest jagged, NO triangle tail
  narration / note : rectangle, no tail
  thought          : temporary ellipse + dots (cloud templates later)
"""

from __future__ import annotations

import math
import random
from typing import Any

from PIL import Image, ImageDraw

from manga_babble.schema import normalize_bbox


def _ellipse_pts(cx, cy, rx, ry, seed=0, n=48):
    return [
        (
            cx + rx * math.cos(2 * math.pi * i / n),
            cy + ry * math.sin(2 * math.pi * i / n),
        )
        for i in range(n)
    ]


def _hard_jagged_pts(cx, cy, rx, ry, seed=0, spikes=8, indent=0.22):
    """
    Hard (polygonal) jagged: angular ellipse + modest spikes.
    Not an explosion mark — few spikes, moderate indent, tiny noise.
    """
    rnd = random.Random(seed)
    pts = []
    for i in range(spikes * 2):
        t = math.pi * i / spikes
        # outer tip / inner valley
        base_r = 1.0 if i % 2 == 0 else (1.0 - indent)
        r = base_r * (1 + rnd.uniform(-0.03, 0.03))
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return pts


def _nearest_point_on_bbox(px, py, bbox):
    x1, y1, x2, y2 = bbox
    return min(max(px, x1), x2), min(max(py, y1), y2)


def _clamp_tail_target(cx, cy, rx, ry, target, max_len_ratio=0.45):
    """Shorten tail tip so it does not spear across the page."""
    tx, ty = target
    dx, dy = tx - cx, ty - cy
    dist = math.hypot(dx, dy) or 1.0
    # Start from ellipse edge
    edge = max(rx, ry) * 0.85
    max_len = max(rx, ry) * 2 * max_len_ratio
    if dist <= edge + 4:
        return tx, ty
    # Point at most max_len beyond the bubble center toward target
    scale = min(1.0, (edge + max_len) / dist)
    return cx + dx * scale, cy + dy * scale


def _draw_polygon(draw: ImageDraw.ImageDraw, pts, fill, outline, width, dashed=False):
    if len(pts) < 3:
        return
    ip = [(int(round(x)), int(round(y))) for x, y in pts]
    draw.polygon(ip, fill=fill, outline=outline)
    if dashed:
        for i in range(len(ip)):
            p0, p1 = ip[i], ip[(i + 1) % len(ip)]
            if i % 2 == 0:
                draw.line([p0, p1], fill=outline, width=width)
    else:
        draw.line(ip + [ip[0]], fill=outline, width=width)


def _draw_one(
    draw: ImageDraw.ImageDraw,
    bubble: dict[str, Any],
    stroke: int = 4,
):
    tone = bubble.get("tone") or "normal"
    seed = int((bubble.get("meta") or {}).get("seed") or 0)
    x1, y1, x2, y2 = normalize_bbox(bubble["bubble_bbox"])
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = max(1.0, (x2 - x1) / 2), max(1.0, (y2 - y1) / 2)
    face = bubble.get("speaker_face_bbox")
    placement = (bubble.get("meta") or {}).get("placement") or ""

    # Rectangle: narration and page-margin notes
    if tone in ("narration", "note") or placement == "page_margin":
        draw.rectangle(
            [int(x1), int(y1), int(x2), int(y2)],
            fill=(255, 255, 255, 255),
            outline=(0, 0, 0, 255),
            width=stroke,
        )
        return

    if tone == "shout":
        pts = _hard_jagged_pts(cx, cy, rx, ry, seed=seed)
    else:
        # normal, whisper, thought body (thought cloud templates later)
        pts = _ellipse_pts(cx, cy, rx, ry, seed=seed)

    dashed = tone == "whisper"
    _draw_polygon(
        draw,
        pts,
        fill=(255, 255, 255, 255),
        outline=(0, 0, 0, 255),
        width=stroke,
        dashed=dashed,
    )

    # shout: no triangle tail (shape alone; user soft-burst templates later)
    if tone == "shout" or face is None:
        return

    fx1, fy1, fx2, fy2 = normalize_bbox(face)
    aim = (fx1, fy1, fx2, fy2 + (fy2 - fy1) * 0.3)
    target = _nearest_point_on_bbox(cx, cy, aim)
    target = _clamp_tail_target(cx, cy, rx, ry, target)

    if tone == "thought":
        for i, frac in enumerate((0.35, 0.58, 0.78)):
            bx = cx + (target[0] - cx) * frac
            by = cy + (target[1] - cy) * frac
            r = max(3, 10 - i * 3)
            draw.ellipse(
                [bx - r, by - r, bx + r, by + r],
                fill=(255, 255, 255, 255),
                outline=(0, 0, 0, 255),
                width=max(1, stroke - 1),
            )
        return

    # normal / whisper: short triangle tail
    angle = math.atan2(target[1] - cy, target[0] - cx)
    base_x = cx + rx * 0.92 * math.cos(angle)
    base_y = cy + ry * 0.92 * math.sin(angle)
    perp = angle + math.pi / 2
    tw = min(16, max(8, min(rx, ry) * 0.25))
    dx, dy = math.cos(perp) * tw / 2, math.sin(perp) * tw / 2
    tri = [
        (base_x + dx, base_y + dy),
        (base_x - dx, base_y - dy),
        (target[0], target[1]),
    ]
    _draw_polygon(
        draw,
        tri,
        fill=(255, 255, 255, 255),
        outline=(0, 0, 0, 255),
        width=stroke,
    )


def draw_bubble_layer(
    width: int,
    height: int,
    bubbles: list[dict[str, Any]],
    *,
    stroke_width: int = 4,
) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ordered = sorted(bubbles, key=lambda b: b.get("order", 0))
    for b in ordered:
        _draw_one(draw, b, stroke=stroke_width)
    return img
