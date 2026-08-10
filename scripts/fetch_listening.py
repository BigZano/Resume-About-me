#!/usr/bin/env python3
"""Fetch top tracks from Spotify into content/listening.json.

Knows nothing about HTML — it writes JSON, and the build renders it. See
specs/2026-08-09-spotify-listening-design.md for the contract.
"""
import json

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
