"""Render-time profanity softening.

Profanity is permitted and stored raw. This module rewrites it for display
only, so the policy stays reversible and the original is never lost.

Deliberately does NOT use normalize.candidates(). Detection asks whether
any reading of a string contains a term; swapping must rewrite one span
inside the user's own text and leave every other byte alone. Normalized
input would produce normalized output and destroy their message.
"""
import re
from collections.abc import Mapping

_COMMENT = "#"
_SEPARATOR = "="


def load_swaps(path: str) -> dict[str, str]:
    """Parse `term = replacement` lines. Missing file yields {}."""
    swaps: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return swaps

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(_COMMENT):
            continue
        if _SEPARATOR not in stripped:
            continue
        term, _, replacement = stripped.partition(_SEPARATOR)
        term, replacement = term.strip(), replacement.strip()
        if term and replacement:
            swaps[term.casefold()] = replacement
    return swaps


def _match_case(original: str, replacement: str) -> str:
    """Reshape `replacement` to the case pattern of `original`."""
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def apply_swaps(text: str, swaps: Mapping[str, str]) -> tuple[str, bool]:
    """Return (display_text, did_swap).

    Matches on word boundaries so 'shitake' is untouched. Every byte that
    is not part of a match is preserved exactly.
    """
    if not text or not swaps:
        return text, False

    # Longest terms first so a term containing another is matched whole.
    ordered = sorted(swaps, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(term) for term in ordered) + r")\b",
        re.IGNORECASE,
    )

    did_swap = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal did_swap
        did_swap = True
        found = match.group(0)
        return _match_case(found, swaps[found.casefold()])

    return pattern.sub(substitute, text), did_swap
