"""Speaker aim resolution: faces ∪ anchors → AimRef (#36 / #31 R0–R3).

Mode A: faces from detector.
Mode B: anchors from structure JSON (name / head boxes).
Both share the same resolve path — no work-specific names in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from manga_babble.schema import normalize_bbox


@dataclass(frozen=True)
class AimRef:
    """Hard-avoid + tail target (face or name-stage anchor)."""

    id: str
    bbox: tuple[float, float, float, float]
    speaker: str | None = None
    frame_id: str | None = None
    source: str = "face"  # "face" | "anchor"


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def _contains(frame_bbox, point) -> bool:
    x1, y1, x2, y2 = frame_bbox
    px, py = point
    return x1 <= px <= x2 and y1 <= py <= y2


def _clip_to_frame(bb, frame_bbox):
    x1 = max(bb[0], frame_bbox[0])
    y1 = max(bb[1], frame_bbox[1])
    x2 = min(bb[2], frame_bbox[2])
    y2 = min(bb[3], frame_bbox[3])
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _intersection_area(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _norm_speaker(s: str | None) -> str | None:
    if s is None:
        return None
    t = str(s).strip()
    return t or None


def collect_aims(
    faces: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> list[AimRef]:
    """Merge faces and anchors into AimRef list (anchors and faces both valid)."""
    out: list[AimRef] = []
    for i, f in enumerate(faces or []):
        try:
            bb = normalize_bbox(f["bbox"])
        except Exception:
            continue
        fid = str(f.get("id") or f"face{i}")
        out.append(
            AimRef(
                id=fid,
                bbox=bb,
                speaker=_norm_speaker(f.get("speaker")),
                frame_id=f.get("frame_id"),
                source="face",
            )
        )
    for i, a in enumerate(anchors or []):
        try:
            bb = normalize_bbox(a["bbox"])
        except Exception:
            continue
        aid = str(a.get("id") or f"anchor{i}")
        out.append(
            AimRef(
                id=aid,
                bbox=bb,
                speaker=_norm_speaker(a.get("speaker")),
                frame_id=a.get("frame_id"),
                source="anchor",
            )
        )
    return out


def aims_in_frame(
    aims: list[AimRef],
    frame_bbox: tuple[float, float, float, float],
    frame_id: str | None,
) -> list[AimRef]:
    """Aims belonging to this panel (frame_id match or center inside). No cross-panel pull."""
    out: list[AimRef] = []
    for a in aims:
        if frame_id and a.frame_id == frame_id:
            out.append(a)
            continue
        if _contains(frame_bbox, _center(a.bbox)):
            out.append(a)
    return out


def hard_avoid_boxes(
    aims: list[AimRef],
    frame_bbox: tuple[float, float, float, float],
    frame_id: str | None,
) -> list[tuple[float, float, float, float]]:
    """All aim bboxes in frame, clipped — hard constraints for placement."""
    boxes = []
    for a in aims_in_frame(aims, frame_bbox, frame_id):
        clipped = _clip_to_frame(a.bbox, frame_bbox)
        if clipped is not None:
            boxes.append(clipped)
    return boxes


def body_aim_bbox(
    bodies: list[dict[str, Any]],
    frame_bbox: tuple[float, float, float, float],
    frame_id: str | None,
    near_point: tuple[float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    """Upper third of nearest body in frame (face-less fallback)."""
    cands: list[tuple[float, float, float, float]] = []
    for b in bodies or []:
        try:
            bb = normalize_bbox(b["bbox"])
        except Exception:
            continue
        clipped = _clip_to_frame(bb, frame_bbox)
        if clipped is None:
            continue
        ia = _intersection_area(bb, frame_bbox)
        if ia <= 0:
            continue
        frac = ia / max(_area(bb), 1.0)
        if not (
            (frame_id and b.get("frame_id") == frame_id)
            or _contains(frame_bbox, _center(bb))
            or frac >= 0.12
        ):
            continue
        x1, y1, x2, y2 = clipped
        aim = (x1, y1, x2, y1 + max(20.0, (y2 - y1) * 0.35))
        cands.append(aim)
    if not cands:
        return None
    if near_point is not None:
        cands.sort(
            key=lambda t: (_center(t)[0] - near_point[0]) ** 2
            + (_center(t)[1] - near_point[1]) ** 2
        )
    else:
        cands.sort(key=lambda t: _center(t)[0])
    return cands[0]


def resolve_aim(
    line: dict[str, Any],
    aims: list[AimRef],
    frame_bbox: tuple[float, float, float, float],
    frame_id: str | None,
    *,
    slot_index: int = 0,
    bubble_bbox: tuple[float, float, float, float] | None = None,
    bodies: list[dict[str, Any]] | None = None,
    allow_body_fallback: bool = True,
) -> tuple[AimRef | None, tuple[float, float, float, float] | None, str | None]:
    """
    Resolve speaker aim for a line.

    Returns (AimRef or synthetic, bbox, tail_from) where tail_from is
    None | \"face\" | \"anchor\" | \"body\".

    Priority (#31 R0/R3):
      1) explicit face_id / anchor_id / speaker_face_id
      2) speaker name match among in-frame aims only
      3) multi-aim: R→L vs slot_index; optional nearest-to-bubble switch
      4) single aim: only for slot_index == 0
      5) body upper-third if allow_body_fallback
      6) null
    """
    pool = aims_in_frame(aims, frame_bbox, frame_id)
    speaker = _norm_speaker(line.get("speaker"))
    explicit = (
        line.get("face_id")
        or line.get("anchor_id")
        or line.get("speaker_face_id")
        or line.get("speaker_anchor_id")
    )

    # 1) Explicit id (may be global if user forced it)
    if explicit:
        eid = str(explicit)
        for a in aims:
            if a.id == eid:
                return a, a.bbox, a.source
        for a in pool:
            if a.id == eid:
                return a, a.bbox, a.source

    # 2) Speaker name — in-frame only (no other-panel pull)
    if speaker:
        for a in pool:
            if a.speaker == speaker or a.id == speaker:
                return a, a.bbox, a.source

    if not pool:
        if allow_body_fallback and bodies:
            near = _center(bubble_bbox) if bubble_bbox else _center(frame_bbox)
            bb = body_aim_bbox(bodies, frame_bbox, frame_id, near_point=near)
            if bb is not None:
                synth = AimRef(
                    id="body_aim",
                    bbox=bb,
                    speaker=speaker,
                    frame_id=frame_id,
                    source="anchor",
                )
                return synth, bb, "body"
        return None, None, None

    # 3) Multiple aims: R→L by center x
    if len(pool) > 1:
        pool_rtl = sorted(pool, key=lambda a: _center(a.bbox)[0], reverse=True)
        idx = min(max(0, slot_index), len(pool_rtl) - 1)
        chosen = pool_rtl[idx]
        if bubble_bbox is not None:
            bcx, bcy = _center(bubble_bbox)

            def d2(a: AimRef) -> float:
                fc = _center(a.bbox)
                return (fc[0] - bcx) ** 2 + (fc[1] - bcy) ** 2

            nearest = min(pool, key=d2)
            if nearest is not chosen and d2(nearest) * 2.25 < d2(chosen):
                chosen = nearest
        return chosen, chosen.bbox, chosen.source

    # 4) Single aim: only first line in panel
    if slot_index == 0:
        a0 = pool[0]
        return a0, a0.bbox, a0.source

    # 5) Later lines with only one aim → do not reuse that head; try body
    if allow_body_fallback and bodies:
        near = _center(bubble_bbox) if bubble_bbox else _center(frame_bbox)
        bb = body_aim_bbox(bodies, frame_bbox, frame_id, near_point=near)
        if bb is not None:
            synth = AimRef(
                id="body_aim",
                bbox=bb,
                speaker=speaker,
                frame_id=frame_id,
                source="anchor",
            )
            return synth, bb, "body"
    return None, None, None
