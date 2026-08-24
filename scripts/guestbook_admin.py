#!/usr/bin/env python3
"""Guestbook moderation.

Standalone: stdlib only, no src/ imports, runs anywhere.

    export GUESTBOOK_ADMIN_TOKEN=...
    python3 scripts/guestbook_admin.py --list
    python3 scripts/guestbook_admin.py --review
    python3 scripts/guestbook_admin.py --hide 41
    python3 scripts/guestbook_admin.py --unhide 41

--review shows entries the FILTER blocked. It is the only place a
Scunthorpe-class misfire becomes visible. When it shows a real person,
add their word to worker/src/data/allow.txt -- do not weaken the filter.

The token is read from the environment, never a CLI argument: arguments
leak into shell history and `ps`.
"""
import argparse
import hashlib
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("GUESTBOOK_API", "https://api.bretzanotelli.work")
TOKEN_VAR = "GUESTBOOK_ADMIN_TOKEN"

# worker/src/data/{allow,blocked}.txt, relative to this file. Read-only, and
# only consulted by --review; a missing repo checkout (script copied
# elsewhere, per the standalone contract above) just skips the check.
REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOW_PATH = REPO_ROOT / "worker" / "src" / "data" / "allow.txt"
BLOCKED_PATH = REPO_ROOT / "worker" / "src" / "data" / "blocked.txt"

# Mirrors worker/src/normalize.py's normalize(), restricted to the parts
# digest() actually exercises (NFKD fold, mark strip, zero-width strip,
# casefold, confusables). Duplicated rather than imported so this script
# stays standalone -- see the module docstring and Task 9's plan note. If
# worker/src/normalize.py's table changes, update this one too.
_ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u00ad"
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "і": "i", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ɡ": "g",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v",
    "τ": "t", "Β": "b", "Κ": "k",
}
_ZW_TABLE = str.maketrans("", "", _ZERO_WIDTH)
_CONFUSABLE_TABLE = str.maketrans(
    {src.casefold(): dst for src, dst in _CONFUSABLES.items()}
)


def _normalize_local(text):
    """Fold `text` the same way worker/src/normalize.py's normalize() does."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    cleaned = without_marks.translate(_ZW_TABLE)
    return cleaned.casefold().translate(_CONFUSABLE_TABLE)


def _strip_nonalnum_local(text):
    return "".join(c for c in text if c.isalnum())


def _digest_local(term):
    """sha256 hex digest matching scripts/hash_terms.py's committed output."""
    canon = _strip_nonalnum_local(_normalize_local(term))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _load_wordlist_lines(path):
    """Non-comment, non-blank lines of a wordlist. Missing file -> []."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return [
                stripped for stripped in (line.strip() for line in handle)
                if stripped and not stripped.startswith("#")
            ]
    except OSError:
        return []


def check_allow_overlap(allow_path=ALLOW_PATH, blocked_path=BLOCKED_PATH):
    """Allow-list entries that hash to an already-blocked digest.

    Task 5 noted nothing cross-checks this: such an entry silently
    nullifies that blocked term, since matching.py subtracts the allowlist
    before the denylist ever gets a look. Returns the offending entries,
    in the form they appear in allow.txt.
    """
    blocked_digests = {d.lower() for d in _load_wordlist_lines(blocked_path)}
    if not blocked_digests:
        return []
    return [
        entry for entry in _load_wordlist_lines(allow_path)
        if _digest_local(entry) in blocked_digests
    ]


def _call(path, method="GET"):
    token = os.environ.get(TOKEN_VAR)
    if not token:
        print(f"ERROR: {TOKEN_VAR} is not set", file=sys.stderr)
        raise SystemExit(2)

    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"ERROR: {exc.code} {exc.reason} for {path}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"ERROR: could not reach {API}: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from exc


def _print(entries):
    if not entries:
        print("(none)")
        return
    for entry in entries:
        flag = "HIDDEN" if entry.get("hidden") else "live  "
        reason = entry.get("block_reason") or ""
        print(f"[{entry['id']:>5}] {flag} {reason:<7} "
              f"{entry['created_at']}  {entry['name']}")
        print(f"          {entry['message']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                        help="show live entries")
    group.add_argument("--review", action="store_true",
                        help="show entries the filter blocked")
    group.add_argument("--all", action="store_true",
                        help="show everything, hidden included")
    group.add_argument("--hide", metavar="ID", help="hide an entry")
    group.add_argument("--unhide", metavar="ID", help="restore an entry")
    args = parser.parse_args()

    if args.hide:
        _call(f"/admin/entries/{args.hide}/hide", "POST")
        print(f"Hid entry {args.hide}")
        return 0

    if args.unhide:
        _call(f"/admin/entries/{args.unhide}/unhide", "POST")
        print(f"Restored entry {args.unhide}")
        return 0

    entries = _call("/admin/entries").get("entries", [])

    if args.list:
        _print([e for e in entries if not e.get("hidden")])
    elif args.review:
        blocked = [e for e in entries if e.get("block_reason") == "slur"]
        _print(blocked)
        if blocked:
            print("\nIf any of these are real people, add the word to "
                  "worker/src/data/allow.txt. Do not weaken the filter.")
        overlap = check_allow_overlap()
        if overlap:
            print("\nWARNING: these worker/src/data/allow.txt entries hash to "
                  "an already-blocked term, silently nullifying that "
                  "block. This is a bug in the term lists, not the "
                  "matcher -- fix by removing the term from one list:")
            for word in overlap:
                print(f"  {word}")
    else:
        _print(entries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
