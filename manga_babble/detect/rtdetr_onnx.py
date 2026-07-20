"""RT-DETRv4-X Manga109-s v2 ONNX inference (local)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image

from manga_babble import SCHEMA_VERSION

CLASS_NAMES = {0: "body", 1: "text", 2: "frame", 3: "face"}
INPUT_SIZE = 1280
DEFAULT_MODEL = Path("models/rtdetrv4-x-manga109s_v2/model.onnx")

_session_cache: dict[str, ort.InferenceSession] = {}


def _get_session(model_path: str | Path) -> ort.InferenceSession:
    key = str(Path(model_path).resolve())
    if key not in _session_cache:
        if not Path(model_path).is_file():
            raise FileNotFoundError(
                f"ONNX model not found: {model_path}. "
                "See models/README.md for download instructions."
            )
        _session_cache[key] = ort.InferenceSession(
            key,
            providers=["CPUExecutionProvider"],
        )
    return _session_cache[key]


def _center(bbox):
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def _contains(frame_bbox, point) -> bool:
    x1, y1, x2, y2 = frame_bbox
    px, py = point
    return x1 <= px <= x2 and y1 <= py <= y2


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _intersection_area(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def _assign_frame_by_face_rule(item: dict, frames: list[dict]) -> str | None:
    """
    ぶち抜き対応の帰属:
      1) bbox 中心が入っている frame
      2) なければ / 複数なら 重なり面積最大の frame
    「縁が1px触れただけ」で他コマにしないよう、中心優先。
    """
    if not frames:
        return None
    bb = item["bbox"]
    c = _center(bb)
    containing = []
    for fr in frames:
        fb = fr["bbox"]
        if _contains(fb, c):
            containing.append((fr, _intersection_area(bb, fb)))
    if containing:
        # among frames that contain the center, pick max overlap with the item
        containing.sort(key=lambda x: x[1], reverse=True)
        return containing[0][0].get("id")
    # center outside all frames (true span): max intersection area
    best_id, best_ia = None, 0.0
    for fr in frames:
        ia = _intersection_area(bb, fr["bbox"])
        if ia > best_ia:
            best_ia = ia
            best_id = fr.get("id")
    return best_id


def _assign_frame_ids(items: list[dict], frames: list[dict]) -> None:
    if not frames:
        return
    for it in items:
        fid = _assign_frame_by_face_rule(it, frames)
        if fid is not None:
            it["frame_id"] = fid


def _link_bodies_to_face_frames(
    bodies: list[dict], faces: list[dict], frames: list[dict]
) -> None:
    """
    Spanning body: prefer the frame_id of the nearest face that overlaps it.
    Falls back to face-rule assignment already on the body.
    """
    if not bodies or not faces:
        return
    for body in bodies:
        bb = body["bbox"]
        best_face = None
        best_d = None
        bcx, bcy = _center(bb)
        for face in faces:
            fb = face["bbox"]
            if _intersection_area(bb, fb) <= 0 and not _contains(bb, _center(fb)):
                # face center inside body also counts
                continue
            fcx, fcy = _center(fb)
            d = (fcx - bcx) ** 2 + (fcy - bcy) ** 2
            if best_d is None or d < best_d:
                best_d = d
                best_face = face
        # also: face center inside body bbox
        if best_face is None:
            for face in faces:
                if _contains(bb, _center(face["bbox"])):
                    best_face = face
                    break
        if best_face and best_face.get("frame_id"):
            body["frame_id"] = best_face["frame_id"]
            body["meta"] = dict(body.get("meta") or {})
            body["meta"]["frame_from"] = "linked_face"
            body["meta"]["linked_face_id"] = best_face.get("id")


def detect_page(
    image_path: str | Path,
    *,
    model_path: str | Path | None = None,
    conf_threshold: float = 0.5,
) -> dict[str, Any]:
    image_path = Path(image_path)
    model_path = Path(model_path) if model_path else DEFAULT_MODEL
    session = _get_session(model_path)

    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    resized = image.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    arr = np.asarray(resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[None]
    orig_size = np.array([[w, h]], dtype=np.int64)

    labels, boxes, scores = session.run(
        None, {"images": arr, "orig_target_sizes": orig_size}
    )
    labels, boxes, scores = labels[0], boxes[0], scores[0]
    keep = scores >= conf_threshold

    buckets: dict[str, list] = {
        "bodies": [],
        "texts": [],
        "frames": [],
        "faces": [],
    }
    key_map = {
        "body": "bodies",
        "text": "texts",
        "frame": "frames",
        "face": "faces",
    }
    counters = {k: 0 for k in key_map}

    for cid, box, sc in zip(labels[keep], boxes[keep], scores[keep]):
        name = CLASS_NAMES.get(int(cid))
        if name is None:
            continue
        bucket = key_map[name]
        idx = counters[name]
        counters[name] += 1
        prefix = {"body": "b", "text": "t", "frame": "f", "face": "face"}[name]
        x1, y1, x2, y2 = map(float, box)
        buckets[bucket].append(
            {
                "id": f"{prefix}{idx}",
                "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "score": round(float(sc), 4),
            }
        )

    # Faces first: ぶち抜きは「顔が属するコマ」が一次帰属
    _assign_frame_ids(buckets["faces"], buckets["frames"])
    _assign_frame_ids(buckets["bodies"], buckets["frames"])
    _assign_frame_ids(buckets["texts"], buckets["frames"])
    # Body that spans panels: stick to nearest overlapping face's frame
    _link_bodies_to_face_frames(
        buckets["bodies"], buckets["faces"], buckets["frames"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "page": {
            "image_path": str(image_path),
            "width": w,
            "height": h,
        },
        "detections": buckets,
        "model": {
            "name": "rtdetrv4-x-manga109s_v2",
            "path": str(model_path),
            "conf_threshold": conf_threshold,
        },
    }
