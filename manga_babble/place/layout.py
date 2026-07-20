"""Build layout JSON from detections + dialogue lines.

Placement rules:
  - Bubble size from text metrics (not free-space max)
  - Same panel: try slots ① top-right → ② top-left → ③ bottom-left → ④
  - Face bboxes are hard-avoid; body blockers are clipped to the frame
  - Slot failure → free-space distance-transform candidates
  - panel_index N → Nth frame in manga reading order (R→L, T→B)
  - frame_id explicit always wins; no face required
"""

from __future__ import annotations

from typing import Any

from manga_babble import SCHEMA_VERSION
from manga_babble.place.candidates import compute_bubble_candidates, size_from_text
from manga_babble.schema import ensure_line_ids, normalize_bbox
from manga_babble.text.breaks import split_text_to_chunks
from manga_babble.tone.resolve import is_page_margin_line, resolve_style

# Slot anchors inside a frame (relative 0–1): top-right, top-left, bottom-left, bottom-right
_SLOTS = (
    (0.78, 0.22),  # ① 右上
    (0.22, 0.22),  # ② 左上
    (0.22, 0.72),  # ③ 左下
    (0.78, 0.72),  # ④ 右下
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


def _intersection_area(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def _clip_to_frame(bb, frame_bbox):
    """Intersection of bb with frame; None if empty."""
    x1 = max(bb[0], frame_bbox[0])
    y1 = max(bb[1], frame_bbox[1])
    x2 = min(bb[2], frame_bbox[2])
    y2 = min(bb[3], frame_bbox[3])
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def frames_in_reading_order(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manga page order: top→bottom, then right→left within a band."""
    if not frames:
        return []
    items = list(frames)
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
            band_tol = (
                sum(_center(_bbox_of(x))[1] for x in bands[-1]) / len(bands[-1]),
                bt,
            )
        else:
            bands.append([f])
            band_tol = (cy, tol)
    ordered: list[dict] = []
    for band in bands:
        band.sort(key=lambda f: _center(_bbox_of(f))[0], reverse=True)
        ordered.extend(band)
    return ordered


def _resolve_frame(
    line: dict[str, Any],
    frames: list[dict[str, Any]],
    frames_ordered: list[dict[str, Any]],
    page_bbox,
) -> tuple[tuple[float, float, float, float], str | None]:
    if line.get("frame_id"):
        for f in frames:
            if f.get("id") == line["frame_id"]:
                return _bbox_of(f), f.get("id")
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


def _faces_in_frame(
    faces: list[dict[str, Any]],
    frame_bbox,
    frame_id: str | None,
) -> list[dict[str, Any]]:
    out = []
    for f in faces:
        bb = _bbox_of(f)
        if frame_id and f.get("frame_id") == frame_id:
            out.append(f)
        elif _contains(frame_bbox, _center(bb)):
            out.append(f)
    return out


def _match_face(
    line: dict[str, Any],
    faces: list[dict[str, Any]],
    frame_bbox,
    frame_id: str | None,
    *,
    slot_index: int = 0,
    bubble_bbox=None,
) -> tuple[dict[str, Any] | None, tuple[float, float, float, float] | None]:
    """
    Pick speaker face for tail / proximity.

    Priority:
      1) explicit face id or speaker tag on detection
      2) among in-frame faces: nearest to bubble (or slot preference R→L)
      3) single face only for first line in panel (slot 0); later lines → no face
         (avoid all tails pointing at the only detected face)
    """
    pool = _faces_in_frame(faces, frame_bbox, frame_id)
    speaker = line.get("speaker")
    explicit = line.get("face_id") or line.get("speaker_face_id")

    if explicit:
        for f in faces:
            if f.get("id") == explicit:
                # Prefer in-frame; allow global only if explicit id
                return f, _bbox_of(f)

    if speaker:
        # In-frame speaker name match only (no global wrong-panel pull)
        for f in pool:
            if f.get("speaker") == speaker or f.get("id") == speaker:
                return f, _bbox_of(f)
        for f in faces:
            if f.get("speaker") == speaker and f.get("id") == speaker:
                if frame_id and f.get("frame_id") == frame_id:
                    return f, _bbox_of(f)

    if not pool:
        return None, None

    if len(pool) == 1:
        # Only assign the lone face to the first bubble in the panel
        if slot_index == 0:
            return pool[0], _bbox_of(pool[0])
        return None, None

    # Multiple faces: R→L vs slot (0 = rightmost). If bubble is clearly
    # nearer another face, switch (placement may have moved).
    pool_rtl = sorted(pool, key=lambda f: _center(_bbox_of(f))[0], reverse=True)
    idx = min(slot_index, len(pool_rtl) - 1)
    chosen = pool_rtl[idx]
    if bubble_bbox is not None:
        bcx, bcy = _center(bubble_bbox)

        def d2(f):
            fc = _center(_bbox_of(f))
            return (fc[0] - bcx) ** 2 + (fc[1] - bcy) ** 2

        nearest = min(pool, key=d2)
        # Switch only if nearest is substantially closer than slot pick
        if nearest is not chosen and d2(nearest) * 2.25 < d2(chosen):
            chosen = nearest
    return chosen, _bbox_of(chosen)


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
    hard_faces: list[tuple] | None = None,
) -> tuple[float, float, float, float]:
    """Nudge bbox within frame to reduce overlap with blockers."""
    fx1, fy1, fx2, fy2 = frame_bbox
    x1, y1, x2, y2 = bb
    w, h = x2 - x1, y2 - y1
    hard_faces = hard_faces or []
    for _ in range(32):
        hit = None
        # Prefer escaping faces first
        for bl in hard_faces:
            if _overlaps((x1, y1, x2, y2), bl, pad=2.0):
                hit = bl
                break
        if hit is None:
            for bl in blockers:
                if _overlaps((x1, y1, x2, y2), bl):
                    hit = bl
                    break
        if hit is None:
            break
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


def _face_blockers(
    faces: list[dict[str, Any]],
    frame_bbox,
    frame_id: str | None,
) -> list[tuple]:
    boxes = []
    for f in _faces_in_frame(faces, frame_bbox, frame_id):
        clipped = _clip_to_frame(_bbox_of(f), frame_bbox)
        if clipped is not None:
            boxes.append(clipped)
    return boxes


def _body_blockers_clipped(
    bodies: list[dict[str, Any]],
    frame_bbox,
    frame_id: str | None,
) -> list[tuple]:
    """Body occupancy clipped to frame (spanning bodies don't flood the panel)."""
    boxes = []
    for b in bodies:
        bb = _bbox_of(b)
        clipped = _clip_to_frame(bb, frame_bbox)
        if clipped is None:
            continue
        # Include if assigned to this frame, center in frame, or meaningful overlap
        ia = _intersection_area(bb, frame_bbox)
        if ia <= 0:
            continue
        frac = ia / max(_area(bb), 1.0)
        in_frame = (
            (frame_id and b.get("frame_id") == frame_id)
            or _contains(frame_bbox, _center(bb))
            or frac >= 0.15
        )
        if in_frame:
            boxes.append(clipped)
    return boxes


def _overlaps_any_face(bb, face_boxes: list[tuple], pad: float = 2.0) -> bool:
    return any(_overlaps(bb, fb, pad=pad) for fb in face_boxes)


def _dist2(a, b) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _place_bubble_in_frame(
    frame_bbox,
    half_w: float,
    half_h: float,
    max_hw: float,
    max_hh: float,
    faces: list[dict[str, Any]],
    bodies: list[dict[str, Any]],
    frame_id: str | None,
    placed: list[tuple],
    preferred_slot: int,
    prefer_near: tuple[float, float] | None = None,
) -> tuple[tuple[float, float, float, float], float, dict[str, Any]]:
    """
    Place bubble avoiding faces hard; bodies soft (clipped).
    Among valid candidates, prefer preferred slot then near prefer_near (speaker).
    Returns (bbox, score, meta).
    """
    face_boxes = _face_blockers(faces, frame_bbox, frame_id)
    body_boxes = _body_blockers_clipped(bodies, frame_bbox, frame_id)
    soft_blockers = list(body_boxes) + list(placed)
    pref_si = preferred_slot % len(_SLOTS)
    # Anchor: speaker face / prefer_near, else preferred slot center
    if prefer_near is None:
        prefer_near = _center(_slot_bbox(frame_bbox, _SLOTS[pref_si], half_w, half_h))

    def cand_rank(bb, mode: str, si: int) -> tuple:
        """Lower is better."""
        cx, cy = _center(bb)
        # Keep some distance from face center (don't hug face edge)
        face_pen = 0.0
        for fb in face_boxes:
            fcx, fcy = _center(fb)
            d = _dist2((cx, cy), (fcx, fcy)) ** 0.5
            # Ideal: not overlapping, moderately near for tail
            if d < 40:
                face_pen += 5000
            elif d > 400:
                face_pen += (d - 400) * 0.5
        placed_pen = sum(
            _intersection_area(bb, p) for p in placed
        )
        slot_pen = 0 if si == pref_si else 200 * abs(si - pref_si)
        mode_pen = {"slot": 0, "free_space": 60, "fallback_faces_only": 120}.get(
            mode, 50
        )
        near_pen = _dist2((cx, cy), prefer_near) ** 0.5
        # Prefer preferred-slot side of frame (x)
        side_pen = 0.0
        if prefer_near is not None:
            # Reward being on the same half as prefer_near
            mid_x = (frame_bbox[0] + frame_bbox[2]) / 2
            if (prefer_near[0] - mid_x) * (cx - mid_x) < 0:
                side_pen = 150
        return (placed_pen, mode_pen + slot_pen + face_pen + side_pen + near_pen * 0.2)

    def collect(hw: float, hh: float) -> list[tuple]:
        found: list[tuple] = []
        for si in range(len(_SLOTS)):
            cand = _slot_bbox(frame_bbox, _SLOTS[si], hw, hh)
            nudged = _nudge_away_from(
                cand, soft_blockers + face_boxes, frame_bbox, hard_faces=face_boxes
            )
            if _overlaps_any_face(nudged, face_boxes):
                continue
            if any(_intersection_area(nudged, p) > _area(nudged) * 0.55 for p in placed):
                continue
            found.append((nudged, "slot", si))

        # Free-space: faces + placed are hard; body is soft (omit from mask)
        # so dialogue can sit over clothing when needed — never over faces.
        cands = compute_bubble_candidates(
            frame_bbox,
            [],
            face_boxes,
            extra_bboxes=placed,
            top_k=8,
            min_half_w=hw,
            min_half_h=hh,
            max_half_w=max_hw,
            max_half_h=max_hh,
            prefer_text_size=True,
        )
        for c in cands:
            bb = tuple(float(x) for x in c["bbox"])
            if _overlaps_any_face(bb, face_boxes):
                continue
            # Soft body penalty applied via ranking only
            found.append((bb, "free_space", pref_si))
        return found

    scales = (1.0, 0.88, 0.76, 0.65)
    for sc in scales:
        hw = max(24.0, half_w * sc)
        hh = max(20.0, half_h * sc)
        opts = collect(hw, hh)
        if not opts:
            continue
        opts.sort(key=lambda t: cand_rank(t[0], t[1], t[2]))
        bb, mode, si = opts[0]
        return bb, float(10 - sc * 2), {
            "placement_mode": mode,
            "slot_index": si,
            "overlap_face": False,
            "size_scale": sc,
        }

    # Last resort
    hw, hh = max(24.0, half_w * 0.6), max(20.0, half_h * 0.6)
    bb = _slot_bbox(frame_bbox, _SLOTS[pref_si], hw, hh)
    bb = _nudge_away_from(
        bb, soft_blockers + face_boxes, frame_bbox, hard_faces=face_boxes
    )
    still_face = _overlaps_any_face(bb, face_boxes)
    if still_face:
        cands = compute_bubble_candidates(
            frame_bbox,
            [],
            face_boxes,
            extra_bboxes=placed,
            top_k=8,
            min_half_w=hw,
            min_half_h=hh,
            max_half_w=max_hw,
            max_half_h=max_hh,
            prefer_text_size=True,
        )
        ranked = []
        for c in cands:
            cand = tuple(float(x) for x in c["bbox"])
            if not _overlaps_any_face(cand, face_boxes):
                ranked.append(cand)
        if ranked:
            ranked.sort(key=lambda b: cand_rank(b, "fallback_faces_only", pref_si))
            return ranked[0], 0.4, {
                "placement_mode": "fallback_faces_only",
                "slot_index": pref_si,
                "overlap_face": False,
                "size_scale": 0.6,
            }
    return bb, 0.2, {
        "placement_mode": "fallback",
        "slot_index": pref_si,
        "overlap_face": still_face,
        "size_scale": 0.6,
    }


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
        y1 = min(
            page_h - strip_h,
            max(0.0, content[1] + (content[3] - content[1]) * 0.35),
        )
        candidates.append((x1, y1, x2, y1 + strip_h))
    if right_gap >= strip_w * 0.5:
        x1 = min(page_w - strip_w, content[2] + pad)
        x2 = min(page_w, x1 + strip_w)
        y1 = min(
            page_h - strip_h,
            max(0.0, content[1] + (content[3] - content[1]) * 0.35),
        )
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

            # Size from the same chunks render will use (agent　 /  structural)
            text_chunks = split_text_to_chunks(
                str(line["text"]),
                options=lines_doc.get("options"),
                speaker=line.get("speaker"),
                line_meta=line.get("meta") if isinstance(line.get("meta"), dict) else None,
            )
            min_hw, min_hh, max_hw, max_hh = size_from_text(
                str(line["text"]), w, h, shape=shape, chunks=text_chunks
            )
            half_w = min(min_hw, max_hw)
            half_h = min(min_hh, max_hh)
            meta_extra["text_chunks"] = text_chunks
            meta_extra["n_cols"] = len(text_chunks)

            # Pre-match face for proximity bias (may refine after place)
            pre_face, pre_fbb = _match_face(
                line,
                faces,
                frame_bbox,
                frame_id,
                slot_index=slot_i,
                bubble_bbox=None,
            )
            prefer_near = _center(pre_fbb) if pre_fbb is not None else None

            bb, score, place_meta = _place_bubble_in_frame(
                frame_bbox,
                half_w,
                half_h,
                max_hw,
                max_hh,
                faces,
                bodies,
                frame_id,
                placed_bboxes,
                preferred_slot=slot_i,
                prefer_near=prefer_near,
            )
            meta_extra.update(place_meta)

            face_obj, face_bb = _match_face(
                line,
                faces,
                frame_bbox,
                frame_id,
                slot_index=slot_i,
                bubble_bbox=bb,
            )
            # Keep pre-match for lone-face first line if post-match agrees / empty
            if face_obj is None and pre_face is not None and slot_i == 0:
                face_obj, face_bb = pre_face, pre_fbb
            face_id = face_obj.get("id") if face_obj else None
            if tone == "narration":
                face_bb = None
                face_id = None

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
