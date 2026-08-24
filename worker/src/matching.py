"""Hashed denylist matching.

Pure functions. Stdlib only. No I/O at import time.

The repo is public, so the denylist ships as SHA-256 digests rather than
plaintext. Matching hashes each candidate token (and, for longer terms,
each bounded substring) and tests membership.

Two passes, with deliberately different minimum lengths:

  1. Word-boundary pass, using every term.
  2. Separator-stripped substring pass, using only terms of length
     >= substr_minlen.

Short terms are the ones that appear innocently inside longer words --
'ass' in 'assassin', 'cock' in 'peacock', 'tit' in 'titles'. Once
separators are stripped the word boundaries are gone, so a 3-character
term scanned as a substring would fire constantly on ordinary text, and
no allowlist can enumerate every word in English. The accepted cost is
that a short term broken up by punctuation *inside a sentence* is missed;
see src/tests/test_gb_matching.py.

The allowlist is subtracted BEFORE candidates are generated. Doing it
after would let the separator-stripped pass re-expose the term inside the
safe word: 'Scunthorpe, England' strips to 'scunthorpeengland', which no
whole-word allowlist entry can match any more.
"""
import hashlib
import re
from dataclasses import dataclass

from normalize import candidates, normalize, strip_nonalnum

_COMMENT = "#"
_HEADER_KEYS = ("minlen", "maxlen", "substr_minlen")

# Words, for the boundary pass. Digits included: a term may contain them,
# and normalize() has already folded everything else to [a-z0-9].
_WORD = re.compile(r"[a-z0-9]+")

# Used when the digest file carries no header, or cannot be read at all.
# minlen/maxlen bound the word pass; substr_minlen gates the substring
# pass. hash_terms.py writes the real values from the real term list.
_DEFAULT_MINLEN = 3
_DEFAULT_MAXLEN = 14
_DEFAULT_SUBSTR_MINLEN = 5


@dataclass(frozen=True)
class Blocklist:
    """Digests plus the length bounds needed to drive the substring pass."""

    digests: frozenset[str]
    minlen: int
    maxlen: int
    substr_minlen: int


def digest(term: str) -> str:
    """SHA-256 hex of the normalized term."""
    return _digest_normalized(normalize(term))


def _digest_normalized(text: str) -> str:
    """Hash text that is already normalized, skipping a redundant fold."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_lines(path: str) -> list[str]:
    """Lines of a UTF-8 wordlist. An unusable file reads as no lines.

    utf-8-sig so an editor-added byte order mark does not turn the header
    comment into a digest.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.readlines()
    except OSError:
        return []


def load_blocked(path: str) -> Blocklist:
    """Read the digest file. An unusable file yields an empty blocklist."""
    bounds = {
        "minlen": _DEFAULT_MINLEN,
        "maxlen": _DEFAULT_MAXLEN,
        "substr_minlen": _DEFAULT_SUBSTR_MINLEN,
    }
    digests: set[str] = set()

    for line in _read_lines(path):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT):
            for key in _HEADER_KEYS:
                # \b matters: 'substr_minlen' ends in 'minlen', so a
                # boundary-less search reads the wrong number whenever
                # substr_minlen comes first in the header.
                match = re.search(rf"\b{key}=(\d+)", stripped)
                if match:
                    bounds[key] = int(match.group(1))
            continue
        digests.add(stripped.lower())

    return Blocklist(
        frozenset(digests),
        bounds["minlen"],
        bounds["maxlen"],
        bounds["substr_minlen"],
    )


def load_allow(path: str) -> frozenset[str]:
    """Read the plaintext false-positive allowlist.

    Entries are normalized the same way message text is, so an accented
    name in the file still matches the folded text.
    """
    return frozenset(
        normalize(stripped)
        for stripped in (line.strip() for line in _read_lines(path))
        if stripped and not stripped.startswith(_COMMENT)
    )


def _subtract_allowed(text: str, allow: frozenset[str]) -> str:
    """Remove allowlisted words by word boundary, before candidates exist.

    Order matters: doing this after candidate generation would let the
    separator-stripped pass see the safe word anyway. Entries are escaped
    -- an allowlist is a list of literals, and an unescaped '.' would
    delete a real term from the message.

    Substituting "" instead of " " is an equivalent mutation, not an
    untested branch: \\b only matches where the flanking character is
    outside \\w, and [a-z0-9] is a subset of \\w, so removing the span can
    never join two words that the scanners would then read as one.
    """
    for word in allow:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    return text


def contains_blocked(
    text: str, blocklist: Blocklist, allow: frozenset[str]
) -> bool:
    """True when any reading of `text` contains a blocked term."""
    # Pure short-circuit, and deliberately not covered by a behavioural
    # test: an empty digest set matches nothing either way, so removing
    # this is an equivalent mutation. It earns its place on cost. The
    # committed blocked.txt is header-only until the owner generates the
    # real digests, and scanning a 450-character message against nothing
    # costs ~17 ms of hashing per submission on CPython, more under
    # Pyodide.
    if not blocklist.digests:
        return False

    cleaned = _subtract_allowed(normalize(text), allow)

    for form in candidates(cleaned):
        # Pass 1: whole words, every term length.
        for word in _WORD.findall(form):
            if blocklist.minlen <= len(word) <= blocklist.maxlen:
                if _digest_normalized(word) in blocklist.digests:
                    return True

        # Pass 2: bounded substrings of the stripped form, longer terms
        # only. Stripping here is what makes the comparison alphanumeric
        # on both sides -- hash_terms.py canonicalizes terms the same way,
        # so a chunk spanning a separator can never be a term and is not
        # worth hashing.
        stripped = strip_nonalnum(form)
        low = max(blocklist.substr_minlen, 1)
        for size in range(low, blocklist.maxlen + 1):
            for start in range(0, len(stripped) - size + 1):
                chunk = stripped[start:start + size]
                if _digest_normalized(chunk) in blocklist.digests:
                    return True

    return False
