"""Resolve speech tone and bubble shape (kept as separate concepts).

tone  = 役割・雰囲気（normal / shout / thought / whisper / narration）
shape = 見た目（ellipse / jagged / cloud / dashed-ellipse / v-rect / …）

台本の末尾トークンは主に shape 名（normal, giza, kumo, whisper, narration…）。
「ナレーション」話者や ※ は tone=narration 側。
"""

from __future__ import annotations

import re
from typing import Any

from manga_babble.schema import VALID_TONES

# True synonyms of tone only (not shapes)
_TONE_ALIASES = {
    "scream": "shout",
    "yell": "shout",
    "think": "thought",
    "monologue": "thought",
    "inner": "thought",
    "narrate": "narration",
    "narr": "narration",
    "note": "narration",
}

# Script trailing token → (canonical_shape, default_tone)
# Keep this table small: one preferred name per look.
#
# IMPORTANT (field survey): cloud / kumo is for bright・playful spoken voice,
# NOT internal monologue (thought). Popular comics often do NOT use cloud
# balloons for 心の声. Thought defaults to ellipse + trail dots.
_SHAPE_TOKENS: dict[str, tuple[str, str]] = {
    "normal": ("ellipse", "normal"),
    "giza": ("jagged", "shout"),
    # 楽しい・明るい発話用雲（心の声ではない）
    "fun-cloud": ("fun-cloud", "normal"),
    "fun_cloud": ("fun-cloud", "normal"),
    "kumo": ("fun-cloud", "normal"),  # legacy alias
    "cloud": ("fun-cloud", "normal"),  # legacy alias
    "thought": ("ellipse", "thought"),  # 心の声 → 楕円＋丸連なり
    "whisper": ("dashed-ellipse", "whisper"),
    "narration": ("v-rect", "narration"),
}


def is_page_margin_line(line: dict[str, Any]) -> bool:
    """※ notes or explicit placement → outside panel."""
    meta = line.get("meta") or {}
    if meta.get("placement") in ("page_margin", "outside", "outside_frame"):
        return True
    if line.get("placement") in ("page_margin", "outside", "outside_frame"):
        return True
    text = str(line.get("text") or "").strip()
    if text.startswith("※") or text.startswith("*"):
        return True
    return False


def resolve_tone(line: dict[str, Any]) -> tuple[str, str]:
    """Backward-compatible: returns (tone, source). Prefer resolve_style()."""
    tone, _shape, source = resolve_style(line)
    return tone, source


def resolve_style(line: dict[str, Any]) -> tuple[str, str, str]:
    """
    Returns (tone, shape, source).

    Priority:
      1) explicit line["shape"]
      2) line["type"] as tone synonym, tone name, or shape token
      3) text / speaker rules
      4) defaults
    """
    source = "default"
    shape: str | None = None
    tone: str | None = None

    raw_shape = line.get("shape")
    if raw_shape is not None and str(raw_shape).strip() != "":
        key = _norm_token(raw_shape)
        if key in _SHAPE_TOKENS:
            shape, tone_from_shape = _SHAPE_TOKENS[key]
            tone = tone_from_shape
            source = "explicit"
        else:
            # Allow raw canonical shapes: ellipse, jagged, v-rect, …
            shape = key
            source = "explicit"

    raw_type = line.get("type")
    if raw_type is not None and str(raw_type).strip() != "":
        key = _norm_token(raw_type)
        source = "explicit"
        if key in _TONE_ALIASES:
            tone = _TONE_ALIASES[key]
            if shape is None:
                shape = _default_shape_for_tone(tone)
        elif key in VALID_TONES:
            tone = key
            if shape is None:
                shape = _default_shape_for_tone(tone)
        elif key in _SHAPE_TOKENS:
            s, tone_from_shape = _SHAPE_TOKENS[key]
            shape = shape or s
            if tone is None:
                tone = tone_from_shape
        else:
            if tone is None:
                tone = "normal"
            if shape is None:
                shape = "ellipse"

    if is_page_margin_line(line):
        if tone is None:
            tone = "narration"
            source = "rule" if source == "default" else source
        if shape is None:
            shape = "v-rect"

    speaker = str(line.get("speaker") or "").strip()
    if tone is None and speaker in ("ナレーション", "narration", "ナレ"):
        tone = "narration"
        shape = shape or "v-rect"
        source = "rule"

    if tone is None:
        text = str(line.get("text") or "")
        ruled = _from_text(text)
        if ruled:
            tone = ruled
            source = "rule"
            if shape is None:
                shape = _default_shape_for_tone(tone)

    if tone is None:
        tone = "normal"
    if shape is None:
        shape = _default_shape_for_tone(tone)

    if tone not in VALID_TONES:
        tone = "normal"

    return tone, shape, source


def _norm_token(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "-").replace("_", "-")


def _default_shape_for_tone(tone: str) -> str:
    return {
        "normal": "ellipse",
        "shout": "jagged",
        "whisper": "dashed-ellipse",
        "thought": "ellipse",  # not cloud; 心の声 is usually oval + dots
        "narration": "v-rect",
    }.get(tone, "ellipse")


def _from_text(text: str) -> str | None:
    s = text.strip()
    if not s:
        return None

    if s.startswith("※") or s.startswith("*"):
        return "narration"

    if (s.startswith("（") and s.endswith("）")) or (
        s.startswith("(") and s.endswith(")")
    ):
        return "thought"

    if s.startswith("――") or s.startswith("──") or s.startswith("…『"):
        return "narration"
    if re.match(r"^[【\[]", s) and re.search(r"[】\]]$", s):
        return "narration"

    if "（小声）" in s or "（囁" in s or "(whisper)" in s.lower():
        return "whisper"

    bangs = s.count("！") + s.count("!")
    if bangs >= 2:
        return "shout"

    return None
