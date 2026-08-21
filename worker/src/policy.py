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
# broad: a false positive costs the visitor a rephrase, while a miss hands
# a link spammer the payload the whole policy exists to deny.
#
# That bias settles two judgement calls in the pattern:
#
#   * No word boundary before the host. '_spam.com' is a link, and an
#     anchor there is a one-character evasion.
#   * No lookahead after the TLD. Forbidding a following '.' -- as an
#     earlier draft did -- means 'visit spam.com.' matches nothing at
#     all, because the only candidate span is the one the lookahead
#     rejects. The cost of dropping it is that a missing space after a
#     full stop ('Cool site.Thanks!') reads as a domain.
#
# The trailing \b is load-bearing in the other direction: it keeps
# 'song.mp3' from reading as a host, since a TLD does not end in a digit.
_URL = re.compile(
    r"https?://"
    r"|www\."
    r"|[a-z0-9-]+\.[a-z]{2,63}\b",
    re.IGNORECASE,
)

# Zero-width characters and the soft hyphen, kept in step with
# normalize.ZERO_WIDTH. policy.py does not import normalize (see the
# module layering in plans/2026-08-20-guestbook.md), and a drifted copy
# can only ever affect what counts as blank -- never what matches.
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

    normalize.py documents this module as the type boundary: everything
    downstream assumes str. entry.py coerces the JSON body before calling
    in, so this is the backstop, not the gate.
    """
    if not isinstance(text, str):
        raise TypeError(f"{field} must be a str")
    return _BLANK_EDGE.sub("", text)


def check_name(
    name: str, *, blocklist: Blocklist, allow: frozenset[str]
) -> Verdict:
    """Validate a submitted name. Slurs, URLs, and length only.

    The length cap deliberately runs BEFORE contains_blocked, which hashes
    every bounded substring of what it is given: the cap is what bounds
    that cost, and under Pyodide the difference is not academic.

    Ordering the empty check against the length check is an equivalent
    mutation, not an untested branch -- the trimmed name is empty exactly
    when its length is 0, so the two conditions can never both be true
    and no input can tell the two orders apart. Verified: no test kills
    that swap, and none should be invented to pretend otherwise.
    """
    # Rebound, not copied to a second name: the untrimmed text is then
    # unreachable below, and every check runs on the same string the
    # length cap measured. Handing the raw text to contains_blocked
    # returns the same verdict -- the matcher is blind to edge
    # whitespace -- but scans padding the cap already excluded.
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

    The returned `display` is the swapped text. The RAW message is what the
    caller stores; this function never rewrites what gets persisted.

    Same ordering as check_name, and the same parameter rebinding, for
    the same reasons; plus one more: the swap runs only after every check
    has passed, so a rejected message is never rewritten on its way to
    the audit table.
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
