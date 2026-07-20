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


def size_from_text(text: str, page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """
    Preferred half sizes from character count (vertical-friendly).

    - Prefer single column when n < 12 (no wrap)
    - ~1 character margin each side
    - Sized so at least MIN_FONT_PX text can fit
    """
    n = max(1, len(str(text).replace("\n", "").replace(" ", "")))
    # Line-break policy: only consider multi-column if 12+ chars
    if n < 12:
        cols, rows = 1, n
    else:
        cols = max(1, min(4, (n + 5) // 6))
        rows = max(1, (n + cols - 1) // cols)

    char_px = max(MIN_FONT_PX, min(28.0, page_h / 50.0))
    margin = char_px * 1.0  # one character padding each side
    min_half_w = (cols * char_px + 2 * margin) / 2
    min_half_h = (rows * char_px + 2 * margin) / 2
    max_half_w = page_w * 0.35
    max_half_h = page_h * 0.28
    min_half_w = min(min_half_w, max_half_w)
    min_half_h = min(min_half_h, max_half_h)
    return min_half_w, min_half_h, max_half_w, max_half_h
