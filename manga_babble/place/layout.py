"""Build layout JSON from detections + dialogue lines.

Placement rules (Phase A):
  - Bubble size from text metrics (not free-space max)
  - Same panel: slots ① top-right → ② top-left → ③ bottom-left
  - panel_index N → Nth frame in manga reading order (R→L, T→B)
  - frame_id explicit always wins; no face required
"""

from __future__ import annotations

from typing import Any

from manga_babble import SCHEMA_VERSION
from manga_babble.place.candidates import size_from_text
from manga_babble.schema import ensure_line_ids, normalize_bbox
from manga_babble.tone.resolve import is_page_margin_line, resolve_style

# Slot anchors inside a frame (relative 0–1): top-right, top-left, bottom-left
_SLOTS = (
    (0.78, 0.22),  # ① 右上
    (0.22, 0.22),  # ② 左上
    (0.22, 0.72),  # ③ 左下
    (0.78, 0.72),  # ④ 右下（4本目以降）
)


def _det_list(detections: dict[str, Any], key: str) -> list[dict[str, Any]]:
    block = detections.get("detections") or detections
    return list(block.get(key) or [])


def _bbox_of(item: dict[str, Any]) -> tuple[float, float, float, float]:
    return normalize_bbox(item["bbox"])


def _center(bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def _contains(frame_bbox, point) -> bool:
    x1, y1, x2, y2 = frame_bbox
    px, py = point
    return x1 <= px <= x2 and y1 <= py <= y2


def _overlaps(a, b, pad: float = 4.0) -> bool:
    return not (
        a[2] + pad <= b[0]
        or a[0] - pad >= b[2]
        or a[3] + pad <= b[1]
        or a[1] - pad >= b[3]
    )


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def frames_in_reading_order(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manga page order: top→bottom, then right→left within a band."""
    if not frames:
        return []
    items = list(frames)
    # Band by vertical center
    items.sort(key=lambda f: _center(_bbox_of(f))[1])
    bands: list[list[dict]] = []
    band_tol = None
    for f in items:
        cy = _center(_bbox_of(f))[1]
        h = _bbox_of(f)[3] - _bbox_of(f)[1]
        tol = max(40.0, h * 0.35)
        if band_tol is None:
            bands.append([f])
            band_tol = (cy, tol)
            continue
        bcy, bt = band_tol
        if abs(cy - bcy) <= max(bt, tol):
            bands[-1].append(f)
            # update band center
            band_tol = (
                sum(_center(_bbox_of(x))[1] for x in bands[-1]) / len(bands[-1]),
                bt,
            )
        else:
            bands.append([f])
            band_tol = (cy, tol)
    ordered: list[dict] = []
    for band in bands:
        # right to left
        band.sort(key=lambda f: _center(_bbox_of(f))[0], reverse=True)
        ordered.extend(band)
    return ordered


def _resolve_frame(
    line: dict[str, Any],
    frames: list[dict[str, Any]],
    frames_ordered: list[dict[str, Any]],
    page_bbox,
) -> tuple[tuple[float, float, float, float], str | None]:
    # Explicit frame_id
    if line.get("frame_id"):
        for f in frames:
            if f.get("id") == line["frame_id"]:
                return _bbox_of(f), f.get("id")
    # panel_index 1-based reading order
    pi = line.get("panel_index")
    if pi is not None and frames_ordered:
        try:
            idx = int(pi) - 1
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(frames_ordered):
            f = frames_ordered[idx]
            return _bbox_of(f), f.get("id")
    if frames_ordered:
        f = frames_ordered[0]
        return _bbox_of(f), f.get("id")
    return page_bbox, None


def _match_face(
    line: dict[str, Any],
    faces: list[dict[str, Any]],
    frame_bbox,
    frame_id: str | None,
) -> tuple[dict[str, Any] | None, tuple[float, float, float, float] | None]:
    speaker = line.get("speaker")
    in_frame = []
    for f in faces:
        bb = _bbox_of(f)
        if frame_id and f.get("frame_id") == frame_id:
            in_frame.append(f)
        elif _contains(frame_bbox, _center(bb)):
            in_frame.append(f)
    pool = in_frame or []

    if speaker:
        for f in faces:
            if f.get("speaker") == speaker or f.get("id") == speaker:
                # Prefer if in this frame; still allow explicit id
                return f, _bbox_of(f)
        # name match only among in-frame faces — skip global wrong-panel faces
        for f in pool:
            if f.get("id") == speaker:
                return f, _bbox_of(f)

    if pool:
        return pool[0], _bbox_of(pool[0])
    return None, None


def _slot_bbox(
    frame_bbox,
    slot_xy: tuple[float, float],
    half_w: float,
    half_h: float,
) -> tuple[float, float, float, float]:
    fx1, fy1, fx2, fy2 = frame_bbox
    fw, fh = fx2 - fx1, fy2 - fy1
    sx, sy = slot_xy
    cx = fx1 + fw * sx
    cy = fy1 + fh * sy
    # keep inside frame
    half_w = min(half_w, fw * 0.45)
    half_h = min(half_h, fh * 0.45)
    bb = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return (
        max(fx1, bb[0]),
        max(fy1, bb[1]),
        min(fx2, bb[2]),
        min(fy2, bb[3]),
    )


def _nudge_away_from(
    bb,
    blockers: list[tuple],
    frame_bbox,
    step: float = 12.0,
) -> tuple[float, float, float, float]:
    """Nudge bbox within frame to reduce overlap with blockers."""
    fx1, fy1, fx2, fy2 = frame_bbox
    x1, y1, x2, y2 = bb
    w, h = x2 - x1, y2 - y1
    for _ in range(24):
        hit = None
        for bl in blockers:
            if _overlaps((x1, y1, x2, y2), bl):
                hit = bl
                break
        if hit is None:
            break
        # push away from blocker center
        bcx, bcy = _center(hit)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = cx - bcx, cy - bcy
        if abs(dx) < 1 and abs(dy) < 1:
            dx = 1.0
        norm = (dx * dx + dy * dy) ** 0.5
        dx, dy = dx / norm * step, dy / norm * step
        cx, cy = cx + dx, cy + dy
        x1, y1 = cx - w / 2, cy - h / 2
        x2, y2 = cx + w / 2, cy + h / 2
        x1 = max(fx1, min(x1, fx2 - w))
        y1 = max(fy1, min(y1, fy2 - h))
        x2, y2 = x1 + w, y1 + h
    return (x1, y1, x2, y2)


def _union_frames(frames: list[dict[str, Any]], page_bbox):
    if not frames:
        return page_bbox
    boxes = [_bbox_of(f) for f in frames]
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _place_page_margin(
    text: str,
    page_w: float,
    page_h: float,
    frames: list[dict[str, Any]],
    placed: list[tuple],
) -> tuple[tuple[float, float, float, float], float]:
    n = max(1, len(text.replace("\n", "")))
    strip_w = max(36.0, min(page_w * 0.06, 72.0))
    char_h = max(14.0, min(22.0, page_h / 90.0))
    strip_h = min(page_h * 0.45, max(80.0, n * char_h * 1.15))
    content = _union_frames(frames, (0, 0, page_w, page_h))
    pad = 8.0
    candidates = []
    left_gap = content[0] - 0
    right_gap = page_w - content[2]
    if left_gap >= strip_w * 0.5:
        x2 = max(strip_w, content[0] - pad)
        x1 = max(0.0, x2 - strip_w)
        y1 = min(page_h - strip_h, max(0.0, content[1] + (content[3] - content[1]) * 0.35))
        candidates.append((x1, y1, x2, y1 + strip_h))
    if right_gap >= strip_w * 0.5:
        x1 = min(page_w - strip_w, content[2] + pad)
        x2 = min(page_w, x1 + strip_w)
        y1 = min(page_h - strip_h, max(0.0, content[1] + (content[3] - content[1]) * 0.35))
        candidates.append((x1, y1, x2, y1 + strip_h))
    if not candidates:
        candidates.append((pad, page_h * 0.4, pad + strip_w, page_h * 0.4 + strip_h))
    for bb in candidates:
        if not any(_overlaps(bb, p) for p in placed):
            return bb, 1.0
    return candidates[0], 0.5


def build_layout(
    detections_doc: dict[str, Any],
    lines_doc: dict[str, Any],
    *,
    page_width: int | None = None,
    page_height: int | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    page = dict(detections_doc.get("page") or lines_doc.get("page") or {})
    w = page_width or page.get("width")
    h = page_height or page.get("height")
    if not w or not h:
        raise ValueError("page width/height required for layout")
    w, h = int(w), int(h)
    page["width"] = w
    page["height"] = h
    page_bbox = (0.0, 0.0, float(w), float(h))

    frames = _det_list(detections_doc, "frames")
    faces = _det_list(detections_doc, "faces")
    bodies = _det_list(detections_doc, "bodies")
    frames_ordered = frames_in_reading_order(frames)

    lines = ensure_line_ids(list(lines_doc.get("lines") or []))
    lines = sorted(lines, key=lambda x: (x.get("order", 0), x.get("id", "")))

    # Count slot index per frame for same-panel left/right split
    slot_counter: dict[str, int] = {}
    placed_bboxes: list[tuple] = []
    bubbles: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        tone, shape, tone_source = resolve_style(line)
        margin = is_page_margin_line(line)
        meta_extra: dict[str, Any] = {"shape": shape}

        if margin:
            bb, score = _place_page_margin(
                str(line["text"]), float(w), float(h), frames, placed_bboxes
            )
            face_bb = None
            face_id = None
            frame_id = None
            tone = "narration"
            shape = shape if shape in ("rect", "v-rect", "tall-rect") else "v-rect"
            meta_extra["shape"] = shape
            meta_extra["placement"] = "page_margin"
        else:
            frame_bbox, frame_id = _resolve_frame(
                line, frames, frames_ordered, page_bbox
            )
            fid_key = frame_id or "_page"
            slot_i = slot_counter.get(fid_key, 0)
            slot_counter[fid_key] = slot_i + 1
            slot_xy = _SLOTS[slot_i % len(_SLOTS)]

            min_hw, min_hh, max_hw, max_hh = size_from_text(str(line["text"]), w, h)
            half_w = min(min_hw, max_hw)
            half_h = min(min_hh, max_hh)

            bb = _slot_bbox(frame_bbox, slot_xy, half_w, half_h)

            # Blockers: faces/bodies in frame + already placed
            blockers = []
            for f in faces:
                fbb = _bbox_of(f)
                if _contains(frame_bbox, _center(fbb)) or f.get("frame_id") == frame_id:
                    blockers.append(fbb)
            for b in bodies:
                bbb = _bbox_of(b)
                if _contains(frame_bbox, _center(bbb)):
                    blockers.append(bbb)
            blockers.extend(placed_bboxes)

            bb = _nudge_away_from(bb, blockers, frame_bbox)
            score = float(len(_SLOTS) - (slot_i % len(_SLOTS)))

            face_obj, face_bb = _match_face(line, faces, frame_bbox, frame_id)
            face_id = face_obj.get("id") if face_obj else None
            if tone == "narration":
                face_bb = None
                face_id = None

            meta_extra["slot_index"] = slot_i % len(_SLOTS)

        placed_bboxes.append(bb)
        bubbles.append(
            {
                "id": f"bub_{line['id']}",
                "line_id": line["id"],
                "text": str(line["text"]),
                "tone": tone,
                "order": int(line.get("order", i)),
                "bubble_bbox": [round(v, 2) for v in bb],
                "speaker_face_id": face_id,
                "speaker_face_bbox": (
                    [round(v, 2) for v in face_bb] if face_bb is not None else None
                ),
                "frame_id": frame_id,
                "score": round(score, 3),
                "meta": {
                    "tone_source": tone_source,
                    "char_count": len(str(line["text"]).replace("\n", "")),
                    "seed": seed + i,
                    **meta_extra,
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "page": page,
        "bubbles": bubbles,
        "options": dict(lines_doc.get("options") or {}),
        "meta": {
            "frames_reading_order": [f.get("id") for f in frames_ordered],
        },
    }
