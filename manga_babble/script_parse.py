"""Parse human script format (docs/script-format.md) → lines.json structure."""

from __future__ import annotations

import re
from typing import Any

from manga_babble import SCHEMA_VERSION

_PAGE_RE = re.compile(r"^page\s*(\d+)\s*$", re.I)
# [1] / [枠外] / [4][枠外]（コマ付き注釈）
_PANEL_RE = re.compile(
    r"^\[\s*([0-9０-９]+|枠外)\s*\](?:\s*\[\s*(枠外)\s*\])?\s*$"
)
_LINE_RE = re.compile(
    r'^(?P<speaker>\S+)\s+"(?P<text>(?:\\.|[^"\\])*)"\s*(?P<shape>\S+)?\s*$'
)
_BARE_NOTE_RE = re.compile(r"^(※|＊|\*).+")

_ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def _norm_num(s: str) -> int:
    return int(s.translate(_ZEN))


def parse_script(text: str) -> dict[str, Any]:
    """
    Parse script text into {schema_version, page, lines, options}.
    """
    page_id = "page1"
    panel_index: int | None = None
    in_margin = False
    lines: list[dict[str, Any]] = []
    order = 0
    panel_orders: dict[int, int] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = _PAGE_RE.match(line)
        if m:
            page_id = f"page{int(m.group(1))}"
            continue

        m = _PANEL_RE.match(line)
        if m:
            tag = m.group(1)
            margin_suffix = m.group(2)  # second [枠外] if present
            if tag == "枠外" or margin_suffix == "枠外":
                in_margin = True
                # [4][枠外] keeps association with panel 4 when useful later
                if tag != "枠外":
                    panel_index = _norm_num(tag)
                else:
                    panel_index = None
            else:
                in_margin = False
                panel_index = _norm_num(tag)
            continue

        m = _LINE_RE.match(line)
        if m:
            speaker = m.group("speaker")
            body = m.group("text").replace('\\"', '"')
            shape = (m.group("shape") or "normal").lower()
            entry: dict[str, Any] = {
                "id": f"l{order}",
                "text": body,
                "order": order,
                "type": shape,
            }
            if speaker in ("ナレーション", "ナレ", "narration"):
                entry["speaker"] = None
                if shape == "normal":
                    entry["type"] = "narration"
            else:
                entry["speaker"] = speaker

            if in_margin:
                entry["meta"] = {"placement": "page_margin"}
                entry["type"] = entry.get("type") or "narration"
            elif panel_index is not None:
                entry["panel_index"] = panel_index
                # order within panel for slots
                po = panel_orders.get(panel_index, 0)
                entry["order"] = order
                entry["meta"] = {"panel_order": po}
                panel_orders[panel_index] = po + 1

            lines.append(entry)
            order += 1
            continue

        if in_margin or _BARE_NOTE_RE.match(line):
            lines.append(
                {
                    "id": f"l{order}",
                    "text": line,
                    "order": order,
                    "type": "narration",
                    "meta": {"placement": "page_margin"},
                }
            )
            order += 1
            continue

    return {
        "schema_version": SCHEMA_VERSION,
        "page": {"id": page_id},
        "lines": lines,
        "options": {"style": "default", "seed": 0},
    }


def parse_script_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return parse_script(f.read())
