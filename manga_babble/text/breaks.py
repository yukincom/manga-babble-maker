"""Split dialogue text into display chunks.

Primary path (recommended):
  Agent / human inserts explicit break markers in the text.
  Supported: fullwidth space　, slash /, newline.

Code does NOT maintain open-ended connective dictionaries.
Fallback without markers: keep as one chunk (or very light structural hints only).

page_margin: wrap only if len >= 12; avoid mid-word cuts.
"""

from __future__ import annotations

import re
from typing import Any

from manga_babble.text.profile import BreakProfile, resolve_break_profile

# Explicit break markers (agent skill should insert these)
# 　 = editorial space, / = explicit break token, newlines
_EXPLICIT_SPLIT = re.compile(r"(?:[\u3000\u00a0]+|/+|\n+|\r+)")

_KATAKANA = re.compile(r"[\u30a0-\u30ffー]")
_HIRAGANA = re.compile(r"[\u3040-\u309fー]")
_KANJI = re.compile(r"[\u4e00-\u9fff]")

# Closed small set — structural only, not open-ended connectives
_DEMONSTRATIVE_HEAD = re.compile(
    r"(?<=[ぁ-んァ-ン一-龥])(?=(?:これ|それ|あれ|どれ))"
)


def split_text_to_chunks(
    text: str,
    *,
    profile: BreakProfile | None = None,
    options: dict[str, Any] | None = None,
    speaker: str | None = None,
    line_meta: dict[str, Any] | None = None,
    placement: str | None = None,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    line_meta = line_meta or {}
    place = placement or line_meta.get("placement")

    if place == "page_margin":
        return _split_margin_note(text)

    prof = profile or resolve_break_profile(
        options, speaker=speaker, line_meta=line_meta
    )

    # 1) Explicit markers from agent/human — authoritative
    if _EXPLICIT_SPLIT.search(text):
        parts = [p.strip() for p in _EXPLICIT_SPLIT.split(text) if p.strip()]
        return _safety(parts, prof.chunk_max_chars, allow_midword=False)

    # 2) Minimal structural fallback only (no connective lexicon)
    parts = _light_structural(text)
    return _safety(parts, prof.chunk_max_chars, allow_midword=prof.allow_midword_split)


def _split_margin_note(text: str) -> list[str]:
    text = text.strip()
    n = len(re.sub(r"\s+", "", text))
    if n < 12:
        return [text]
    if _EXPLICIT_SPLIT.search(text):
        return [p.strip() for p in _EXPLICIT_SPLIT.split(text) if p.strip()]
    parts = _light_structural(text)
    return _safety(parts, max_chars=12, allow_midword=False)


def _light_structural(text: str) -> list[str]:
    """
    Tiny closed heuristics when agent did not insert breaks.
    Prefer one chunk over shredding.
    """
    work = _split_kana_to_katakana(text)
    work = _DEMONSTRATIVE_HEAD.sub("\x1e", work)
    parts = [p.strip() for p in re.split(r"[\x1e\n]+", work) if p.strip()]
    return parts or [text]


def _split_kana_to_katakana(s: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(s):
        if i > 0 and _KATAKANA.match(ch) and not _KATAKANA.match(s[i - 1]):
            if _HIRAGANA.match(s[i - 1]) or _KANJI.match(s[i - 1]):
                out.append("\x1e")
        out.append(ch)
    return "".join(out)


def _safety(
    parts: list[str],
    max_chars: int,
    *,
    allow_midword: bool,
) -> list[str]:
    result: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            result.append(p)
            continue
        soft = _light_structural(p)
        if len(soft) > 1:
            result.extend(_safety(soft, max_chars, allow_midword=allow_midword))
            continue
        if allow_midword:
            for i in range(0, len(p), max_chars):
                result.append(p[i : i + max_chars])
        else:
            # Keep intact rather than shred particles
            result.append(p)
    return result or parts
