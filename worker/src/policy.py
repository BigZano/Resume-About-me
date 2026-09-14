"""Content policy orchestration.

Pure functions. Stdlib only. Wordlists are injected, never read here.

Names are checked for slurs, URLs, and length ONLY. No profanity check and
no joke-name list: 'James Cockburn' is a real surname and 'Mike Hawk' is a
joke the site owner finds funny. Blocking either costs more than it saves.
See specs/2026-08-20-guestbook-design.md section 6.4.
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass

from matching import Blocklist, contains_blocked
from swaps import apply_swaps

MAX_NAME = 40
MAX_MESSAGE = 500

# Scheme, www., or a bare domain with a known-ish TLD shape. Deliberately
# broad — a miss hands a spammer the payload this policy exists to deny.
# No word boundary before the host ('_spam.com' still counts), and no
# lookahead after the TLD (rejecting a trailing '.' made 'visit spam.com.'
# match nothing, since that's the only candidate span). Trailing \b keeps
# 'song.mp3' from reading as a host, since a TLD never ends in a digit.
_URL = re.compile(
    r"https?://"
    r"|www\."
    r"|[a-z0-9-]+\.[a-z]{2,63}\b",
    re.IGNORECASE,
)

# Zero-width characters and the soft hyphen, kept in step with
# normalize.ZERO_WIDTH (this module doesn't import normalize — see the
# layering in plans/2026-08-20-guestbook.md).
_INVISIBLE = "​‌‍﻿­"
_BLANK_EDGE = re.compile(rf"^[\s{_INVISIBLE}]+|[\s{_INVISIBLE}]+$")


@dataclass(frozen=True)
class Verdict:
    """Outcome of a policy check.

    `display` carries the render-ready text when ok, and None when not.
    """

    ok: bool
    code: str | None
    display: str | None
    has_swap: bool


def contains_url(text: str) -> bool:
    """True when `text` contains anything that reads as a link."""
    return bool(_URL.search(text))


def _cleaned(text: str, field: str) -> str:
    """Trim blank edges, and refuse anything that is not text.

    This is the type boundary — everything downstream assumes str.
    """
    if not isinstance(text, str):
        raise TypeError(f"{field} must be a str")
    return _BLANK_EDGE.sub("", text)


def check_name(
    name: str, *, blocklist: Blocklist, allow: frozenset[str]
) -> Verdict:
    """Validate a submitted name. Slurs, URLs, and length only.

    The length cap runs BEFORE contains_blocked, which hashes every
    bounded substring it's given — the cap bounds that cost, and under
    Pyodide the difference isn't academic.
    """
    name = _cleaned(name, "name")

    if not name:
        return Verdict(ok=False, code="empty", display=None, has_swap=False)
    if len(name) > MAX_NAME:
        return Verdict(
            ok=False, code="name_too_long", display=None, has_swap=False
        )
    if contains_url(name):
        return Verdict(
            ok=False, code="url_not_allowed", display=None, has_swap=False
        )
    if contains_blocked(name, blocklist, allow):
        return Verdict(ok=False, code="blocked", display=None, has_swap=False)

    return Verdict(ok=True, code=None, display=name, has_swap=False)


def check_message(
    message: str,
    *,
    blocklist: Blocklist,
    allow: frozenset[str],
    swaps: Mapping[str, str],
) -> Verdict:
    """Validate a submitted message and produce its display form.

    `display` is the swapped text; the caller stores the raw message, not
    this. Same ordering as check_name, plus: the swap runs only after every
    check passes, so a rejected message is never rewritten en route to the
    audit table.
    """
    message = _cleaned(message, "message")

    if not message:
        return Verdict(ok=False, code="empty", display=None, has_swap=False)
    if len(message) > MAX_MESSAGE:
        return Verdict(
            ok=False, code="message_too_long", display=None, has_swap=False
        )
    if contains_url(message):
        return Verdict(
            ok=False, code="url_not_allowed", display=None, has_swap=False
        )
    if contains_blocked(message, blocklist, allow):
        return Verdict(ok=False, code="blocked", display=None, has_swap=False)

    display, has_swap = apply_swaps(message, swaps)
    return Verdict(ok=True, code=None, display=display, has_swap=has_swap)
