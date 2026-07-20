"""Free-space bubble candidates via distance transform (from MVP)."""

from __future__ import annotations

import numpy as np
import cv2

# Font floor used when sizing bubbles so 12px text + 1ch margin fits.
MIN_FONT_PX = 12.0


def compute_bubble_candidates(
    frame_bbox,
    body_bboxes,
    face_bboxes,
    extra_bboxes=None,
    resolution=200,
    margin_ratio=0.03,
    top_k=3,
    min_half_w=40.0,
    min_half_h=30.0,
    max_half_w=None,
    max_half_h=None,
    prefer_text_size: bool = True,
):
    """
    Return list of {bbox: (x1,y1,x2,y2), score: float} inside frame_bbox,
    avoiding body/face/extra occupied regions.

    If prefer_text_size is True (default), bubble half-size is driven by
    min_half_* (from text metrics), not by the free-space peak radius.
    Free-space only chooses the *center* and rejects spots too tight to fit.
    """
    fx1, fy1, fx2, fy2 = map(float, frame_bbox)
    fw, fh = fx2 - fx1, fy2 - fy1
    if fw <= 0 or fh <= 0:
        return []

    res_x = resolution
    res_y = max(1, round(resolution * fh / fw))

    occupied = np.zeros((res_y, res_x), dtype=np.uint8)
    border = max(1, int(res_x * margin_ratio))
    occupied[:border, :] = 1
    occupied[-border:, :] = 1
    occupied[:, :border] = 1
    occupied[:, -border:] = 1

    def to_mask_coords(bbox):
        x1, y1, x2, y2 = map(float, bbox)
        mx1 = int((x1 - fx1) / fw * res_x)
        my1 = int((y1 - fy1) / fh * res_y)
        mx2 = int((x2 - fx1) / fw * res_x)
        my2 = int((y2 - fy1) / fh * res_y)
        return (
            max(mx1, 0),
            max(my1, 0),
            min(mx2, res_x),
            min(my2, res_y),
        )

    margin = max(1, int(res_x * margin_ratio))
    all_occ = list(body_bboxes) + list(face_bboxes) + list(extra_bboxes or [])
    for bbox in all_occ:
        mx1, my1, mx2, my2 = to_mask_coords(bbox)
        occupied[
            max(0, my1 - margin) : min(res_y, my2 + margin),
            max(0, mx1 - margin) : min(res_x, mx2 + margin),
        ] = 1

    px_per_unit = fw / res_x
    # Need free radius (in mask units) to fit preferred half-size
    need_r = max(min_half_w, min_half_h) / px_per_unit * 0.9

    results = []
    for _ in range(top_k):
        free = (1 - occupied).astype(np.uint8)
        dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
        # Mask out cells too small for the text-sized bubble
        if prefer_text_size and need_r > 1:
            fit = dist >= need_r
            if not np.any(fit):
                # relax: take global peak but still use text size (may clip)
                idx = np.unravel_index(np.argmax(dist), dist.shape)
                peak_val = float(dist[idx])
            else:
                masked = np.where(fit, dist, 0)
                idx = np.unravel_index(np.argmax(masked), masked.shape)
                peak_val = float(dist[idx])
        else:
            idx = np.unravel_index(np.argmax(dist), dist.shape)
            peak_val = float(dist[idx])

        if peak_val <= 1:
            break
        cy, cx = idx

        if prefer_text_size:
            half_w = float(min_half_w)
            half_h = float(min_half_h)
        else:
            half_w_ratio, half_h_ratio = 0.95, 0.8
            half_w = peak_val * half_w_ratio * px_per_unit
            half_h = peak_val * half_h_ratio * px_per_unit
            half_w = max(half_w, min_half_w)
            half_h = max(half_h, min_half_h)

        if max_half_w is not None:
            half_w = min(half_w, max_half_w)
        if max_half_h is not None:
            half_h = min(half_h, max_half_h)

        half_w_mask = half_w / px_per_unit
        half_h_mask = half_h / px_per_unit
        mx1, my1 = cx - half_w_mask, cy - half_h_mask
        mx2, my2 = cx + half_w_mask, cy + half_h_mask

        occupied[
            max(0, int(my1)) : min(res_y, int(my2) + 1),
            max(0, int(mx1)) : min(res_x, int(mx2) + 1),
        ] = 1

        cx_real = fx1 + cx * px_per_unit
        cy_real = fy1 + cy * px_per_unit
        bbox = (
            cx_real - half_w,
            cy_real - half_h,
            cx_real + half_w,
            cy_real + half_h,
        )
        bbox = (
            max(fx1, bbox[0]),
            max(fy1, bbox[1]),
            min(fx2, bbox[2]),
            min(fy2, bbox[3]),
        )
        results.append({"bbox": bbox, "score": peak_val})
    return results


def size_from_text(
    text: str,
    page_w: float,
    page_h: float,
    *,
    shape: str = "ellipse",
    num_chunks: int | None = None,
    max_rows: int | None = None,
    chunks: list[str] | None = None,
) -> tuple[float, float, float, float]:
    """
    Preferred half sizes from character count (vertical-friendly).

    Prefer passing ``chunks`` from ``split_text_to_chunks`` so place sizing
    matches render columns (cols = len(chunks), rows = max chunk length).

    Ellipse roundness may widen slightly, but is **capped** so balloons do not
    become empty horizontal ovals when text is only 1–2 columns.
    """
    import re

    t = str(text)
    if chunks is not None and len(chunks) > 0:
        parts = [str(c) for c in chunks if str(c).strip()]
        num_chunks = max(1, len(parts))
        max_rows = max((len(p) for p in parts), default=1)
        raw = "".join(parts)
    elif num_chunks is None:
        if "　" in t or "/" in t or "\n" in t:
            parts = [p for p in re.split(r"[\u3000/\n\r]+", t) if p.strip()]
            num_chunks = max(1, len(parts))
            max_rows = max((len(p) for p in parts), default=1)
            raw = "".join(parts)
        else:
            num_chunks = 1
            raw = t.replace(" ", "").replace("　", "").replace("/", "")
            max_rows = max(1, len(raw))
    else:
        raw = (
            t.replace("\n", "")
            .replace("　", "")
            .replace("/", "")
            .replace(" ", "")
        )
        if max_rows is None:
            max_rows = max(1, (len(raw) + int(num_chunks) - 1) // max(1, int(num_chunks)))

    n = max(1, len(raw))
    cols = max(1, int(num_chunks or 1))
    rows = max(1, int(max_rows or ((n + cols - 1) // cols)))

    char_px = max(MIN_FONT_PX, min(28.0, page_h / 50.0))
    margin = char_px * 1.0

    # Content box from actual columns × longest column
    content_w = cols * char_px + 2 * margin
    content_h = rows * char_px + 2 * margin
    min_half_w = content_w / 2
    min_half_h = content_h / 2

    shape = (shape or "ellipse").replace("_", "-")
    is_round_ellipse = shape in (
        "ellipse",
        "dashed-ellipse",
        "fun-cloud",
        "cloud",
        "",
    )

    if is_round_ellipse:
        full_w, full_h = content_w, content_h
        # Mild roundness: allow some side pad, but never explode width.
        # Cap: min(height-based target, 1.45× content width, content + 3ch)
        if full_h > full_w * 1.15:
            target = full_h / 1.2
            cap = min(content_w * 1.45, content_w + 3 * char_px)
            full_w = min(max(full_w, target), cap)
        if n <= 4 and cols <= 1:
            # Short single-column: near-circle, but still content-based floor
            side = max(full_w, full_h * 0.92)
            full_w = min(side, content_w * 1.5 + char_px)
            full_h = max(full_h, side * 0.95)
        min_half_w, min_half_h = full_w / 2, full_h / 2
    elif shape in ("jagged", "giza"):
        full_w, full_h = content_w, content_h
        side = max(full_w, full_h) * 1.05
        # Keep shout near-square but not thinner than content
        min_half_w = max(min_half_w, min(side, content_w * 1.3) / 2)
        min_half_h = max(min_half_h, side / 2)

    max_half_w = page_w * 0.35
    max_half_h = page_h * 0.28
    min_half_w = min(min_half_w, max_half_w)
    min_half_h = min(min_half_h, max_half_h)
    return min_half_w, min_half_h, max_half_w, max_half_h
