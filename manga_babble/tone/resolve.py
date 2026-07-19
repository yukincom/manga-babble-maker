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
}


def resolve_tone(line: dict[str, Any]) -> tuple[str, str]:
    """
    Returns (tone, source) where source is explicit | rule | default.
    """
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

    # Whisper-ish: many ellipses / small voice markers, no bang
    if "（小声）" in s or "（囁" in s or "(whisper)" in s.lower():
        return "whisper"

    bangs = s.count("！") + s.count("!")
    if bangs >= 1 and ("？" not in s[:2] and "?" not in s[:2]):
        # Strong shout if multiple bangs or short intense line
        if bangs >= 2 or len(s) <= 12:
            return "shout"

    return None
