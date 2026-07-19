"""Write layout and output manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from manga_babble import SCHEMA_VERSION
from manga_babble.schema import save_json


def stem_from_page(page: dict[str, Any], default: str = "page") -> str:
    img = page.get("image_path")
    if img:
        return Path(img).stem
    return default


def output_paths(out_dir: str | Path, stem: str) -> dict[str, Path]:
    out_dir = Path(out_dir)
    return {
        "bubble_layer": out_dir / f"{stem}_bubble.png",
        "text_layer": out_dir / f"{stem}_text.png",
        "layout_json": out_dir / f"{stem}_layout.json",
        "preview": out_dir / f"{stem}_preview.png",
        "manifest": out_dir / f"{stem}_manifest.json",
        "detections": out_dir / f"{stem}_detections.json",
    }


def build_manifest(
    *,
    page: dict[str, Any],
    bubbles: list[dict[str, Any]],
    files: dict[str, str | None],
    status: str = "ok",
    errors: list | None = None,
) -> dict[str, Any]:
    slim = []
    for b in bubbles:
        slim.append(
            {
                "id": b.get("id"),
                "line_id": b.get("line_id"),
                "text": b.get("text"),
                "tone": b.get("tone"),
                "order": b.get("order"),
                "bubble_bbox": b.get("bubble_bbox"),
                "speaker_face_bbox": b.get("speaker_face_bbox"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "page": page,
        "files": files,
        "bubbles": slim,
        "errors": errors or [],
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    return save_json(path, manifest)
