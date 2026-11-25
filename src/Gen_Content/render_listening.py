"""Render Spotify listening data into landing-page markup.

Deliberately knows nothing about Spotify or the network — it reads a dict
with a known shape and emits HTML. content/listening.json is the only
contract between this module and the fetcher.

The output is a chart: tracks arrive already ranked, each row carries its
play count, and consecutive rows by the same artist are marked
`same-artist` so the stylesheet can hide the repeated name and let the list
read grouped by artist. The name is only hidden visually; every row stays
complete in the markup, so a screen reader hears artist, title and plays on
every line.
"""
import html
import json
from datetime import datetime

# Matches the indentation of the surrounding <li> items in titlepage.html.
_INDENT = " " * 16

# Locale-proof month names. strftime("%b") follows the machine's locale, and
# "%-d" does not exist on Windows, so the stamp is assembled by hand.
MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

STAMP_EMPTY = "not yet live"
EMPTY_TRACKS_HTML = f"{_INDENT}<li>Nothing logged yet</li>"


def _plays(track):
    """The play count, or None when it is missing or not a real count.

    bool is an int subclass (True == 1) and a float like 3.0 is not a count
    the fetcher would write, so both are rejected rather than coerced.
    """
    plays = track.get("plays")
    if isinstance(plays, bool) or not isinstance(plays, int) or plays < 1:
        return None
    return plays


def _render_plays(plays):
    noun = "play" if plays == 1 else "plays"
    return (
        f'<span class="plays">×{plays}'
        f'<span class="vh"> {noun}</span></span>'
    )


def _clean_artist(track):
    return str(track.get("artist") or "").strip()


def _render_track(track, previous_artist):
    """One <li>, or None when the entry has nothing usable in it."""
    if not isinstance(track, dict):
        return None
    artist = _clean_artist(track)
    title = str(track.get("title") or "").strip()
    if not artist and not title:
        return None

    parts = []
    if artist:
        parts.append(f'<span class="artist">{html.escape(artist)}</span>')
    if title:
        parts.append(f'<span class="title">{html.escape(title)}</span>')
    plays = _plays(track)
    if plays is not None:
        parts.append(_render_plays(plays))

    # An empty artist never counts as a repeat: there is no name to hide.
    repeat = bool(artist) and artist == previous_artist
    open_tag = '<li class="same-artist">' if repeat else "<li>"
    return f"{_INDENT}{open_tag}{' '.join(parts)}</li>"


def _updated_label(fetched_at):
    """'Nov 24' from an ISO timestamp, or None when it is not usable.

    The date is read in the timestamp's own zone (the fetcher writes UTC),
    so the label matches what is in the file rather than the build machine.
    """
    if not isinstance(fetched_at, str):
        return None
    try:
        stamp = datetime.fromisoformat(fetched_at.strip())
    except ValueError:
        return None
    return f"{MONTHS[stamp.month - 1]} {stamp.day}"


def _stamp_live(count, fetched_at):
    label = f"top {count} this week"
    updated = _updated_label(fetched_at)
    return f"{label} · updated {updated}" if updated else label


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

    rendered = []
    previous_artist = None
    for track in tracks:
        line = _render_track(track, previous_artist)
        if line is None:
            continue
        rendered.append(line)
        previous_artist = _clean_artist(track)

    if not rendered:
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    return "\n".join(rendered), _stamp_live(len(rendered), data.get("fetched_at"))


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
