"""Load and pick raster shape templates from assets/shapes/."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

_ROOT = Path(__file__).resolve().parents[2] / "assets" / "shapes"

# shape kind → directory name under assets/shapes
SHAPE_DIRS = {
    "fun-cloud": "fun-cloud",
    "fun_cloud": "fun-cloud",
    "kumo": "fun-cloud",  # legacy token
    "cloud": "fun-cloud",  # legacy → fun speech cloud
    "jagged": "jagged",
    "giza": "jagged",
    "shout": "jagged",
}

_FILE_RE = re.compile(r"^.+_(?P<num>\d+)\.(png|PNG)$")


def shapes_root() -> Path:
    return _ROOT


def list_templates(kind: str) -> list[Path]:
    key = (kind or "").replace("_", "-").lower()
    dirname = SHAPE_DIRS.get(key, key)
    d = _ROOT / dirname
    if not d.is_dir():
        return []
    files = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() != ".png":
            continue
        if p.name.startswith("."):
            continue
        files.append(p)
    return files


def pick_template_path(
    kind: str,
    *,
    seed: int = 0,
    template_id: str | None = None,
) -> Path | None:
    paths = list_templates(kind)
    if not paths:
        return None
    if template_id:
        tid = str(template_id).strip().lower().replace("_", "-")
        for p in paths:
            stem = p.stem.lower().replace("_", "-")
            if stem == tid or tid in stem:
                return p
            if tid.isdigit() and stem.endswith(f"-{int(tid):02d}"):
                return p
    return paths[int(seed) % len(paths)]


def _white_bg_to_rgba(im: Image.Image) -> Image.Image:
    gray = im.convert("L")
    w, h = gray.size
    work = gray.point(lambda v: 255 if v > 240 else 0)
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        try:
            ImageDraw.floodfill(work, xy, 128, thresh=10)
        except Exception:
            pass
    rgba = Image.new("RGBA", (w, h))
    g = gray.load()
    m = work.load()
    out = rgba.load()
    for y in range(h):
        for x in range(w):
            if m[x, y] == 128:
                out[x, y] = (255, 255, 255, 0)
            else:
                v = g[x, y]
                if v < 80:
                    out[x, y] = (0, 0, 0, 255)
                else:
                    out[x, y] = (255, 255, 255, 255)
    return rgba


@lru_cache(maxsize=64)
def load_template(path_str: str) -> Image.Image:
    path = Path(path_str)
    im = Image.open(path)
    if im.mode == "RGBA":
        px = im.getpixel((0, 0))
        if len(px) == 4 and px[3] > 250 and px[0] > 250:
            return _white_bg_to_rgba(im.convert("L"))
        return im.copy()
    return _white_bg_to_rgba(im)


def fit_template_to_bbox(
    template: Image.Image,
    bbox: tuple[float, float, float, float],
) -> tuple[Image.Image, tuple[int, int]]:
    x1, y1, x2, y2 = bbox
    tw = max(1, int(round(x2 - x1)))
    th = max(1, int(round(y2 - y1)))
    pad = max(2, int(min(tw, th) * 0.03))
    scaled = template.resize((tw + pad * 2, th + pad * 2), Image.Resampling.LANCZOS)
    return scaled, (int(round(x1)) - pad, int(round(y1)) - pad)
