"""Resolve bubble tone from explicit type or light text rules (no VLM)."""

from __future__ import annotations

import re
from typing import Any

from manga_babble.schema import VALID_TONES

# Explicit aliases
_ALIASES = {
    "scream": "shout",
    "yell": "shout",
    "think": "thought",
    "monologue": "thought",
    "inner": "thought",
    "narrate": "narration",
    "narr": "narration",
    "box": "narration",
    "note": "narration",
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
    """
    Returns (tone, source) where source is explicit | rule | default.
    """
    if is_page_margin_line(line) and not (
        line.get("type") and str(line.get("type")).strip()
    ):
        return "narration", "rule"

    raw = line.get("type")
    if raw is not None and str(raw).strip() != "":
        t = str(raw).strip().lower()
        t = _ALIASES.get(t, t)
        if t not in VALID_TONES:
            t = "normal"
        return t, "explicit"

    text = str(line.get("text") or "")
    rule = _from_text(text)
    if rule:
        return rule, "rule"
    return "normal", "default"


def _from_text(text: str) -> str | None:
    s = text.strip()
    if not s:
        return None

    if s.startswith("※") or s.startswith("*"):
        return "narration"

    # Full-width / half-width parens often mark thought / aside
    if (s.startswith("（") and s.endswith("）")) or (
        s.startswith("(") and s.endswith(")")
    ):
        return "thought"

    # Narration-ish markers
    if s.startswith("――") or s.startswith("──") or s.startswith("…『"):
        return "narration"
    if re.match(r"^[【\[]", s) and re.search(r"[】\]]$", s):
        return "narration"

    # Whisper-ish
    if "（小声）" in s or "（囁" in s or "(whisper)" in s.lower():
        return "whisper"

    bangs = s.count("！") + s.count("!")
    # Soft single bang stays normal; strong shout needs !! or more
    if bangs >= 2:
        return "shout"

    return None
