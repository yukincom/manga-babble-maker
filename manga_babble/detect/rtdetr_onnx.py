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


def _assign_frame_ids(items: list[dict], frames: list[dict]) -> None:
    if not frames:
        return
    for it in items:
        c = _center(it["bbox"])
        best = None
        best_area = None
        for fr in frames:
            fb = fr["bbox"]
            if _contains(fb, c):
                area = (fb[2] - fb[0]) * (fb[3] - fb[1])
                if best is None or area < best_area:
                    best = fr
                    best_area = area
        if best is not None:
            it["frame_id"] = best.get("id")


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

    _assign_frame_ids(buckets["bodies"], buckets["frames"])
    _assign_frame_ids(buckets["faces"], buckets["frames"])
    _assign_frame_ids(buckets["texts"], buckets["frames"])

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
