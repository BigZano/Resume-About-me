#!/usr/bin/env python3
"""Build the weekly Spotify chart in content/listening.json.

Spotify's recently-played endpoint only ever returns the last 50 plays, so a
single weekly fetch would see a few hours of listening. The workflow instead
polls every few hours and merges each response into a rolling 7-day play log
(.cache/spotify-plays.json, held in the GitHub Actions cache, never
committed: it carries timestamps and the repo is public). A publish run then
aggregates that log into the top tracks and writes listening.json.

Spotify offers no way to look further back than those 50 plays, so a log that
has only just started (first run, or the cache was evicted) cannot show a true
week. The log therefore records when it began, and for the first 7 days a
publish keeps the committed chart instead of replacing it with a thin one.

Knows nothing about HTML — it writes JSON, and the build renders it. See
specs/2026-08-09-spotify-listening-design.md for the contract.

  python3 scripts/fetch_listening.py                  poll only: update the log
  python3 scripts/fetch_listening.py --publish        poll, then write the chart
  python3 scripts/fetch_listening.py --publish --keep-alive
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
from datetime import UTC, datetime, timedelta
from pathlib import Path

TRACK_LIMIT = 10
WINDOW_DAYS = 7  # the play log's window, and how long a new log warms up
RECENT_LIMIT = 50  # the most /me/player/recently-played will ever return


# --- timestamps --------------------------------------------------------------

def _parse_played_at(value):
    """Spotify timestamp string -> timezone-aware UTC datetime, or None.

    A naive timestamp is rejected rather than guessed at: it cannot be
    compared with an aware `now`, and Spotify always sends a zone.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _format_played_at(moment):
    """Canonical form, so equal instants always compare (and dedupe) equal."""
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _require_aware(moment, name):
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(f"`{name}` must be a timezone-aware datetime")


def _window_start(now):
    """Oldest instant still inside the 7-day window (inclusive)."""
    _require_aware(now, "now")
    return now - timedelta(days=WINDOW_DAYS)


# --- plays -------------------------------------------------------------------

def _clean_play(entry):
    """Normalise one play dict, or None when any field is unusable."""
    if not isinstance(entry, dict):
        return None
    artist = entry.get("artist")
    title = entry.get("title")
    if not isinstance(artist, str) or not artist.strip():
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    moment = _parse_played_at(entry.get("played_at"))
    if moment is None:
        return None
    return {
        "artist": artist.strip(),
        "title": title.strip(),
        "played_at": _format_played_at(moment),
    }


def _first_artist_name(track):
    artists = track.get("artists")
    if not isinstance(artists, list) or not artists:
        return None
    first = artists[0]
    return first.get("name") if isinstance(first, dict) else None


def parse_recently_played(payload):
    """Extract [{'artist', 'title', 'played_at'}] from a recently-played response.

    Order follows the payload (Spotify sends newest first).

    An `items` list with zero entries is a well-formed "nothing played" and
    returns []. That is a legitimate quiet stretch, not a fault, so it must
    not turn the run red. Everything that is NOT that raises ValueError: a
    payload that is not an object, an `items` that is missing or not a list,
    and a non-empty `items` in which no entry is usable (that smells like
    Spotify changed the shape, and silently reading it as "no plays" would
    hide it).
    """
    # ValueError, not TypeError: callers catch one exception type for
    # "unusable payload" regardless of the underlying cause.
    if not isinstance(payload, dict):
        raise ValueError("recently-played payload is not a JSON object")  # noqa: TRY004

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("recently-played payload has no 'items' list")  # noqa: TRY004
    if not items:
        return []

    plays = []
    for item in items:
        if not isinstance(item, dict):
            continue
        track = item.get("track")
        if not isinstance(track, dict):
            continue
        play = _clean_play({
            "artist": _first_artist_name(track),
            "title": track.get("name"),
            "played_at": item.get("played_at"),
        })
        if play is not None:
            plays.append(play)

    if not plays:
        raise ValueError("recently-played payload yielded zero usable plays")
    return plays


def merge_play_log(existing, fresh, now):
    """Merge new plays into the log, then drop anything older than 7 days.

    Pure: `now` is a parameter. Entries are normalised, de-duplicated on
    (played_at, artist, title) so overlapping polls never double-count, and
    returned oldest-first so the cached file is stable between runs. An entry
    exactly 7 days old is kept; one second older is dropped.
    """
    cutoff = _window_start(now)
    merged = {}
    for entry in [*existing, *fresh]:
        play = _clean_play(entry)
        if play is None:
            continue
        if _parse_played_at(play["played_at"]) < cutoff:
            continue
        merged[(play["played_at"], play["artist"], play["title"])] = play
    return sorted(
        merged.values(),
        key=lambda p: (p["played_at"], p["artist"], p["title"]),
    )


def aggregate_weekly_top(entries, now, limit=TRACK_LIMIT):
    """Top `limit` tracks by play count over the last 7 days.

    Returns [{'artist', 'title', 'plays'}], most-played first. Ties go to the
    most recently played track, then to artist/title so the order never
    depends on dict or file ordering (a flapping order would commit daily).
    Returns [] when nothing falls inside the window — the caller must treat
    that as "nothing to publish", never as a chart to write.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    cutoff = _window_start(now)

    counts = {}  # (artist, title) -> (plays, most recent played_at)
    for entry in entries:
        play = _clean_play(entry)
        if play is None:
            continue
        if _parse_played_at(play["played_at"]) < cutoff:
            continue
        key = (play["artist"], play["title"])
        plays, latest = counts.get(key, (0, ""))
        counts[key] = (plays + 1, max(latest, play["played_at"]))

    # sorted()/sort() are stable, so sort by the weakest key first.
    ranked = sorted(counts.items())                       # artist, title
    ranked.sort(key=lambda kv: kv[1][1], reverse=True)    # most recent
    ranked.sort(key=lambda kv: kv[1][0], reverse=True)    # most plays
    return [
        {"artist": artist, "title": title, "plays": plays}
        for (artist, title), (plays, _latest) in ranked[:limit]
    ]


# --- network -----------------------------------------------------------------

TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played"
TIMEOUT_SECONDS = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
LISTENING_PATH = REPO_ROOT / "content" / "listening.json"
# Gitignored. The workflow persists it through the Actions cache; it holds
# timestamps, so it must never be committed to this public repo.
PLAY_LOG_PATH = REPO_ROOT / ".cache" / "spotify-plays.json"


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


def get_recently_played(access_token):
    """GET /me/player/recently-played?limit=50 -> raw JSON payload."""
    query = urllib.parse.urlencode({"limit": RECENT_LIMIT})
    request = urllib.request.Request(
        f"{RECENTLY_PLAYED_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return _read_json(request, "Recently-played fetch")


# --- files -------------------------------------------------------------------

def _write_json_atomic(path, payload):
    """Write JSON via a temp file + os.replace.

    An interrupted write must never leave a truncated file behind.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _read_since(value, now):
    """The log's start time from the file's `since`. Returns (since, warning).

    A log without one (written before this existed) is treated as starting
    now, silently: it is a legitimate state. A `since` that is present but
    unusable (not a string, not a timestamp, no zone, or later than `now`)
    also restarts from now, with a warning. Trusting a future `since` would
    stretch the warm-up well past 7 days.
    """
    if value is None:
        return now, None
    since = _parse_played_at(value)
    if since is None:
        reason = "is unusable"
    elif since > now:
        reason = "is in the future"
    else:
        return since, None
    return now, f"play log 'since' {value!r} {reason}; restarting from now"


def load_play_log(path, now):
    """Read the cached play log. Returns (plays, since, warning).

    `since` is when the log started, as a timezone-aware datetime. Whenever
    the log starts fresh it is `now`. A missing file is a legitimate state
    (first run, or the cache was evicted), so it returns ([], now, None). A
    corrupt file also starts fresh rather than failing the run, but returns a
    warning for the caller to print. Individual unusable entries are dropped
    silently.
    """
    _require_aware(now, "now")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return [], now, None
    except (OSError, ValueError, RecursionError) as exc:
        return [], now, f"play log {path} is unreadable ({exc}); starting fresh"

    plays = data.get("plays") if isinstance(data, dict) else None
    if not isinstance(plays, list):
        return [], now, f"play log {path} has no 'plays' list; starting fresh"
    since, warning = _read_since(data.get("since"), now)
    cleaned = [play for play in map(_clean_play, plays) if play is not None]
    return cleaned, since, warning


def save_play_log(path, plays, since):
    """Write the log. `since` is required so a save can never drop it."""
    _require_aware(since, "since")
    _write_json_atomic(path, {
        "since": _format_played_at(since.astimezone(UTC)),
        "plays": plays,
    })


def update_play_log(path, fresh, now):
    """Load the log, merge `fresh` into it and save it.

    Returns (plays, since, previous_count, warning). `since` is read from the
    file and written back untouched, so it only ever changes when the log
    starts fresh. Saved before anything aggregates, so a failed publish
    cannot also lose this poll.
    """
    existing, since, warning = load_play_log(path, now)
    plays = merge_play_log(existing, fresh, now)
    save_play_log(path, plays, since)
    return plays, since, len(existing), warning


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
    """Write listening.json atomically, stamped with the current time."""
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    _write_json_atomic(path, {"fetched_at": stamp, "tracks": tracks})


# --- publishing --------------------------------------------------------------

def _is_usable_track(track):
    """A committed track the page can show: text artist and text title."""
    if not isinstance(track, dict):
        return False
    return all(
        isinstance(track.get(key), str) and track[key].strip()
        for key in ("artist", "title")
    )


def _has_usable_track(tracks):
    return isinstance(tracks, list) and any(map(_is_usable_track, tracks))


def _format_age(age):
    """'2d 4h', rounded down, so the notice never claims more than is true."""
    days, hours = divmod(int(age.total_seconds() // 3600), 24)
    return f"{days}d {hours}h"


def plan_publish(tracks, existing, keep_alive, *, since, now):
    """Decide what, if anything, to write. Returns (tracks_or_None, message).

    This is where "never overwrite good data with worse" lives:

    * Warm-up: a play log under 7 days old cannot hold a full week (Spotify
      only hands back the last 50 plays and offers no way to look further
      back), so a chart built from it would be thin. While it is, a usable
      committed chart stays. A log exactly 7 days old is complete and
      publishes. With no usable committed chart there is nothing to protect,
      so the log publishes whatever it has.
    * No plays in the window -> never write zero tracks. A quiet week is not
      a pipeline fault, so the last chart simply stays.
    * Tracks identical to the committed ones -> write nothing (fetched_at
      deliberately goes stale), unless keep_alive asks for a refresh.
    * keep_alive with nothing new to say re-stamps the committed chart, so the
      60-day scheduled-workflow inactivity clock is still reset.

    `since` is when the play log started. It and `now` are keyword-only
    because both are datetimes, and swapped they would read as a log from the
    future.
    """
    _require_aware(now, "now")
    _require_aware(since, "since")
    age = max(now - since, timedelta(0))
    if age < timedelta(days=WINDOW_DAYS) and _has_usable_track(existing):
        notice = (
            f"Warming up: play log covers {_format_age(age)} of "
            f"{WINDOW_DAYS}d; keeping the committed chart"
        )
        if keep_alive:
            return existing, f"{notice} (timestamp refreshed as keep-alive)."
        return None, f"{notice}."

    if not tracks:
        if keep_alive and existing:
            return existing, (
                "No plays in the last 7 days; refreshed timestamp on the "
                "committed chart as keep-alive."
            )
        return None, "No plays in the last 7 days; leaving listening.json alone."
    if tracks == existing:
        if keep_alive:
            return tracks, "Tracks unchanged; refreshed timestamp as keep-alive."
        return None, "Tracks unchanged; leaving listening.json alone."
    return tracks, f"Wrote {len(tracks)} tracks."


def publish_chart(plays, now, keep_alive, path=LISTENING_PATH, *, since):
    """Aggregate the play log and write listening.json if warranted."""
    tracks = aggregate_weekly_top(plays, now)
    to_write, message = plan_publish(
        tracks, load_existing_tracks(path), keep_alive, since=since, now=now
    )
    if to_write is not None:
        write_listening(path, to_write)
    return message


def run_poll(
    fresh, now, play_log, publish, keep_alive, chart_path=LISTENING_PATH
):
    """Everything after the fetch: update the log, then publish if asked.

    Split from main() so it can be run with a `now` and paths of the
    caller's choosing, without the network. Returns the exit code.
    """
    plays, since, previously, warning = update_play_log(play_log, fresh, now)
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    print(
        f"Fetched {len(fresh)} recent plays; the log now holds {len(plays)} "
        f"from the last {WINDOW_DAYS} days (was {previously})."
    )

    if not publish:
        print("Poll only; leaving listening.json alone.")
        return 0

    print(publish_chart(plays, now, keep_alive, chart_path, since=since))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help=(
            "After updating the play log, aggregate it and write "
            "content/listening.json when the chart changed. Without this "
            "flag the run only polls and never touches content/."
        ),
    )
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help=(
            "With --publish: write the file even when tracks are unchanged, "
            "purely to reset the 60-day scheduled-workflow inactivity clock."
        ),
    )
    parser.add_argument(
        "--play-log",
        type=Path,
        default=PLAY_LOG_PATH,
        help="Where the rolling 7-day play log lives (default: %(default)s).",
    )
    args = parser.parse_args(argv)
    if args.keep_alive and not args.publish:
        parser.error("--keep-alive only makes sense together with --publish")

    client_id = _require_env("SPOTIFY_CLIENT_ID")
    client_secret = _require_env("SPOTIFY_CLIENT_SECRET")
    refresh_token = _require_env("SPOTIFY_REFRESH_TOKEN")

    access_token, rotated = refresh_access_token(
        client_id, client_secret, refresh_token
    )
    if rotated and rotated != refresh_token:
        # A workflow cannot rewrite its own secret. Silently dropping this
        # would make a later run fail for reasons that look unrelated.
        print(
            "\n" + "=" * 68 +
            "\nACTION REQUIRED: Spotify returned a NEW refresh token.\n"
            "Update the SPOTIFY_REFRESH_TOKEN secret to:\n\n"
            f"{rotated}\n\n"
            "This run succeeded, but future runs may fail until you do.\n"
            + "=" * 68,
            file=sys.stderr,
        )

    try:
        fresh = parse_recently_played(get_recently_played(access_token))
    except ValueError as exc:
        raise SystemExit(f"Recently-played response unusable: {exc}") from exc

    return run_poll(
        fresh, datetime.now(UTC), args.play_log, args.publish, args.keep_alive
    )


if __name__ == "__main__":
    sys.exit(main())
