"""Non-interactive CLI: detect | place | render | run."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from manga_babble import SCHEMA_VERSION, __version__
from manga_babble.pipeline import run_detect, run_place, run_pipeline, run_render
from manga_babble.schema import SchemaError


def _print_json(data: dict) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _error_manifest(message: str, code: str = "error") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "files": {},
        "bubbles": [],
        "errors": [{"code": code, "message": message}],
    }


def cmd_detect(args: argparse.Namespace) -> int:
    doc = run_detect(
        args.image,
        model_path=args.model,
        conf_threshold=args.conf,
        out_path=args.out,
    )
    if args.out:
        _print_json(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ok",
                "files": {"detections": str(Path(args.out).resolve())},
                "page": doc.get("page"),
                "errors": [],
            }
        )
    else:
        _print_json(doc)
    return 0


def cmd_place(args: argparse.Namespace) -> int:
    layout = run_place(
        args.detections,
        args.lines,
        out_path=args.out,
        seed=args.seed,
    )
    if args.out:
        _print_json(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ok",
                "files": {"layout_json": str(Path(args.out).resolve())},
                "bubbles": layout.get("bubbles"),
                "errors": [],
            }
        )
    else:
        _print_json(layout)
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    manifest = run_render(
        args.layout,
        args.out_dir,
        preview=not args.no_preview,
        art_path=args.art,
    )
    _print_json(manifest)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    lines_path = args.lines
    if args.script:
        from manga_babble.script_parse import parse_script_file
        from manga_babble.schema import save_json

        doc = parse_script_file(args.script)
        out_lines = Path(args.out_dir) / "lines_from_script.json"
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        save_json(out_lines, doc)
        lines_path = str(out_lines)
    if not lines_path:
        raise ValueError("either --lines or --script is required")
    manifest = run_pipeline(
        args.image,
        lines_path,
        args.out_dir,
        model_path=args.model,
        conf_threshold=args.conf,
        seed=args.seed,
        preview=not args.no_preview,
        detections=args.detections,
    )
    _print_json(manifest)
    return 0


def cmd_parse_script(args: argparse.Namespace) -> int:
    from manga_babble.script_parse import parse_script_file
    from manga_babble.schema import save_json

    doc = parse_script_file(args.script)
    if args.out:
        save_json(args.out, doc)
        _print_json(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ok",
                "files": {"lines": str(Path(args.out).resolve())},
                "errors": [],
            }
        )
    else:
        _print_json(doc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="manga_babble",
        description="Manga bubble placement: detect → place → render (local ONNX).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("detect", help="Run RT-DETR ONNX detection")
    d.add_argument("--image", required=True, help="Page image path")
    d.add_argument("--out", help="Write detections JSON path")
    d.add_argument(
        "--model",
        default="models/rtdetrv4-x-manga109s_v2/model.onnx",
        help="ONNX model path",
    )
    d.add_argument("--conf", type=float, default=0.5, help="Confidence threshold")
    d.set_defaults(func=cmd_detect)

    pl = sub.add_parser("place", help="Place bubbles from detections + lines")
    pl.add_argument("--detections", required=True, help="detections JSON path")
    pl.add_argument("--lines", required=True, help="lines JSON path")
    pl.add_argument("--out", help="Write layout JSON path")
    pl.add_argument("--seed", type=int, default=0)
    pl.set_defaults(func=cmd_place)

    r = sub.add_parser("render", help="Render bubble/text layers from layout")
    r.add_argument("--layout", required=True, help="layout JSON path")
    r.add_argument("--out-dir", required=True, help="Output directory")
    r.add_argument("--art", help="Art image path override")
    r.add_argument("--no-preview", action="store_true")
    r.set_defaults(func=cmd_render)

    run = sub.add_parser("run", help="detect (optional skip) + place + render")
    run.add_argument("--image", required=True)
    run.add_argument("--lines", help="lines JSON path")
    run.add_argument("--script", help="human script.txt (converted to lines)")
    run.add_argument("--out-dir", required=True)
    run.add_argument(
        "--model",
        default="models/rtdetrv4-x-manga109s_v2/model.onnx",
    )
    run.add_argument("--conf", type=float, default=0.5)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument(
        "--detections",
        help="Skip ONNX; use this detections JSON instead",
    )
    run.add_argument("--no-preview", action="store_true")
    run.set_defaults(func=cmd_run)

    ps = sub.add_parser("parse-script", help="Parse script.txt → lines.json")
    ps.add_argument("--script", required=True)
    ps.add_argument("--out", help="Write lines JSON")
    ps.set_defaults(func=cmd_parse_script)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SchemaError, FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        _print_json(_error_manifest(str(e), code=type(e).__name__))
        return 1
    except Exception as e:
        print(traceback.format_exc(), file=sys.stderr)
        _print_json(_error_manifest(str(e), code="internal"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
