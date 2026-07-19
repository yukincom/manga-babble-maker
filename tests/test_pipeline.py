from pathlib import Path

from manga_babble.pipeline import run_place, run_render
from manga_babble.schema import load_json

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def test_place_and_render(tmp_path):
    det = load_json(SAMPLES / "demo_detections.json")
    lines = load_json(SAMPLES / "demo_lines.json")
    layout = run_place(det, lines, seed=0)
    assert layout["bubbles"]
    for b in layout["bubbles"]:
        assert b["text"]
        assert b["tone"]
        assert len(b["bubble_bbox"]) == 4

    out = tmp_path / "out"
    manifest = run_render(layout, out, preview=True, art_path=None)
    assert manifest["status"] == "ok"
    assert Path(manifest["files"]["bubble_layer"]).is_file()
    assert Path(manifest["files"]["text_layer"]).is_file()
    assert Path(manifest["files"]["layout_json"]).is_file()
    # Text data present for downstream tools
    assert all(b.get("text") for b in manifest["bubbles"])
