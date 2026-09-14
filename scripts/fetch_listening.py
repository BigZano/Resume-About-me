#!/usr/bin/env python3
"""Fetch top tracks from Spotify into content/listening.json.

Knows nothing about HTML — it writes JSON, and the build renders it. See
specs/2026-08-09-spotify-listening-design.md for the contract.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

TRACK_LIMIT = 10
TIME_RANGE = "short_term"  # old ~4wk window. TODO: being replaced, see below.


# TODO(old): still used by main() below. Keep until get_recently_played +
# aggregate_weekly_top (further down) are ready, then delete this and
# get_top_tracks together.
def parse_top_tracks(payload, limit=TRACK_LIMIT):
    """Extract [{'artist', 'title'}] from a Spotify top-tracks response.

    Raises ValueError rather than returning an empty list. An empty return
    would let the caller write a file that blanks the page, and a bad
    response must never be able to destroy good data.
    """
    # ValueError, not TypeError: callers catch one exception type for
    # "unusable payload" regardless of the underlying cause.
    if not isinstance(payload, dict):
        raise ValueError("top-tracks payload is not a JSON object")  # noqa: TRY004

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("top-tracks payload has no 'items' list")  # noqa: TRY004

    tracks = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("name")
        if not isinstance(title, str) or not title.strip():
            continue

        artists = item.get("artists")
        if not isinstance(artists, list) or not artists:
            continue
        first = artists[0]
        if not isinstance(first, dict):
            continue
        artist = first.get("name")
        if not isinstance(artist, str) or not artist.strip():
            continue

        tracks.append({"artist": artist.strip(), "title": title.strip()})
        if len(tracks) >= limit:
            break

    if not tracks:
        raise ValueError("top-tracks payload yielded zero usable tracks")
    return tracks


TOKEN_URL = "https://accounts.spotify.com/api/token"
TOP_TRACKS_URL = "https://api.spotify.com/v1/me/top/tracks"
TIMEOUT_SECONDS = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
LISTENING_PATH = REPO_ROOT / "content" / "listening.json"


def _require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable {name}")
    return value


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


def refresh_access_token(client_id, client_secret, refresh_token):
    """Trade the refresh token for an access token.

    Returns (access_token, rotated_refresh_token_or_None).
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    payload = _read_json(request, "Token refresh")
    access_token = payload.get("access_token")
    if not access_token:
        raise SystemExit(f"Token response carried no access_token: {payload}")
    return access_token, payload.get("refresh_token")


# TODO(old): being replaced by get_recently_played below.
def get_top_tracks(access_token):
    query = urllib.parse.urlencode({
        "time_range": TIME_RANGE,
        "limit": TRACK_LIMIT,
    })
    request = urllib.request.Request(
        f"{TOP_TRACKS_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return _read_json(request, "Top-tracks fetch")


# TODO: new fetch fn. Same auth pattern as get_top_tracks above — Bearer
# token, GET, _read_json — just a different URL and no time_range param.
# Scope user-read-recently-played is already granted (spec §6), no re-auth.
def get_recently_played(access_token):
    """GET /me/player/recently-played?limit=50 -> raw JSON payload."""
    raise NotImplementedError


# TODO: new parse fn, sibling to parse_top_tracks above. Different shape:
# each item is {"track": {"name": ..., "artists": [{"name": ...}]},
# "played_at": "2026-09-10T14:00:00Z"}. Same rule as parse_top_tracks:
# raise ValueError on unusable payload, never return [].
def parse_recently_played(payload):
    """Raw recently-played JSON -> [{"artist", "title", "played_at"}, ...]."""
    raise NotImplementedError


# TODO: new aggregation fn — this is the actual "weekly" logic.
# 1. Keep only entries where played_at is within 7 days of `now`.
# 2. Count occurrences per (artist, title) pair.
# 3. Sort by count desc; tiebreak by most recent played_at.
# 4. Return the top `limit` as [{"artist", "title"}, ...] (drop played_at —
#    listening.json's contract is artist/title only, see the spec).
# `now` is a parameter, not datetime.now() — keeps this testable without
# mocking the clock, same pattern as days_until_expiry in check_token_age.py.
def aggregate_weekly_top(entries, now, limit=TRACK_LIMIT):
    """[{"artist", "title", "played_at"}, ...], now -> top `limit` tracks."""
    raise NotImplementedError


def load_existing_tracks(path):
    """Committed tracks, or None when there is nothing usable on disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    tracks = data.get("tracks")
    return tracks if isinstance(tracks, list) else None


def write_listening(path, tracks):
    """Write listening.json atomically, via a temp file + os.replace.

    An interrupted write must never leave a truncated file behind.
    """
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": stamp, "tracks": tracks}, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help=(
            "Write the file even when tracks are unchanged, purely to reset "
            "the 60-day scheduled-workflow inactivity clock."
        ),
    )
    args = parser.parse_args(argv)

    client_id = _require_env("SPOTIFY_CLIENT_ID")
    client_secret = _require_env("SPOTIFY_CLIENT_SECRET")
    refresh_token = _require_env("SPOTIFY_REFRESH_TOKEN")

    access_token, rotated = refresh_access_token(
        client_id, client_secret, refresh_token
    )
    if rotated and rotated != refresh_token:
        # A workflow cannot rewrite its own secret. Silently dropping this
        # would make next week fail for reasons that look unrelated.
        print(
            "\n" + "=" * 68 +
            "\nACTION REQUIRED: Spotify returned a NEW refresh token.\n"
            "Update the SPOTIFY_REFRESH_TOKEN secret to:\n\n"
            f"{rotated}\n\n"
            "This run succeeded, but future runs may fail until you do.\n"
            + "=" * 68,
            file=sys.stderr,
        )

    # TODO: swap this block for:
    #   tracks = aggregate_weekly_top(
    #       parse_recently_played(get_recently_played(access_token)),
    #       datetime.now(UTC),
    #   )
    try:
        tracks = parse_top_tracks(get_top_tracks(access_token))
    except ValueError as exc:
        raise SystemExit(f"Top-tracks response unusable: {exc}") from exc

    if tracks == load_existing_tracks(LISTENING_PATH):
        if args.keep_alive:
            write_listening(LISTENING_PATH, tracks)
            print("Tracks unchanged; refreshed timestamp as keep-alive.")
        else:
            print("Tracks unchanged; leaving listening.json alone.")
        return 0

    write_listening(LISTENING_PATH, tracks)
    print(f"Wrote {len(tracks)} tracks to {LISTENING_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
