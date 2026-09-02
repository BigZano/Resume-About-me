"""Render Spotify listening data into landing-page markup.

Deliberately knows nothing about Spotify or the network — it reads a dict
with a known shape and emits HTML. content/listening.json is the only
contract between this module and the fetcher.
"""
import html
import json

# Matches the indentation of the surrounding <li> items in titlepage.html.
_INDENT = " " * 16

STAMP_LIVE = "on repeat this month"
STAMP_EMPTY = "not yet live"
EMPTY_TRACKS_HTML = f"{_INDENT}<li>Nothing logged yet</li>"


def _render_track(track):
    """One <li>, or None when the entry has nothing usable in it."""
    if not isinstance(track, dict):
        return None
    artist = str(track.get("artist") or "").strip()
    title = str(track.get("title") or "").strip()
    if not artist and not title:
        return None
    return (
        f"{_INDENT}<li><span>{html.escape(artist)}</span> "
        f"{html.escape(title)}</li>"
    )


def render_listening(data):
    """Return (tracks_html, stamp) for the Listening block.

    Falls back to the empty state for anything unusable, so the build can
    never fail because of listening data.
    """
    if not isinstance(data, dict):
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    rendered = [line for line in (_render_track(t) for t in tracks) if line]
    if not rendered:
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    return "\n".join(rendered), STAMP_LIVE


def load_listening(path):
    """Read listening.json. Returns (data, warning).

    A missing file is a legitimate state — a fresh clone that has never
    fetched — so it returns (None, None) silently. Malformed content is a
    bug, so it returns a warning for the caller to print.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, f"Warning: could not read {path}: {exc}"
