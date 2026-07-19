"""Build layout JSON from detections + dialogue lines."""

from __future__ import annotations

from typing import Any

from manga_babble import SCHEMA_VERSION
from manga_babble.place.candidates import compute_bubble_candidates, size_from_text
from manga_babble.schema import ensure_line_ids, normalize_bbox
from manga_babble.tone import resolve_tone
from manga_babble.tone.resolve import is_page_margin_line


def _det_list(detections: dict[str, Any], key: str) -> list[dict[str, Any]]:
    block = detections.get("detections") or detections
    items = block.get(key) or []
    return list(items)


def _bbox_of(item: dict[str, Any]) -> tuple[float, float, float, float]:
    return normalize_bbox(item["bbox"])


def _center(bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def _contains(frame_bbox, point) -> bool:
    x1, y1, x2, y2 = frame_bbox
    px, py = point
    return x1 <= px <= x2 and y1 <= py <= y2


def _assign_frame(
    line: dict[str, Any],
    frames: list[dict[str, Any]],
    faces: list[dict[str, Any]],
    page_bbox,
) -> tuple[tuple[float, float, float, float], str | None]:
    if line.get("frame_id"):
        for f in frames:
            if f.get("id") == line["frame_id"]:
                return _bbox_of(f), f.get("id")
    if frames:
        ranked = sorted(
            frames,
            key=lambda f: (
                (_bbox_of(f)[2] - _bbox_of(f)[0])
                * (_bbox_of(f)[3] - _bbox_of(f)[1])
            ),
            reverse=True,
        )
        fb = _bbox_of(ranked[0])
        return fb, ranked[0].get("id")
    return page_bbox, None


def _match_face(
    line: dict[str, Any],
    faces: list[dict[str, Any]],
    used: set[str],
    frame_bbox,
    line_index: int,
) -> tuple[dict[str, Any] | None, tuple[float, float, float, float] | None]:
    speaker = line.get("speaker")
    if speaker:
        for f in faces:
            if f.get("speaker") == speaker:
                return f, _bbox_of(f)
        for f in faces:
            if f.get("id") == speaker:
                return f, _bbox_of(f)

    in_frame = []
    for f in faces:
        bb = _bbox_of(f)
        if _contains(frame_bbox, _center(bb)):
            in_frame.append(f)
    pool = in_frame or faces
    for f in pool:
        fid = f.get("id") or str(id(f))
        if fid not in used:
            used.add(fid)
            return f, _bbox_of(f)
    if pool:
        f = pool[line_index % len(pool)]
        return f, _bbox_of(f)
    return None, None


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
    """
    Place a slim note outside the comic panels (typically left gutter).
    Prefer left margin; fall back to right; then bottom strip.
    """
    n = max(1, len(text.replace("\n", "")))
    # Vertical strip: narrow width, height from char count
    strip_w = max(36.0, min(page_w * 0.06, 72.0))
    char_h = max(14.0, min(22.0, page_h / 90.0))
    strip_h = min(page_h * 0.45, max(80.0, n * char_h * 1.15))

    content = _union_frames(frames, (0, 0, page_w, page_h))
    left_gap = content[0] - 0
    right_gap = page_w - content[2]
    pad = 8.0

    candidates = []
    # Left gutter (outside frames)
    if left_gap >= strip_w * 0.5:
        x2 = max(strip_w, content[0] - pad)
        x1 = max(0.0, x2 - strip_w)
        y1 = min(page_h - strip_h, max(0.0, content[1] + (content[3] - content[1]) * 0.35))
        y2 = y1 + strip_h
        candidates.append((x1, y1, x2, y2))
    # Right gutter
    if right_gap >= strip_w * 0.5:
        x1 = min(page_w - strip_w, content[2] + pad)
        x2 = min(page_w, x1 + strip_w)
        y1 = min(page_h - strip_h, max(0.0, content[1] + (content[3] - content[1]) * 0.35))
        y2 = y1 + strip_h
        candidates.append((x1, y1, x2, y2))
    # Bottom strip under content
    x1 = max(0.0, content[0])
    x2 = min(page_w, content[0] + max(strip_w * 2, n * char_h * 0.5))
    y2 = page_h - pad
    y1 = max(content[3] + pad, y2 - strip_w * 1.2)
    if y1 < y2:
        candidates.append((x1, y1, x2, y2))

    if not candidates:
        # Absolute left edge of page
        candidates.append((pad, page_h * 0.4, pad + strip_w, page_h * 0.4 + strip_h))

    def overlaps(a, b):
        return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])

    for bb in candidates:
        if any(overlaps(bb, p) for p in placed):
            # nudge down
            x1, y1, x2, y2 = bb
            h = y2 - y1
            y1 = min(page_h - h - pad, y1 + h + pad)
            y2 = y1 + h
            bb = (x1, y1, x2, y2)
        if not any(overlaps(bb, p) for p in placed):
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
    bodies = _det_list(detections_doc, "bodies")
    faces = _det_list(detections_doc, "faces")
    texts = _det_list(detections_doc, "texts")

    lines = ensure_line_ids(list(lines_doc.get("lines") or []))
    lines = sorted(lines, key=lambda x: (x.get("order", 0), x.get("id", "")))

    used_faces: set[str] = set()
    placed_bboxes: list[tuple] = []
    bubbles: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        tone, tone_source = resolve_tone(line)
        margin = is_page_margin_line(line)
        meta_extra: dict[str, Any] = {}

        if margin:
            bb, score = _place_page_margin(
                str(line["text"]), float(w), float(h), frames, placed_bboxes
            )
            face_bb = None
            face_id = None
            frame_id = None
            tone = "narration"
            meta_extra["placement"] = "page_margin"
        else:
            frame_bbox, frame_id = _assign_frame(line, frames, faces, page_bbox)

            def in_fr(bb):
                return _contains(frame_bbox, _center(bb))

            body_bbs = [_bbox_of(b) for b in bodies if in_fr(_bbox_of(b))] or [
                _bbox_of(b) for b in bodies
            ]
            face_bbs = [_bbox_of(f) for f in faces if in_fr(_bbox_of(f))] or [
                _bbox_of(f) for f in faces
            ]
            text_bbs = [_bbox_of(t) for t in texts if in_fr(_bbox_of(t))]
            extra = text_bbs + placed_bboxes

            face_obj, face_bb = _match_face(line, faces, used_faces, frame_bbox, i)
            min_hw, min_hh, max_hw, max_hh = size_from_text(str(line["text"]), w, h)
            cands = compute_bubble_candidates(
                frame_bbox,
                body_bbs,
                face_bbs,
                extra_bboxes=extra,
                top_k=max(3, len(lines)),
                min_half_w=min_hw,
                min_half_h=min_hh,
                max_half_w=max_hw,
                max_half_h=max_hh,
            )
            if not cands:
                fx1, fy1, fx2, fy2 = frame_bbox
                bw = min(max_hw * 2, (fx2 - fx1) * 0.4)
                bh = min(max_hh * 2, (fy2 - fy1) * 0.25)
                cx = (fx1 + fx2) / 2
                cy = fy1 + (fy2 - fy1) * 0.2
                bb = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
                score = 0.0
            else:
                if face_bb is not None:
                    fcx, fcy = _center(face_bb)

                    def dist_score(c):
                        bx1, by1, bx2, by2 = c["bbox"]
                        bcx, bcy = (bx1 + bx2) / 2, (by1 + by2) / 2
                        d = ((bcx - fcx) ** 2 + (bcy - fcy) ** 2) ** 0.5
                        return c["score"] * 10 - d * 0.01

                    cands = sorted(cands, key=dist_score, reverse=True)
                chosen = cands[0]
                bb = chosen["bbox"]
                score = float(chosen["score"])

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
    }
