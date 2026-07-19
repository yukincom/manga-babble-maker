"""Raster speech-bubble layer (frame + tail only, no text)."""

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


def _jagged_pts(cx, cy, rx, ry, seed=0, spikes=14, jitter=0.35):
    rnd = random.Random(seed)
    pts = []
    for i in range(spikes * 2):
        t = math.pi * i / spikes
        base_r = 1.0 if i % 2 == 0 else (1 - jitter)
        r = base_r * (1 + rnd.uniform(-0.08, 0.08))
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return pts


def _cloud_pts(cx, cy, rx, ry, seed=0, bumps=10, n=96):
    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        bump = 1 + 0.12 * math.sin(bumps * t) + rnd.uniform(-0.015, 0.015)
        pts.append((cx + rx * bump * math.cos(t), cy + ry * bump * math.sin(t)))
    return pts


def _nearest_point_on_bbox(px, py, bbox):
    x1, y1, x2, y2 = bbox
    return min(max(px, x1), x2), min(max(py, y1), y2)


def _draw_polygon(draw: ImageDraw.ImageDraw, pts, fill, outline, width, dashed=False):
    if len(pts) < 3:
        return
    ip = [(int(round(x)), int(round(y))) for x, y in pts]
    draw.polygon(ip, fill=fill, outline=outline)
    if dashed:
        # Approximate dash by overdrawing white gaps on outline
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

    if tone == "narration":
        draw.rectangle(
            [int(x1), int(y1), int(x2), int(y2)],
            fill=(255, 255, 255, 255),
            outline=(0, 0, 0, 255),
            width=stroke,
        )
        return

    if tone == "shout":
        pts = _jagged_pts(cx, cy, rx, ry, seed=seed)
    elif tone == "thought":
        pts = _cloud_pts(cx, cy, rx, ry, seed=seed)
    else:
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

    if face is None:
        return
    fx1, fy1, fx2, fy2 = normalize_bbox(face)
    aim = (fx1, fy1, fx2, fy2 + (fy2 - fy1) * 0.3)
    target = _nearest_point_on_bbox(cx, cy, aim)

    if tone == "thought":
        for i, frac in enumerate((0.32, 0.56, 0.78)):
            bx = cx + (target[0] - cx) * frac
            by = cy + (target[1] - cy) * frac
            r = max(3, 11 - i * 3)
            draw.ellipse(
                [bx - r, by - r, bx + r, by + r],
                fill=(255, 255, 255, 255),
                outline=(0, 0, 0, 255),
                width=max(1, stroke - 1),
            )
    else:
        angle = math.atan2(target[1] - cy, target[0] - cx)
        base_x = cx + rx * math.cos(angle)
        base_y = cy + ry * math.sin(angle)
        perp = angle + math.pi / 2
        tw = 18
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
