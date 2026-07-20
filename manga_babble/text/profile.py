"""Genre / tension / voice → numeric break parameters (no work titles or cast names)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BreakProfile:
    """How aggressively to split when no explicit　breaks exist."""

    genre: str = "default"
    tension: str = "mid"
    voice: str = "normal"
    chunk_max_chars: int = 8
    target_lines_soft: int = 3
    allow_midword_split: bool = False


# Valid enums only — no series-specific labels
_GENRES = frozenset({"default", "action", "read", "mixed"})
_TENSIONS = frozenset({"low", "mid", "high"})
_VOICES = frozenset({"dense", "normal", "sparse"})

# Base chunk max by genre (chars per chunk, soft)
_GENRE_CHUNK = {
    "default": 8,
    "action": 5,
    "read": 12,
    "mixed": 7,
}
_GENRE_LINES = {
    "default": 3,
    "action": 4,
    "read": 3,
    "mixed": 4,
}


def resolve_break_profile(
    options: dict[str, Any] | None = None,
    *,
    speaker: str | None = None,
    line_meta: dict[str, Any] | None = None,
) -> BreakProfile:
    """
    Build profile from page options + per-line / per-speaker overrides.

    Priority for voice:
      line_meta.voice > options.speakers[speaker].voice > options.voice > normal
    """
    options = options or {}
    line_meta = line_meta or {}

    genre = str(options.get("genre") or "default").lower()
    if genre not in _GENRES:
        genre = "default"

    tension = str(options.get("tension") or "mid").lower()
    if tension not in _TENSIONS:
        tension = "mid"

    voice = "normal"
    if options.get("voice") in _VOICES:
        voice = str(options["voice"])
    speakers = options.get("speakers") or {}
    if speaker and isinstance(speakers, dict) and speaker in speakers:
        sv = speakers[speaker]
        if isinstance(sv, dict) and sv.get("voice") in _VOICES:
            voice = str(sv["voice"])
        elif isinstance(sv, str) and sv in _VOICES:
            voice = sv
    if line_meta.get("voice") in _VOICES:
        voice = str(line_meta["voice"])

    chunk = _GENRE_CHUNK[genre]
    lines = _GENRE_LINES[genre]

    # tension: high → shorter chunks, more lines
    if tension == "high":
        chunk = max(3, int(chunk * 0.65))
        lines = min(6, lines + 1)
    elif tension == "low":
        chunk = int(chunk * 1.25)
        lines = max(2, lines - 1)

    # voice
    if voice == "dense":
        chunk = max(3, int(chunk * 0.7))
        lines = min(6, lines + 1)
    elif voice == "sparse":
        chunk = int(chunk * 1.35)
        lines = max(2, lines - 1)

    allow_mid = bool(options.get("allow_midword_split", False))
    if line_meta.get("allow_midword_split") is not None:
        allow_mid = bool(line_meta["allow_midword_split"])
    elif genre in ("action", "mixed") and tension == "high":
        allow_mid = True

    return BreakProfile(
        genre=genre,
        tension=tension,
        voice=voice,
        chunk_max_chars=max(3, chunk),
        target_lines_soft=max(1, lines),
        allow_midword_split=allow_mid,
    )
