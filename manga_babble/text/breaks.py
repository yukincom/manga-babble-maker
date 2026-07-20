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

# Note: long vowel ー (U+30FC) is NOT treated as katakana for script-boundary splits
_KATAKANA = re.compile(r"[\u30a1-\u30fa\u30fd\u30fe]")  # ァ-ヺ ヽヾ (no ー)
_HIRAGANA = re.compile(r"[\u3041-\u3096\u309d\u309e]")
_KANJI = re.compile(r"[\u4e00-\u9fff]")
# Attach to previous char / never start a column alone
_ATTACH_LEAD = re.compile(r"^[ーｰ−‐–—〜～！？!?。、．，…‥・]+")
_LONG_VOWEL = set("ーｰ−‐–—")

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
    """Insert boundary when script switches to katakana — never before ー."""
    out: list[str] = []
    for i, ch in enumerate(s):
        if ch in _LONG_VOWEL:
            out.append(ch)
            continue
        if i > 0 and _KATAKANA.match(ch) and not _KATAKANA.match(s[i - 1]):
            prev = s[i - 1]
            if prev in _LONG_VOWEL:
                out.append(ch)
                continue
            if _HIRAGANA.match(prev) or _KANJI.match(prev):
                out.append("\x1e")
        out.append(ch)
    return "".join(out)


def _reattach_orphans(parts: list[str]) -> list[str]:
    """Merge chunks that only start with long-vowel/punct into previous chunk."""
    if not parts:
        return parts
    merged: list[str] = [parts[0]]
    for p in parts[1:]:
        if _ATTACH_LEAD.match(p) or (p and all(c in _LONG_VOWEL or c in "！？!?。、．，…‥・" for c in p)):
            merged[-1] = merged[-1] + p
        else:
            merged.append(p)
    return merged


def _safety(
    parts: list[str],
    max_chars: int,
    *,
    allow_midword: bool,
) -> list[str]:
    parts = _reattach_orphans([p for p in parts if p])
    result: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            result.append(p)
            continue
        soft = _light_structural(p)
        soft = _reattach_orphans(soft)
        if len(soft) > 1:
            result.extend(_safety(soft, max_chars, allow_midword=allow_midword))
            continue
        if allow_midword:
            for i in range(0, len(p), max_chars):
                result.append(p[i : i + max_chars])
        else:
            # Keep intact rather than shred particles
            result.append(p)
    return _reattach_orphans(result or parts)
