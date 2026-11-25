"""Render Steam recently-played data into the landing page's Playing block.

Same shape as render_listening: this module knows nothing about Steam or the
network. content/playing.json is the only contract with the fetcher.

Unlike the Listening block, Playing has a hand-written fallback. The
template keeps the real, hand-picked list between two marker comments:

    <!-- playing:start -->
      <ul class="now-list now-games"> ... </ul>
      <p class="now-stamp">hand-picked</p>
    <!-- playing:end -->

When the data is usable the region is replaced with live markup (including
an honest "nothing lately" for a public profile with no recent games); when
it is not (no file yet, malformed data) the hand-written content stays
exactly as it is. The markers themselves are
removed from the output either way.
"""
import html
import json
import math
import re

# Matches the indentation of the surrounding block in titlepage.html.
_LIST_INDENT = " " * 14
_ITEM_INDENT = " " * 16

STAMP_LIVE = "last two weeks · Steam"
EMPTY_GAMES_TEXT = "Nothing in the last two weeks"

PLAYING_START = "<!-- playing:start -->"
PLAYING_END = "<!-- playing:end -->"

# Tolerates spacing differences inside the comments, but nothing else:
# both markers must be present or the template is left untouched. The
# leading/trailing whitespace is swallowed so removing the markers leaves
# no blank or half-indented lines behind.
_REGION = re.compile(
    r"[ \t]*<!--\s*playing:start\s*-->[ \t]*\n?"
    r"(?P<fallback>.*?)\n?"
    r"[ \t]*<!--\s*playing:end\s*-->[ \t]*(?P<newline>\n?)",
    re.DOTALL,
)


def _hours(game):
    """Hours as a float, or None when missing or not a usable duration.

    Rejects bool (an int subclass), strings, negatives, NaN and infinity: a
    bad number drops the hours label, never the game itself.
    """
    hours = game.get("hours_2weeks")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        return None
    if not math.isfinite(hours) or hours < 0:
        return None
    return float(hours)


def _render_game(game):
    """One <li>, or None when the entry has no usable name."""
    if not isinstance(game, dict):
        return None
    name = game.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    parts = [f'<span class="title">{html.escape(name.strip())}</span>']
    hours = _hours(game)
    # Judge by what would be shown: "0.0h" says nothing a missing label
    # does not, so anything that rounds to it is dropped. Comparing the
    # formatted text keeps this in step with the display, float quirks and all.
    shown = f"{hours:.1f}" if hours is not None else None
    if shown is not None and float(shown) > 0:
        parts.append(
            f'<span class="hours">{shown}h'
            '<span class="vh"> in the last two weeks</span></span>'
        )
    return f"{_ITEM_INDENT}<li>{' '.join(parts)}</li>"


def _live_block(items):
    return (
        f'{_LIST_INDENT}<ul class="now-list now-games">\n'
        + "\n".join(items)
        + f"\n{_LIST_INDENT}</ul>\n"
        f'{_LIST_INDENT}<p class="now-stamp">{STAMP_LIVE}</p>'
    )


def render_playing(data):
    """Return replacement HTML for the Playing region, or None.

    None means "keep the hand-written fallback": the data is missing or
    malformed, or it lists games but none has a usable name.

    An empty `games` list is different. It is what the fetcher writes for a
    public profile with nothing played lately, a real answer, so it renders
    as a live empty state rather than falling back to the hand-picked list.
    Never raises.
    """
    if not isinstance(data, dict):
        return None
    games = data.get("games")
    if not isinstance(games, list):
        return None

    if not games:
        return _live_block([f"{_ITEM_INDENT}<li>{EMPTY_GAMES_TEXT}</li>"])

    items = [line for line in (_render_game(g) for g in games) if line]
    if not items:
        return None

    return _live_block(items)


def apply_playing(template_html, data):
    """Swap the marked Playing region of `template_html` for live markup.

    With usable data the whole region (markers included) becomes the live
    block. Without it, the hand-written fallback stays and only the markers
    go. A template with no complete marker pair comes back unchanged.
    """
    match = _REGION.search(template_html)
    if match is None:
        return template_html

    block = render_playing(data)
    if block is None:
        # Keep the fallback verbatim; drop only the marker lines.
        replacement = match.group("fallback") + match.group("newline")
    else:
        replacement = block + match.group("newline")

    return (
        template_html[: match.start()]
        + replacement
        + template_html[match.end():]
    )


def load_playing(path):
    """Read playing.json. Returns (data, warning).

    Mirrors load_listening: a missing file is a normal state (the Steam
    secrets may not exist yet) and returns (None, None) silently; malformed
    content returns a warning for the caller to print.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, f"Warning: could not read {path}: {exc}"
