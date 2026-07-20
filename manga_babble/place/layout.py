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
from manga_babble.place.aim import (
    aims_in_frame,
    collect_aims,
    hard_avoid_boxes,
    resolve_aim,
)
from manga_babble.place.candidates import compute_bubble_candidates, size_from_text
from manga_babble.place.occupancy import (
    build_occupancy_color,
    build_page_occupancy,
    hits_occupancy,
    load_page_gray,
    page_has_color_fill,
    prepare_color_page,
)
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
# Keep bubbles off the panel border (manga gutters / 枠線)
_FRAME_EDGE_PAD_MIN = 16.0
_FRAME_EDGE_PAD_RATIO = 0.045


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


def _frame_edge_pad(frame_bbox) -> float:
    fx1, fy1, fx2, fy2 = frame_bbox
    fw, fh = max(1.0, fx2 - fx1), max(1.0, fy2 - fy1)
    return max(_FRAME_EDGE_PAD_MIN, min(fw, fh) * _FRAME_EDGE_PAD_RATIO)


def _inset_frame(frame_bbox, pad: float | None = None):
    """Usable inner rect — bubbles should stay inside this."""
    fx1, fy1, fx2, fy2 = frame_bbox
    p = _frame_edge_pad(frame_bbox) if pad is None else pad
    ix1, iy1 = fx1 + p, fy1 + p
    ix2, iy2 = fx2 - p, fy2 - p
    if ix2 <= ix1 + 8 or iy2 <= iy1 + 8:
        # Tiny panel: smaller pad
        p = min(p, max(4.0, min(fx2 - fx1, fy2 - fy1) * 0.08))
        ix1, iy1 = fx1 + p, fy1 + p
        ix2, iy2 = fx2 - p, fy2 - p
    if ix2 <= ix1 or iy2 <= iy1:
        return frame_bbox
    return (ix1, iy1, ix2, iy2)


def _clamp_bb_to_frame(bb, frame_bbox, pad: float | None = None):
    """Clamp bubble into inset frame, preserving size when possible."""
    inner = _inset_frame(frame_bbox, pad)
    ix1, iy1, ix2, iy2 = inner
    x1, y1, x2, y2 = bb
    w, h = x2 - x1, y2 - y1
    iw, ih = ix2 - ix1, iy2 - iy1
    if w > iw:
        # Shrink-to-fit width
        cx = (x1 + x2) / 2
        x1 = max(ix1, min(cx - iw / 2, ix2 - iw))
        x2 = x1 + min(w, iw)
    else:
        if x1 < ix1:
            x1, x2 = ix1, ix1 + w
        if x2 > ix2:
            x2, x1 = ix2, ix2 - w
    if h > ih:
        cy = (y1 + y2) / 2
        y1 = max(iy1, min(cy - ih / 2, iy2 - ih))
        y2 = y1 + min(h, ih)
    else:
        if y1 < iy1:
            y1, y2 = iy1, iy1 + h
        if y2 > iy2:
            y2, y1 = iy2, iy2 - h
    return (x1, y1, x2, y2)


def _slot_bbox(
    frame_bbox,
    slot_xy: tuple[float, float],
    half_w: float,
    half_h: float,
) -> tuple[float, float, float, float]:
    # Place within inset so slots never sit on the 枠線
    ix1, iy1, ix2, iy2 = _inset_frame(frame_bbox)
    fw, fh = ix2 - ix1, iy2 - iy1
    sx, sy = slot_xy
    cx = ix1 + fw * sx
    cy = iy1 + fh * sy
    half_w = min(half_w, fw * 0.45)
    half_h = min(half_h, fh * 0.45)
    bb = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return _clamp_bb_to_frame(bb, frame_bbox)


def _center_bbox(
    frame_bbox,
    half_w: float,
    half_h: float,
    rel_y: float = 0.38,
) -> tuple[float, float, float, float]:
    """Bubble centered in frame (slightly upper) — for face-less panels."""
    ix1, iy1, ix2, iy2 = _inset_frame(frame_bbox)
    fw, fh = ix2 - ix1, iy2 - iy1
    half_w = min(half_w, fw * 0.45)
    half_h = min(half_h, fh * 0.45)
    cx = (ix1 + ix2) / 2
    cy = iy1 + fh * rel_y
    bb = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return _clamp_bb_to_frame(bb, frame_bbox)


def _nudge_away_from(
    bb,
    blockers: list[tuple],
    frame_bbox,
    step: float = 12.0,
    hard_faces: list[tuple] | None = None,
) -> tuple[float, float, float, float]:
    """Nudge bbox within inset frame to reduce overlap with blockers."""
    ix1, iy1, ix2, iy2 = _inset_frame(frame_bbox)
    x1, y1, x2, y2 = bb
    w, h = x2 - x1, y2 - y1
    hard_faces = hard_faces or []
    for _ in range(32):
        hit = None
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
        # Stay inside inset
        x1 = max(ix1, min(x1, ix2 - w))
        y1 = max(iy1, min(y1, iy2 - h))
        x2, y2 = x1 + w, y1 + h
    return _clamp_bb_to_frame((x1, y1, x2, y2), frame_bbox)


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


def _overlaps_any_hard(bb, hard_boxes: list[tuple], pad: float = 4.0) -> bool:
    """True if bubble intersects face or body (blue) hard zones."""
    return any(_overlaps(bb, hb, pad=pad) for hb in hard_boxes)


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
    shape: str = "ellipse",
    hard_boxes: list[tuple] | None = None,
    page_occupancy=None,
) -> tuple[tuple[float, float, float, float], float, dict[str, Any]]:
    """
    Place bubble inside green frame inset.

    HARD occupancy:
      - padded face / aim boxes (red)
      - pixel ink mask (dilated lines = person-fill assist) when page_occupancy set
    Body AABB is NOT solid-filled when ink is available (white-in-blue stays free).
    """
    face_boxes = (
        list(hard_boxes)
        if hard_boxes is not None
        else _face_blockers(faces, frame_bbox, frame_id)
    )
    body_boxes = _body_blockers_clipped(bodies, frame_bbox, frame_id)
    use_ink = page_occupancy is not None
    # Without ink, fall back to body AABB hard (legacy)
    hard_boxes_geom = list(face_boxes) + ([] if use_ink else list(body_boxes))
    soft_blockers = list(placed)
    pref_si = preferred_slot % len(_SLOTS)
    shape_l = (shape or "ellipse").replace("_", "-")
    is_shout = shape_l in ("jagged", "giza") or shape_l == "shout"
    is_narration = shape_l in ("v-rect", "tall-rect", "rect") or shape_l == "narration"
    if prefer_near is None:
        prefer_near = _center(_slot_bbox(frame_bbox, _SLOTS[pref_si], half_w, half_h))

    def is_blocked(bb, pad: float = 4.0) -> bool:
        if _overlaps_any_hard(bb, hard_boxes_geom, pad=pad):
            return True
        # Slightly tolerant: slot probes often graze pink shoulder / face pad
        if use_ink and hits_occupancy(page_occupancy, bb, max_frac=0.10):
            return True
        return False

    def edge_pen(bb) -> float:
        inner = _inset_frame(frame_bbox)
        pen = 0.0
        if (
            bb[0] < inner[0] - 1
            or bb[1] < inner[1] - 1
            or bb[2] > inner[2] + 1
            or bb[3] > inner[3] + 1
        ):
            pen += 800
        pad = _frame_edge_pad(frame_bbox)
        for d in (
            bb[0] - frame_bbox[0],
            bb[1] - frame_bbox[1],
            frame_bbox[2] - bb[2],
            frame_bbox[3] - bb[3],
        ):
            if d < pad:
                pen += (pad - d) * 8
        return pen

    def restore_size(bb, hw: float, hh: float):
        cx, cy = _center(bb)
        expanded = _clamp_bb_to_frame((cx - hw, cy - hh, cx + hw, cy + hh), frame_bbox)
        if is_blocked(expanded, pad=4.0):
            if not is_blocked(bb, pad=4.0):
                return bb
        return expanded

    # Preferred manga slot anchor (TR for first line, etc.)
    slot_anchor = _center(_slot_bbox(frame_bbox, _SLOTS[pref_si], half_w, half_h))
    faceless = not face_boxes and not is_narration

    def face_margin_pen(bb) -> float:
        """Moderate distance from face — not glued, not banished to far corner."""
        if not face_boxes:
            return 0.0
        pen = 0.0
        cx, cy = _center(bb)
        for fb in face_boxes:
            fcx, fcy = _center(fb)
            d = _dist2((cx, cy), (fcx, fcy)) ** 0.5
            fh = max(1.0, fb[3] - fb[1])
            # sweet band: ~0.6–1.8 face-heights away
            if d < fh * 0.55:
                pen += 900
            elif d < fh * 0.85:
                pen += 250
            elif d > fh * 3.5:
                pen += (d - fh * 3.5) * 0.8
        return pen

    def cand_rank(bb, mode: str, si: int) -> tuple:
        cx, cy = _center(bb)
        placed_pen = sum(_intersection_area(bb, p) for p in placed)
        # Face-less panels: center first (logo / icon panels)
        if faceless:
            if mode == "center":
                mode_pen, slot_pen = 0, 0
            elif mode == "slot":
                mode_pen, slot_pen = 120, abs(si) * 25
            else:
                mode_pen, slot_pen = 160, 0
        elif mode == "slot":
            mode_pen = 0
            order = [(pref_si + k) % len(_SLOTS) for k in range(len(_SLOTS))]
            try:
                slot_pen = order.index(si) * 35
            except ValueError:
                slot_pen = 100
        elif mode == "center":
            mode_pen, slot_pen = 90, 0
        else:
            # free_space is fallback — still prefer near preferred slot (TR…)
            mode_pen, slot_pen = 80, 0
        if is_narration and mode == "center":
            mode_pen = 500
        # Placement pull = preferred manga slot (TR→…), NOT face center.
        # Face only hard-avoids + face_margin_pen; tails aim at face separately.
        slot_pull = _dist2((cx, cy), slot_anchor) ** 0.5
        near_pen = _dist2((cx, cy), prefer_near) ** 0.5 if prefer_near else 0.0
        side_pen = 0.0
        mid_x = (frame_bbox[0] + frame_bbox[2]) / 2
        # Keep bubble on the preferred-slot side of the panel
        if (slot_anchor[0] - mid_x) * (cx - mid_x) < 0:
            side_pen = 320
        # Prefer upper area for early slots (① TR, ② TL) — manga entry from top
        y_pen = 0.0
        if pref_si in (0, 1):
            fy1, fy2 = frame_bbox[1], frame_bbox[3]
            rel_y = (cy - fy1) / max(1.0, fy2 - fy1)
            if rel_y > 0.38:
                y_pen = (rel_y - 0.38) * 900  # strong: ん？ must not sink
            if rel_y > 0.62:
                y_pen += (rel_y - 0.62) * 500
        size_pen = 0.0
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        if bw < half_w * 1.6:
            size_pen += (half_w * 2 - bw) * 0.8
        if bh < half_h * 1.6:
            size_pen += (half_h * 2 - bh) * 0.8
        total = (
            mode_pen
            + slot_pen
            + side_pen
            + near_pen * 0.08
            + slot_pull * 0.85
            + face_margin_pen(bb)
            + edge_pen(bb)
            + y_pen
            + size_pen
        )
        return (placed_pen, total)

    def collect(hw: float, hh: float) -> list[tuple]:
        found: list[tuple] = []
        nudge_hard = hard_boxes_geom

        def _try_add(bb, mode: str, si: int) -> None:
            bb = restore_size(bb, hw, hh)
            if is_blocked(bb, pad=4.0):
                return
            if any(_intersection_area(bb, p) > _area(bb) * 0.55 for p in placed):
                return
            found.append((bb, mode, si))

        for k in range(len(_SLOTS)):
            si = (pref_si + k) % len(_SLOTS)
            cand = _slot_bbox(frame_bbox, _SLOTS[si], hw, hh)
            nudged = _nudge_away_from(
                cand, soft_blockers + nudge_hard, frame_bbox, hard_faces=nudge_hard
            )
            _try_add(nudged, "slot", si)

        # Preferred-slot micro-probes (higher / tighter to corner) when TR/TL
        # standard slot grazes face pad or pink fill — e.g. small 「ん？」
        if pref_si in (0, 1) and not any(m == "slot" and si == pref_si for _, m, si in found):
            if pref_si == 0:
                probes = ((0.86, 0.14), (0.78, 0.14), (0.88, 0.22), (0.70, 0.16))
            else:
                probes = ((0.14, 0.14), (0.22, 0.14), (0.12, 0.22), (0.30, 0.16))
            for pxy in probes:
                cand = _slot_bbox(frame_bbox, pxy, hw, hh)
                nudged = _nudge_away_from(
                    cand, soft_blockers + nudge_hard, frame_bbox, hard_faces=nudge_hard
                )
                _try_add(nudged, "slot", pref_si)

        # Face-less: always try center (logo panel) — even with ink occupancy
        if faceless:
            for ry in (0.38, 0.42, 0.32, 0.48):
                cen = _center_bbox(frame_bbox, hw, hh, rel_y=ry)
                _try_add(cen, "center", pref_si)
                if any(m == "center" for _, m, _ in found):
                    break

        # Free-space: fallback when preferred slot missing (still ranked by slot_pull/y_pen)
        has_pref_slot = any(m == "slot" and si == pref_si for _, m, si in found)
        if not has_pref_slot or not found:
            inner = _inset_frame(frame_bbox)
            cands = compute_bubble_candidates(
                inner,
                [] if use_ink else body_boxes,
                [] if use_ink else face_boxes,
                extra_bboxes=placed,
                top_k=12,
                min_half_w=hw,
                min_half_h=hh,
                max_half_w=max_hw,
                max_half_h=max_hh,
                prefer_text_size=True,
                page_occupancy=page_occupancy,
            )
            for c in cands:
                bb = _clamp_bb_to_frame(tuple(float(x) for x in c["bbox"]), frame_bbox)
                _try_add(bb, "free_space", pref_si)
        return found

    scales = (1.0, 0.92, 0.8) if is_shout else (1.0, 0.9, 0.78, 0.65)
    for sc in scales:
        hw = max(24.0, half_w * sc)
        hh = max(20.0, half_h * sc)
        opts = collect(hw, hh)
        if not opts:
            continue
        opts.sort(key=lambda t: cand_rank(t[0], t[1], t[2]))
        bb, mode, si = opts[0]
        bb = restore_size(bb, hw, hh)
        if is_blocked(bb, pad=4.0):
            continue
        return bb, float(10 - sc * 2), {
            "placement_mode": mode,
            "slot_index": si,
            "overlap_face": False,
            "size_scale": sc,
            "occupancy": "ink" if use_ink else "aabb",
        }

    hw, hh = max(24.0, half_w * 0.55), max(20.0, half_h * 0.55)
    for k in range(len(_SLOTS)):
        si = (pref_si + k) % len(_SLOTS)
        bb = _slot_bbox(frame_bbox, _SLOTS[si], hw, hh)
        bb = _nudge_away_from(
            bb, soft_blockers + hard_boxes_geom, frame_bbox, hard_faces=hard_boxes_geom
        )
        bb = _clamp_bb_to_frame(bb, frame_bbox)
        if not is_blocked(bb, pad=2.0):
            return bb, 0.3, {
                "placement_mode": "fallback_slot",
                "slot_index": si,
                "overlap_face": False,
                "size_scale": 0.55,
                "occupancy": "ink" if use_ink else "aabb",
            }
    bb = _slot_bbox(frame_bbox, _SLOTS[pref_si], hw, hh)
    bb = _clamp_bb_to_frame(bb, frame_bbox)
    return bb, 0.1, {
        "placement_mode": "fallback",
        "slot_index": pref_si,
        "overlap_face": _overlaps_any_hard(bb, face_boxes, pad=2.0),
        "size_scale": 0.55,
        "occupancy": "ink" if use_ink else "aabb",
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
    anchors = _det_list(detections_doc, "anchors")
    # Structure JSON may put frames/anchors at top level (mode B)
    if not frames and detections_doc.get("frames"):
        frames = list(detections_doc["frames"] or [])
    if not anchors and detections_doc.get("anchors"):
        anchors = list(detections_doc["anchors"] or [])
    frames_ordered = frames_in_reading_order(frames)

    aims = collect_aims(faces, anchors)

    raw_lines = list(lines_doc.get("lines") or [])
    # Combined structure file: lines live next to frames/anchors
    if not raw_lines and detections_doc.get("lines"):
        raw_lines = list(detections_doc["lines"] or [])
    lines = ensure_line_ids(raw_lines)
    lines = sorted(lines, key=lambda x: (x.get("order", 0), x.get("id", "")))

    # Occupancy:
    #   color page → person chromatic fill (+ line ink), ignore body AABB
    #   mono page  → ink envelope fallback
    image_path = page.get("image_path") or (lines_doc.get("page") or {}).get(
        "image_path"
    )
    page_occupancy = None
    occupancy_mode = "none"
    face_bbs = [a.bbox for a in aims]
    for f in faces:
        if f.get("bbox"):
            face_bbs.append(normalize_bbox(f["bbox"]))
    frame_bbs = [normalize_bbox(f["bbox"]) for f in frames if f.get("bbox")]
    body_bbs = [normalize_bbox(b["bbox"]) for b in bodies if b.get("bbox")]

    color_prep = None
    if image_path:
        try:
            color_prep = prepare_color_page(image_path)
        except Exception:
            color_prep = None

    if color_prep and color_prep.get("has_color") and color_prep.get("fill_mask") is not None:
        page_occupancy = build_occupancy_color(
            color_prep["fill_mask"],
            line_ink_mask=color_prep.get("line_ink_mask"),
            face_bboxes=face_bbs,
            frame_bboxes=frame_bbs,
            face_pad_ratio=0.12,
            include_lines=True,
        )
        occupancy_mode = "color_fill"
        # User rule: ignore detector body boxes when fill mask drives free space
        bodies = []
    else:
        gray = load_page_gray(image_path)
        if gray is not None:
            page_occupancy = build_page_occupancy(
                gray,
                face_bbs,
                body_bboxes=body_bbs,
                frame_bboxes=frame_bbs,
                threshold=200,
                face_pad_ratio=0.12,
            )
            occupancy_mode = "ink_envelope"

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

            # Aim: faces ∪ anchors (#36). Speaker name / explicit id / R3 heuristics
            want_tail = tone not in ("narration", "shout") and shape not in (
                "v-rect",
                "tall-rect",
                "rect",
                "jagged",
                "giza",
            )
            pre_aim, pre_fbb, pre_src = resolve_aim(
                line,
                aims,
                frame_bbox,
                frame_id,
                slot_index=slot_i,
                bubble_bbox=None,
                bodies=bodies,
                allow_body_fallback=want_tail,
            )
            # Placement ranking uses preferred SLOT only (TR→TL…).
            # Do NOT pull bubble center toward face — that sank 「ん？」 to the
            # lower free pocket beside the head. Tails still aim via resolve_aim.
            prefer_slot = slot_i
            prefer_near = None
            if tone == "narration":
                prefer_slot = 1 if slot_i == 0 else slot_i
                prefer_near = _center(
                    _slot_bbox(frame_bbox, _SLOTS[prefer_slot % len(_SLOTS)], half_w, half_h)
                )
            elif not aims_in_frame(aims, frame_bbox, frame_id):
                # Face-less / logo panel → center bias
                prefer_near = _center(frame_bbox)

            hard_boxes = hard_avoid_boxes(aims, frame_bbox, frame_id)
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
                preferred_slot=prefer_slot,
                prefer_near=prefer_near,
                shape=shape,
                hard_boxes=hard_boxes,
                page_occupancy=page_occupancy,
            )
            bb = _clamp_bb_to_frame(bb, frame_bbox)
            meta_extra.update(place_meta)
            meta_extra["occupancy_mode"] = occupancy_mode

            aim_obj, face_bb, tail_from = resolve_aim(
                line,
                aims,
                frame_bbox,
                frame_id,
                slot_index=slot_i,
                bubble_bbox=bb,
                bodies=bodies,
                allow_body_fallback=want_tail,
            )
            if aim_obj is None and pre_aim is not None and slot_i == 0:
                aim_obj, face_bb, tail_from = pre_aim, pre_fbb, pre_src
            face_id = aim_obj.id if aim_obj is not None else None
            if tail_from:
                meta_extra["tail_from"] = tail_from
            if aim_obj is not None:
                meta_extra["aim_source"] = aim_obj.source

            if not want_tail or tone == "narration":
                face_bb = None
                face_id = None
                meta_extra.pop("tail_from", None)

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
