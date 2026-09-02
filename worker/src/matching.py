"""Hashed denylist matching.

Pure functions. Stdlib only. No I/O at import time.

The repo is public, so the denylist ships as SHA-256 digests rather than
plaintext. Matching hashes each candidate token (and, for longer terms,
each bounded substring) and tests membership.

Two passes: word-boundary (every term), then separator-stripped substring
(terms >= substr_minlen only). Short terms are excluded from the substring
pass because they appear innocently inside longer words ('ass' in
'assassin', 'cock' in 'peacock') and no allowlist can enumerate every
word in English — the accepted cost is missing a short term broken up by
punctuation inside a sentence.

The allowlist is subtracted BEFORE candidates are generated, so the
substring pass can't re-expose a term inside a safe word (e.g.
'Scunthorpe, England' stripping to 'scunthorpeengland').
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

    utf-8-sig so a BOM doesn't turn the header comment into a digest.
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
                # boundary-less search misreads it.
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

    Entries are escaped — an allowlist is literal text, and an unescaped
    '.' would delete a real term from the message.
    """
    for word in allow:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    return text


def contains_blocked(
    text: str, blocklist: Blocklist, allow: frozenset[str]
) -> bool:
    """True when any reading of `text` contains a blocked term."""
    # Short-circuit on cost, not correctness: committed blocked.txt is
    # header-only until real digests are generated, and scanning a 450-char
    # message against nothing still costs ~17ms of hashing per submission.
    if not blocklist.digests:
        return False

    cleaned = _subtract_allowed(normalize(text), allow)

    for form in candidates(cleaned):
        # REFACTOR: split into named _word_pass()/_substring_pass() helpers
        for word in _WORD.findall(form):
            if blocklist.minlen <= len(word) <= blocklist.maxlen:
                if _digest_normalized(word) in blocklist.digests:
                    return True

        # Stripped so both sides compare alphanumeric-only, matching how
        # hash_terms.py canonicalizes terms.
        stripped = strip_nonalnum(form)
        low = max(blocklist.substr_minlen, 1)
        for size in range(low, blocklist.maxlen + 1):
            for start in range(0, len(stripped) - size + 1):
                chunk = stripped[start:start + size]
                if _digest_normalized(chunk) in blocklist.digests:
                    return True

    return False
