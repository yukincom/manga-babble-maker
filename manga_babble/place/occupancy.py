"""Dual-path occupancy for color ネーム pages.

Path A (detect):  color → extract black lines → B&W line art → RT-DETR
Path B (occupy):  color → chromatic fill mask (person paint) → HARD free-space
Merge:            place uses faces from A + occupancy from B; body AABB ignored.

Mono pages fall back to ink-envelope occupancy.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from manga_babble.schema import normalize_bbox


def load_page_bgr(image_path: str | Path | None) -> np.ndarray | None:
    if not image_path:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def load_page_gray(image_path: str | Path | None) -> np.ndarray | None:
    if not image_path:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def page_has_color_fill(
    bgr: np.ndarray,
    *,
    chroma_min: int = 18,
    min_frac: float = 0.005,
) -> bool:
    """True if image has meaningful non-gray colored fill (e.g. pink skin)."""
    b, g, r = cv2.split(bgr)
    mx = np.maximum(np.maximum(r, g), b).astype(np.int16)
    mn = np.minimum(np.minimum(r, g), b).astype(np.int16)
    chroma = (mx - mn) > chroma_min
    # exclude near-black and near-white
    mean = (r.astype(np.int16) + g + b) // 3
    mid = (mean > 40) & (mean < 250)
    return float(np.mean(chroma & mid)) >= min_frac


def extract_line_art_bgr(
    bgr: np.ndarray,
    *,
    line_thresh: int = 80,
) -> np.ndarray:
    """
    Black/dark strokes → black; everything else white.
    Suitable input for manga face/frame detectors.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lines = gray < int(line_thresh)
    out = np.full_like(gray, 255)
    out[lines] = 0
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def extract_person_fill_mask(
    bgr: np.ndarray,
    *,
    chroma_min: int = 18,
    dilate_iter: int = 2,
    dilate_ksize: int = 5,
) -> np.ndarray:
    """
    Chromatic filled regions = person paint (pink etc.).
    NOT black lines, NOT white paper.
    """
    b, g, r = cv2.split(bgr)
    r16, g16, b16 = r.astype(np.int16), g.astype(np.int16), b.astype(np.int16)
    mx = np.maximum(np.maximum(r16, g16), b16)
    mn = np.minimum(np.minimum(r16, g16), b16)
    chroma = (mx - mn) > chroma_min
    mean = (r16 + g16 + b16) // 3
    # filled skin-like midtones; drop pure black lines and pure white
    mid = (mean > 50) & (mean < 248)
    person = (chroma & mid).astype(np.uint8) * 255
    if dilate_iter > 0:
        k = max(1, int(dilate_ksize)) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        person = cv2.dilate(person, kernel, iterations=int(dilate_iter))
        # close small holes inside fill
        person = cv2.morphologyEx(person, cv2.MORPH_CLOSE, kernel, iterations=1)
    return person


def extract_line_ink_mask(
    bgr: np.ndarray,
    *,
    line_thresh: int = 80,
    dilate_iter: int = 1,
) -> np.ndarray:
    """Optional: thickened black lines also hard (don't cover ink)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ink = (gray < int(line_thresh)).astype(np.uint8) * 255
    if dilate_iter > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        ink = cv2.dilate(ink, kernel, iterations=int(dilate_iter))
    return ink


def face_margin_boxes(
    face_bboxes: list[tuple],
    *,
    pad_ratio: float = 0.12,
    pad_min: float = 6.0,
) -> list[tuple[float, float, float, float]]:
    out = []
    for bb in face_bboxes:
        x1, y1, x2, y2 = normalize_bbox(bb)
        fw, fh = x2 - x1, y2 - y1
        pad = max(pad_min, min(fw, fh) * pad_ratio)
        out.append((x1 - pad, y1 - pad, x2 + pad, y2 + pad))
    return out


def stamp_boxes_on_mask(
    mask: np.ndarray,
    boxes: list[tuple],
    *,
    value: int = 255,
) -> np.ndarray:
    out = mask.copy()
    h, w = out.shape[:2]
    for bb in boxes:
        x1, y1, x2, y2 = normalize_bbox(bb)
        ix1 = max(0, int(np.floor(x1)))
        iy1 = max(0, int(np.floor(y1)))
        ix2 = min(w, int(np.ceil(x2)))
        iy2 = min(h, int(np.ceil(y2)))
        if ix2 > ix1 and iy2 > iy1:
            out[iy1:iy2, ix1:ix2] = value
    return out


def clear_frame_borders(
    occ: np.ndarray,
    frame_bboxes: list[tuple] | None,
    *,
    border_px: int = 6,
) -> np.ndarray:
    if not frame_bboxes:
        return occ
    out = occ.copy()
    h, w = out.shape[:2]
    b = max(1, int(border_px))
    for bb in frame_bboxes:
        x1, y1, x2, y2 = normalize_bbox(bb)
        ix1 = max(0, int(np.floor(x1)))
        iy1 = max(0, int(np.floor(y1)))
        ix2 = min(w, int(np.ceil(x2)))
        iy2 = min(h, int(np.ceil(y2)))
        out[iy1 : min(iy2, iy1 + b), ix1:ix2] = 0
        out[max(iy1, iy2 - b) : iy2, ix1:ix2] = 0
        out[iy1:iy2, ix1 : min(ix2, ix1 + b)] = 0
        out[iy1:iy2, max(ix1, ix2 - b) : ix2] = 0
    return out


def prepare_color_page(
    image_path: str | Path,
    *,
    line_art_out: str | Path | None = None,
) -> dict:
    """
    Split a color ネーム page into detect + occupy assets.

    Returns dict:
      has_color, line_art_path, line_art_bgr, fill_mask, line_ink_mask
    """
    path = Path(image_path)
    bgr = load_page_bgr(path)
    if bgr is None:
        return {"has_color": False, "line_art_path": str(path) if path.is_file() else None}

    has_color = page_has_color_fill(bgr)
    line_bgr = extract_line_art_bgr(bgr)
    fill = extract_person_fill_mask(bgr)
    line_ink = extract_line_ink_mask(bgr)

    out_path = Path(line_art_out) if line_art_out else path.with_name(path.stem + "_lines.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), line_bgr)

    return {
        "has_color": has_color,
        "line_art_path": str(out_path),
        "line_art_bgr": line_bgr,
        "fill_mask": fill,
        "line_ink_mask": line_ink,
        "bgr": bgr,
    }


def build_occupancy_color(
    fill_mask: np.ndarray,
    line_ink_mask: np.ndarray | None = None,
    face_bboxes: list[tuple] | None = None,
    frame_bboxes: list[tuple] | None = None,
    *,
    face_pad_ratio: float = 0.12,
    include_lines: bool = True,
) -> np.ndarray:
    """
    HARD occupancy from person paint (+ optional line ink) + face pads.
    Body detector boxes are not used.
    """
    occ = fill_mask.copy()
    if include_lines and line_ink_mask is not None:
        occ = np.maximum(occ, line_ink_mask)
    if face_bboxes:
        padded = face_margin_boxes(face_bboxes, pad_ratio=face_pad_ratio, pad_min=4.0)
        occ = stamp_boxes_on_mask(occ, padded)
    occ = clear_frame_borders(occ, frame_bboxes, border_px=5)
    return occ


def build_page_occupancy(
    gray: np.ndarray,
    face_bboxes: list[tuple] | None = None,
    body_bboxes: list[tuple] | None = None,
    frame_bboxes: list[tuple] | None = None,
    *,
    threshold: int = 200,
    envelope_radius: float | None = None,
    face_pad_ratio: float = 0.12,
) -> np.ndarray:
    """
    Mono fallback: ink envelope (no solid body AABB).
    Kept for B&W pages without chromatic fill.
    """
    h, w = gray.shape[:2]
    ink = (gray < int(threshold)).astype(np.uint8) * 255
    ink = clear_frame_borders(ink, frame_bboxes, border_px=4)
    if envelope_radius is None:
        envelope_radius = max(8.0, min(h, w) * 0.006)
    free = np.where(ink > 0, 0, 255).astype(np.uint8)
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    occ = ((dist <= float(envelope_radius)) | (ink > 0)).astype(np.uint8) * 255
    # light body-ROI dilate assist without filling whole AABB
    if body_bboxes:
        for bb in body_bboxes:
            x1, y1, x2, y2 = normalize_bbox(bb)
            ix1, iy1 = max(0, int(x1)), max(0, int(y1))
            ix2, iy2 = min(w, int(x2)), min(h, int(y2))
            if ix2 - ix1 < 8 or iy2 - iy1 < 8:
                continue
            crop = ink[iy1:iy2, ix1:ix2]
            k = max(3, int(min(ix2 - ix1, iy2 - iy1) * 0.05)) | 1
            k = min(k, 21)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            thick = cv2.dilate(crop, kernel, iterations=2)
            occ[iy1:iy2, ix1:ix2] = np.maximum(occ[iy1:iy2, ix1:ix2], thick)
    if face_bboxes:
        padded = face_margin_boxes(face_bboxes, pad_ratio=face_pad_ratio, pad_min=4.0)
        occ = stamp_boxes_on_mask(occ, padded)
    return clear_frame_borders(occ, frame_bboxes, border_px=6)


def build_ink_mask(
    gray: np.ndarray,
    *,
    threshold: int = 200,
    dilate_iter: int = 2,
    dilate_ksize: int = 3,
) -> np.ndarray:
    ink = (gray < int(threshold)).astype(np.uint8) * 255
    if dilate_iter <= 0:
        return ink
    radius = max(2.0, dilate_iter * dilate_ksize * 0.9)
    free = np.where(ink > 0, 0, 255).astype(np.uint8)
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    return ((dist <= radius) | (ink > 0)).astype(np.uint8) * 255


def region_ink_fraction(
    occ: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> float:
    h, w = occ.shape[:2]
    x1, y1, x2, y2 = normalize_bbox(bbox)
    ix1 = max(0, int(np.floor(x1)))
    iy1 = max(0, int(np.floor(y1)))
    ix2 = min(w, int(np.ceil(x2)))
    iy2 = min(h, int(np.ceil(y2)))
    if ix2 <= ix1 or iy2 <= iy1:
        return 1.0
    patch = occ[iy1:iy2, ix1:ix2]
    if patch.size == 0:
        return 1.0
    return float(np.mean(patch > 0))


def hits_occupancy(
    occ: np.ndarray | None,
    bbox: tuple[float, float, float, float],
    *,
    max_frac: float = 0.08,
) -> bool:
    if occ is None:
        return False
    return region_ink_fraction(occ, bbox) > max_frac


def debug_occupancy_overlay(
    base_bgr_or_gray: np.ndarray,
    occ: np.ndarray,
    out_path: str | Path,
) -> None:
    if base_bgr_or_gray.ndim == 2:
        base = cv2.cvtColor(base_bgr_or_gray, cv2.COLOR_GRAY2BGR)
    else:
        base = base_bgr_or_gray.copy()
    overlay = base.copy()
    overlay[occ > 0] = (0, 0, 255)
    mix = cv2.addWeighted(base, 0.5, overlay, 0.5, 0)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), mix)


def debug_split_layers(
    bgr: np.ndarray,
    line_bgr: np.ndarray,
    fill_mask: np.ndarray,
    out_dir: str | Path,
) -> None:
    """Save line art + fill overlay for inspection."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "layer_lines.png"), line_bgr)
    fill_vis = bgr.copy()
    fill_vis[fill_mask > 0] = (0, 0, 255)
    mix = cv2.addWeighted(bgr, 0.45, fill_vis, 0.55, 0)
    cv2.imwrite(str(out / "layer_fill.png"), mix)
