#!/usr/bin/env python3
"""Fetch recently played Steam games into content/playing.json.

Same shape as fetch_listening.py: it knows nothing about HTML, it writes
JSON, and the build renders it. The committed file is the only seam.

Needs STEAM_API_KEY and STEAM_ID. If either is unset this prints a notice and
exits 0 without touching anything, so a workflow whose Steam secrets have not
been created yet keeps working.

The Steam profile's "Game details" must be public, or the API answers with an
empty `response` object and this exits non-zero without writing. A public
profile with nothing played in the last two weeks is fine: that writes an empty
`games` list.
"""
import argparse
import json
import math
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

GAME_LIMIT = 5
STEAM_URL = (
    "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
)
TIMEOUT_SECONDS = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAYING_PATH = REPO_ROOT / "content" / "playing.json"


def _minutes_to_tenths_of_an_hour(minutes):
    """Whole minutes -> tenths of an hour, rounding half up.

    Integer arithmetic on purpose: round(minutes / 60, 1) works on a float,
    so 9 minutes (exactly 0.15 h) comes out as 0.1 or 0.2 depending on how
    the binary fraction happens to fall. Here 9 minutes is always 0.2 h.
    """
    return int((minutes + 3) // 6)


def parse_recent_games(payload, limit=GAME_LIMIT):
    """Extract [{'name', 'hours_2weeks'}] from a GetRecentlyPlayedGames response.

    Sorted by two-week playtime, longest first (ties by name, so the order
    never depends on what order Steam happened to send). Steam reports
    `playtime_2weeks` in MINUTES; hours_2weeks is that over 60, to one decimal.
    A game whose hours round to 0.0 is dropped.

    A public profile with nothing played in two weeks is a legitimate quiet
    stretch and returns []: Steam sends `total_count: 0` and/or `games: []`
    for it. Everything that is NOT that raises ValueError: a payload or
    `response` that is not an object, an EMPTY `response` object (what a
    private profile or a bad steamid looks like), a missing or non-list
    `games` without `total_count: 0`, and a non-empty `games` list in which no
    entry is usable (that smells like a shape change).
    """
    # ValueError, not TypeError: callers catch one exception type for
    # "unusable payload" regardless of the underlying cause.
    if not isinstance(payload, dict):
        raise ValueError("Steam payload is not a JSON object")  # noqa: TRY004

    response = payload.get("response")
    if not isinstance(response, dict) or not response:
        raise ValueError(
            "Steam returned an empty response (is the profile's game "
            "details setting private, or the steamid wrong?)"
        )

    if "games" not in response:
        count = response.get("total_count")
        # bool is an int subclass; False is not a count.
        if isinstance(count, int) and not isinstance(count, bool) and count == 0:
            return []
        raise ValueError("Steam response has no 'games' list")
    games = response["games"]
    if not isinstance(games, list):
        raise ValueError("Steam response has no 'games' list")  # noqa: TRY004
    if not games:
        return []

    found = []
    for game in games:
        if not isinstance(game, dict):
            continue
        name = game.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        minutes = game.get("playtime_2weeks")
        # bool is an int subclass; True is not a playtime.
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            continue
        try:
            if not math.isfinite(minutes) or minutes < 0:
                continue
        except OverflowError:  # an int too large to be a float is not a playtime
            continue
        found.append((name.strip(), minutes))

    if not found:
        raise ValueError("Steam response yielded zero usable games")

    found.sort(key=lambda pair: (-pair[1], pair[0]))
    chart = []
    for name, minutes in found:
        if len(chart) >= limit:
            break
        tenths = _minutes_to_tenths_of_an_hour(minutes)
        if tenths == 0:
            # Played, but not enough to show as anything but "0.0 h".
            continue
        chart.append({"name": name, "hours_2weeks": tenths / 10})
    return chart


def _read_json(request, what):
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{what} failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{what} failed (network): {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{what} returned invalid JSON: {exc}") from exc


def get_recent_games(api_key, steam_id):
    """GET GetRecentlyPlayedGames -> raw JSON payload.

    The key travels in the query string because that is how this API takes
    it. It is never printed: errors report the status and body, not the URL.
    """
    query = urllib.parse.urlencode({"key": api_key, "steamid": steam_id})
    request = urllib.request.Request(f"{STEAM_URL}?{query}")
    return _read_json(request, "Steam recently-played fetch")


def load_existing_games(path):
    """Committed games, or None when there is nothing usable on disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    games = data.get("games")
    return games if isinstance(games, list) else None


def write_playing(path, games):
    """Write playing.json atomically, via a temp file + os.replace.

    An interrupted write must never leave a truncated file behind.
    """
    path = Path(path)
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": stamp, "games": games}, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def main(argv=None, env=None, fetch=get_recent_games):
    """`env` and `fetch` exist so tests can run this without the network."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PLAYING_PATH,
        help="Where to write the games (default: %(default)s).",
    )
    args = parser.parse_args(argv)

    env = os.environ if env is None else env
    api_key = str(env.get("STEAM_API_KEY", "")).strip()
    steam_id = str(env.get("STEAM_ID", "")).strip()
    if not api_key or not steam_id:
        print(
            "STEAM_API_KEY and STEAM_ID are not both set; "
            "skipping the Steam fetch."
        )
        return 0

    try:
        games = parse_recent_games(fetch(api_key, steam_id))
    except ValueError as exc:
        raise SystemExit(f"Steam response unusable: {exc}") from exc

    if games == load_existing_games(args.output):
        print("Games unchanged; leaving playing.json alone.")
        return 0

    write_playing(args.output, games)
    print(f"Wrote {len(games)} games to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
