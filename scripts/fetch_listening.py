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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TRACK_LIMIT = 10
TIME_RANGE = "short_term"  # Spotify's rolling ~4-week ranking


def parse_top_tracks(payload, limit=TRACK_LIMIT):
    """Extract [{'artist', 'title'}] from a Spotify top-tracks response.

    Raises ValueError rather than returning an empty list. An empty return
    would let the caller write a file that blanks the page, and a bad
    response must never be able to destroy good data.
    """
    if not isinstance(payload, dict):
        raise ValueError("top-tracks payload is not a JSON object")

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("top-tracks payload has no 'items' list")

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
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"fetched_at": stamp, "tracks": tracks}, handle, indent=2)
        handle.write("\n")


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

    tracks = parse_top_tracks(get_top_tracks(access_token))

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
