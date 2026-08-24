"""Text normalization for the content policy.

Pure functions. Stdlib only. No I/O, no network, no Cloudflare.

A naive denylist is beaten by leetspeak, accents, homoglyphs, zero-width
joiners, spacing, and repeated characters. Rather than pick one canonical
form and hope, `candidates()` returns every plausible reading of the input
so the matcher can check them all. Transforms are ADDITIVE: the plain
normalized form is always in the set, so a destructive deleet pass can
never mangle a numeric term out of existence before it is matched.

Every public function takes `str`. Anything else raises TypeError; the
request boundary (worker/src/policy.py) validates types before calling in.
"""
import itertools
import unicodedata

# Zero-width and invisible characters used to break up words.
ZERO_WIDTH = "​‌‍﻿­"

# Non-Latin characters that render identically to Latin ones. NFKD does
# not fold these — Cyrillic 'а' is a genuinely different letter, not a
# decomposition of 'a' — so they need an explicit table.
CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "і": "i", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ɡ": "g",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v",
    "τ": "t", "Β": "b", "Κ": "k",
}

DELEET = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
    "|": "l", "+": "t",
}

_ZW_TABLE = str.maketrans("", "", ZERO_WIDTH)

# Keyed on the CASEFOLDED source, and applied after casefold(), so that
# uppercase homoglyphs fold too. Applying the table before casefold would
# miss capital Cyrillic А/Е/О/С entirely — the most obvious homoglyph
# attack there is — because casefold maps them to Cyrillic lowercase, not
# to Latin. Folding first collapses both cases onto one table key.
_CONFUSABLE_TABLE = str.maketrans(
    {src.casefold(): dst for src, dst in CONFUSABLES.items()}
)

_DELEET_TABLE = str.maketrans(DELEET)


def normalize(text: str) -> str:
    """Fold `text` to a comparable base form.

    NFKD, drop combining marks, drop invisibles, casefold, map confusables.
    Idempotent.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    cleaned = without_marks.translate(_ZW_TABLE)
    return cleaned.casefold().translate(_CONFUSABLE_TABLE)


def strip_nonalnum(text: str) -> str:
    """Drop everything that is not a letter or digit."""
    return "".join(c for c in text if c.isalnum())


def _collapse(text: str, keep: int) -> str:
    """Collapse runs of the same character down to at most `keep`."""
    return "".join(
        char * min(len(tuple(run)), keep)
        for char, run in itertools.groupby(text)
    )


def candidates(text: str) -> frozenset[str]:
    """Every plausible reading of `text`, for the matcher to check.

    Bounded: the result size depends on the number of transforms, never on
    input length. At most 16 forms.
    """
    base = normalize(text)
    forms = {base, base.translate(_DELEET_TABLE)}

    # Strip separators BEFORE collapsing, so a run broken up by them
    # ('w o o o o r d') becomes adjacent and can still be collapsed.
    forms |= {strip_nonalnum(form) for form in forms}

    # Collapse both to 1 (catches 'wooord') and to 2 (preserves 'less').
    for form in list(forms):
        forms.add(_collapse(form, 1))
        forms.add(_collapse(form, 2))

    # Strip again: collapsing a form that still held separators can expose
    # a spelling the first strip could not see ('aa aa aa' -> 'aaa').
    forms |= {strip_nonalnum(form) for form in forms}

    return frozenset(forms)
