"""JSON load/save and light schema checks (schema_version 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manga_babble import SCHEMA_VERSION

VALID_TONES = frozenset(
    {"normal", "shout", "whisper", "thought", "narration"}
)


class SchemaError(ValueError):
    """Invalid or unsupported JSON payload."""


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SchemaError(f"JSON root must be an object: {path}")
    return data


def save_json(path: str | Path, data: dict[str, Any], *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    return path


def check_schema_version(data: dict[str, Any], *, path: str = "") -> None:
    ver = data.get("schema_version", SCHEMA_VERSION)
    if ver != SCHEMA_VERSION:
        loc = f" ({path})" if path else ""
        raise SchemaError(
            f"Unsupported schema_version={ver}{loc}; expected {SCHEMA_VERSION}"
        )


def ensure_line_ids(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, line in enumerate(lines):
        item = dict(line)
        if not item.get("id"):
            item["id"] = f"l{i}"
        if "order" not in item or item["order"] is None:
            item["order"] = i
        if "text" not in item or item["text"] is None:
            raise SchemaError(f"lines[{i}] missing required field 'text'")
        out.append(item)
    return out


def normalize_bbox(bbox: list | tuple) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise SchemaError(f"bbox must have 4 values, got {bbox!r}")
    x1, y1, x2, y2 = map(float, bbox)
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def page_size_from_data(
    data: dict[str, Any],
    *,
    image_path: str | Path | None = None,
) -> tuple[int, int, str | None]:
    """Return (width, height, image_path_str)."""
    page = data.get("page") or {}
    img = image_path or page.get("image_path")
    w, h = page.get("width"), page.get("height")
    if w and h:
        return int(w), int(h), str(img) if img else None
    if img:
        from PIL import Image

        with Image.open(img) as im:
            return im.size[0], im.size[1], str(img)
    raise SchemaError("page width/height or image_path required")
