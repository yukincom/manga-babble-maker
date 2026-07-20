"""High-level detect / place / render / run (no CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from manga_babble.detect import detect_page
from manga_babble.export import build_manifest, output_paths, stem_from_page, write_manifest
from manga_babble.place import build_layout
from manga_babble.render import compose_preview, draw_bubble_layer, draw_text_layer
from manga_babble.schema import check_schema_version, load_json, page_size_from_data, save_json


def run_detect(
    image_path: str | Path,
    *,
    model_path: str | Path | None = None,
    conf_threshold: float = 0.5,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    doc = detect_page(
        image_path,
        model_path=model_path,
        conf_threshold=conf_threshold,
    )
    if out_path:
        save_json(out_path, doc)
    return doc


def run_place(
    detections: dict[str, Any] | str | Path,
    lines: dict[str, Any] | str | Path,
    *,
    out_path: str | Path | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    det = load_json(detections) if not isinstance(detections, dict) else detections
    lin = load_json(lines) if not isinstance(lines, dict) else lines
    check_schema_version(det)
    check_schema_version(lin)
    w, h, _ = page_size_from_data(det)
    # Prefer lines page image if present
    if lin.get("page", {}).get("image_path") and not det.get("page", {}).get(
        "image_path"
    ):
        det.setdefault("page", {})["image_path"] = lin["page"]["image_path"]
    layout = build_layout(det, lin, page_width=w, page_height=h, seed=seed)
    if out_path:
        save_json(out_path, layout)
    return layout


def run_render(
    layout: dict[str, Any] | str | Path,
    out_dir: str | Path,
    *,
    preview: bool = True,
    art_path: str | Path | None = None,
) -> dict[str, Any]:
    lay = load_json(layout) if not isinstance(layout, dict) else layout
    check_schema_version(lay)
    page = lay.get("page") or {}
    w = int(page["width"])
    h = int(page["height"])
    art = art_path or page.get("image_path")
    stem = stem_from_page(page)
    paths = output_paths(out_dir, stem)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    bubbles = lay.get("bubbles") or []
    options = lay.get("options") or {}
    bubble_img = draw_bubble_layer(w, h, bubbles)
    text_img = draw_text_layer(w, h, bubbles, options=options)
    bubble_img.save(paths["bubble_layer"])
    text_img.save(paths["text_layer"])
    save_json(paths["layout_json"], lay)

    preview_path = None
    if preview:
        prev = compose_preview(art, bubble_img, text_img, width=w, height=h)
        prev.save(paths["preview"])
        preview_path = str(paths["preview"])

    files = {
        "art": str(art) if art else None,
        "bubble_layer": str(paths["bubble_layer"]),
        "text_layer": str(paths["text_layer"]),
        "layout_json": str(paths["layout_json"]),
        "preview": preview_path,
    }
    manifest = build_manifest(page=page, bubbles=bubbles, files=files)
    write_manifest(paths["manifest"], manifest)
    return manifest


def run_pipeline(
    image_path: str | Path,
    lines: dict[str, Any] | str | Path,
    out_dir: str | Path,
    *,
    model_path: str | Path | None = None,
    conf_threshold: float = 0.5,
    seed: int = 0,
    preview: bool = True,
    detections: dict[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Full pipeline. If detections provided, skip ONNX detect."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem if image_path else "page"

    if detections is not None:
        det = (
            load_json(detections)
            if not isinstance(detections, dict)
            else detections
        )
    else:
        det_path = out_dir / f"{stem}_detections.json"
        det = run_detect(
            image_path,
            model_path=model_path,
            conf_threshold=conf_threshold,
            out_path=det_path,
        )

    # Ensure page image path
    det.setdefault("page", {})
    det["page"]["image_path"] = str(image_path)

    lin = load_json(lines) if not isinstance(lines, dict) else lines
    layout_path = out_dir / f"{stem}_layout.json"
    layout = run_place(det, lin, out_path=layout_path, seed=seed)
    layout["page"]["image_path"] = str(image_path)
    save_json(layout_path, layout)

    return run_render(
        layout,
        out_dir,
        preview=preview,
        art_path=image_path,
    )
