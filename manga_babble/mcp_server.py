"""
Thin MCP server wrapping manga_babble.pipeline.

Requires optional dependency: pip install mcp

Run:
  python -m manga_babble.mcp_server
  # or:  manga_babble-mcp  (if entry point installed)

Does not upload manuscript data. Cloud LLM usage is decided by the agent host.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _run():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "mcp package not installed. Run: pip install mcp\n" + str(e)
        ) from e

    from manga_babble.pipeline import run_detect, run_place, run_pipeline, run_render

    mcp = FastMCP("manga-babble")

    @mcp.tool()
    def detect_page(
        image_path: str,
        model_path: str = "models/rtdetrv4-x-manga109s_v2/model.onnx",
        conf_threshold: float = 0.5,
        out_path: str | None = None,
    ) -> dict[str, Any]:
        """Detect body/text/frame/face on a manga page (local ONNX)."""
        return run_detect(
            image_path,
            model_path=model_path or None,
            conf_threshold=conf_threshold,
            out_path=out_path,
        )

    @mcp.tool()
    def place_bubbles(
        detections_path: str,
        lines_path: str,
        out_path: str | None = None,
        seed: int = 0,
    ) -> dict[str, Any]:
        """Place bubbles from detections JSON + dialogue lines JSON."""
        return run_place(
            detections_path,
            lines_path,
            out_path=out_path,
            seed=seed,
        )

    @mcp.tool()
    def render_layers(
        layout_path: str,
        out_dir: str,
        preview: bool = True,
        art_path: str | None = None,
    ) -> dict[str, Any]:
        """Render bubble/text PNG layers + layout JSON + manifest."""
        return run_render(
            layout_path,
            out_dir,
            preview=preview,
            art_path=art_path,
        )

    @mcp.tool()
    def run_pipeline_tool(
        image_path: str,
        lines_path: str,
        out_dir: str,
        model_path: str = "models/rtdetrv4-x-manga109s_v2/model.onnx",
        conf_threshold: float = 0.5,
        seed: int = 0,
        preview: bool = True,
        detections_path: str | None = None,
    ) -> dict[str, Any]:
        """Full pipeline: detect (unless detections_path) → place → render."""
        return run_pipeline(
            image_path,
            lines_path,
            out_dir,
            model_path=model_path or None,
            conf_threshold=conf_threshold,
            seed=seed,
            preview=preview,
            detections=detections_path,
        )

    mcp.run()


if __name__ == "__main__":
    _run()
