"""Raster speech-bubble layer.

- ellipse / whisper: procedural
- narration / v-rect: rectangle
- cloud / jagged: templates from assets/shapes/ when present
- page_margin: no frame
"""

from __future__ import annotations

import math
import random
from typing import Any

from PIL import Image, ImageDraw

from manga_babble.schema import normalize_bbox
from manga_babble.shapes.templates import (
    fit_template_to_bbox,
    load_template,
    pick_template_path,
)


def _ellipse_pts(cx, cy, rx, ry, seed=0, n=48):
    return [
        (
            cx + rx * math.cos(2 * math.pi * i / n),
            cy + ry * math.sin(2 * math.pi * i / n),
        )
        for i in range(n)
    ]


def _hard_jagged_pts(cx, cy, rx, ry, seed=0, spikes=8, indent=0.22):
    rnd = random.Random(seed)
    pts = []
    for i in range(spikes * 2):
        t = math.pi * i / spikes
        base_r = 1.0 if i % 2 == 0 else (1.0 - indent)
        r = base_r * (1 + rnd.uniform(-0.03, 0.03))
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return pts


def _nearest_point_on_bbox(px, py, bbox):
    x1, y1, x2, y2 = bbox
    return min(max(px, x1), x2), min(max(py, y1), y2)


def _clamp_tail_target(cx, cy, rx, ry, target, max_len_ratio=0.45):
    tx, ty = target
    dx, dy = tx - cx, ty - cy
    dist = math.hypot(dx, dy) or 1.0
    edge = max(rx, ry) * 0.85
    max_len = max(rx, ry) * 2 * max_len_ratio
    if dist <= edge + 4:
        return tx, ty
    scale = min(1.0, (edge + max_len) / dist)
    return cx + dx * scale, cy + dy * scale


def _draw_polygon(draw, pts, fill, outline, width, dashed=False):
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


def _try_paste_template(
    img: Image.Image,
    kind: str,
    bbox: tuple[float, float, float, float],
    seed: int,
    template_id: str | None,
) -> bool:
    path = pick_template_path(kind, seed=seed, template_id=template_id)
    if path is None:
        return False
    tmpl = load_template(str(path))
    fitted, xy = fit_template_to_bbox(tmpl, bbox)
    img.alpha_composite(fitted, dest=xy)
    return True


def _draw_one(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    bubble: dict[str, Any],
    stroke: int = 4,
):
    tone = bubble.get("tone") or "normal"
    meta = bubble.get("meta") or {}
    seed = int(meta.get("seed") or 0)
    shape = (meta.get("shape") or "").replace("_", "-")
    template_id = meta.get("template_id")
    x1, y1, x2, y2 = normalize_bbox(bubble["bubble_bbox"])
    bbox = (x1, y1, x2, y2)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = max(1.0, (x2 - x1) / 2), max(1.0, (y2 - y1) / 2)
    face = bubble.get("speaker_face_bbox")
    placement = meta.get("placement") or ""

    if placement == "page_margin":
        return

    if shape in ("rect", "v-rect", "tall-rect") or tone == "narration":
        draw.rectangle(
            [int(x1), int(y1), int(x2), int(y2)],
            fill=(255, 255, 255, 255),
            outline=(0, 0, 0, 255),
            width=stroke,
        )
        return

    # fun-cloud = bright・playful SPEECH (not 心の声)
    use_fun_cloud = shape in ("fun-cloud", "cloud", "kumo")
    use_jagged = shape in ("jagged",) or tone == "shout"
    is_thought = tone == "thought"

    if use_fun_cloud:
        if not _try_paste_template(img, "fun-cloud", bbox, seed, template_id):
            pts = _ellipse_pts(cx, cy, rx, ry, seed=seed)
            _draw_polygon(draw, pts, (255, 255, 255, 255), (0, 0, 0, 255), stroke)
        if face is not None:
            _draw_triangle_tail(draw, cx, cy, rx, ry, face, stroke)
        return

    if use_jagged:
        if _try_paste_template(img, "jagged", bbox, seed, template_id):
            return  # no triangle tail on shout
        pts = _hard_jagged_pts(cx, cy, rx, ry, seed=seed)
        _draw_polygon(draw, pts, (255, 255, 255, 255), (0, 0, 0, 255), stroke)
        return

    # ellipse / whisper / thought body
    pts = _ellipse_pts(cx, cy, rx, ry, seed=seed)
    dashed = shape == "dashed-ellipse" or tone == "whisper"
    _draw_polygon(
        draw, pts, (255, 255, 255, 255), (0, 0, 0, 255), stroke, dashed=dashed
    )

    if face is None:
        return

    if is_thought:
        # 心の声: oval + trail of circles (not cloud template)
        fx1, fy1, fx2, fy2 = normalize_bbox(face)
        aim = (fx1, fy1, fx2, fy2 + (fy2 - fy1) * 0.3)
        target = _clamp_tail_target(
            cx, cy, rx, ry, _nearest_point_on_bbox(cx, cy, aim)
        )
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

    _draw_triangle_tail(draw, cx, cy, rx, ry, face, stroke)


def _draw_triangle_tail(draw, cx, cy, rx, ry, face, stroke):
    fx1, fy1, fx2, fy2 = normalize_bbox(face)
    aim = (fx1, fy1, fx2, fy2 + (fy2 - fy1) * 0.3)
    target = _clamp_tail_target(cx, cy, rx, ry, _nearest_point_on_bbox(cx, cy, aim))
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
    _draw_polygon(draw, tri, (255, 255, 255, 255), (0, 0, 0, 255), stroke)


def draw_bubble_layer(
    width: int,
    height: int,
    bubbles: list[dict[str, Any]],
    *,
    stroke_width: int = 4,
) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for b in sorted(bubbles, key=lambda x: x.get("order", 0)):
        _draw_one(img, draw, b, stroke=stroke_width)
    return img
