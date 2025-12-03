#!/usr/bin/env python3
"""Publish freshly built blog posts to social platforms."""
import argparse
import datetime
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

try:
    import tweepy  # type: ignore
except ImportError:  # pragma: no cover
    tweepy = None  # type: ignore

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_ROOT = REPO_ROOT / "content"
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT / "Gen_Content"))

from Gen_Content.extract_title_markdown import extract_title  # type: ignore


@dataclass
class PostContext:
    title: str
    summary: str
    url: str
    tags: List[str]


def _strip_html_comments(markdown: str) -> str:
    return re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL).replace("\r\n", "\n")


def _first_paragraph(markdown: str, max_len: int = 200) -> str:
    clean = []
    skip = False
    for line in markdown.splitlines():
        if line.strip().startswith("<!--") and "-->" not in line:
            skip = True
            continue
        if skip:
            if "-->" in line:
                skip = False
            continue
        if "-->" in line:
            continue
        segment = line.strip()
        if not segment:
            continue
        if segment.startswith(("#", "!", "-", "*", ">", "[", "<")):
            continue
        segment = " ".join(segment.split())
        return (segment[: max_len - 1] + "…") if len(segment) > max_len else segment
    return "New blog post"


def _relative_html_path(md_path: Path) -> str:
    try:
        rel = md_path.relative_to(CONTENT_ROOT)
        return rel.with_suffix(".html").as_posix()
    except ValueError:
        return md_path.with_suffix(".html").name


def _ensure_tags(tags: Iterable[str]) -> List[str]:
    result: List[str] = []
    for tag in tags:
        if not tag:
            continue
        result.append(tag if tag.startswith("#") else f"#{tag}")
    return result


def load_post_context(md_path: Path, site_base_url: str, tags: Iterable[str]) -> PostContext:
    markdown = md_path.read_text(encoding="utf-8")
    markdown_clean = _strip_html_comments(markdown)
    title = extract_title(markdown_clean)
    summary = _first_paragraph(markdown_clean)
    rel_href = _relative_html_path(md_path)
    base = site_base_url.rstrip("/") if site_base_url else ""
    url = f"{base}/{rel_href}" if base else rel_href
    return PostContext(title=title, summary=summary, url=url, tags=_ensure_tags(tags))


def compose_message(post: PostContext, limit: int) -> str:
    tag_block = " ".join(post.tags).strip()
    headline = f"{post.title}: {post.summary}".strip()
    segments = [segment for segment in (headline, tag_block, post.url) if segment]
    message = " ".join(segments)
    if len(message) <= limit:
        return message
    allowance = limit - len(post.url)
    if tag_block:
        allowance -= len(tag_block) + 1
    allowance -= 1
    if allowance <= 0:
        if tag_block:
            bundle = f"{tag_block} {post.url}".strip()
            return bundle if len(bundle) <= limit else post.url
        return post.url
    shortened = textwrap.shorten(headline, width=max(5, allowance), placeholder="…")
    segments = [segment for segment in (shortened, tag_block, post.url) if segment]
    message = " ".join(segments)
    if len(message) <= limit:
        return message
    overflow = len(message) - limit
    if shortened and len(shortened) > overflow + 1:
        trimmed = shortened[: len(shortened) - overflow - 1].rstrip()
        if trimmed:
            trimmed = trimmed.rstrip("…")
        shortened = f"{trimmed}…" if trimmed else "…"
        message = " ".join(filter(None, (shortened, tag_block, post.url)))
        if len(message) <= limit:
            return message
    return " ".join(filter(None, (tag_block, post.url))) or post.url


def post_to_x(message: str, dry_run: bool) -> None:
    api_key = os.environ.get("X_API_KEY")
    api_secret = os.environ.get("X_API_SECRET")
    access_token = os.environ.get("X_ACCESS_TOKEN")
    access_secret = os.environ.get("X_ACCESS_TOKEN_SECRET")
    if dry_run:
        print(f"[dry-run][X] {message}")
        return
    if tweepy is None:
        raise RuntimeError("Install tweepy to post to X")
    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("Missing X OAuth credentials in environment")
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)  # type: ignore
    api = tweepy.API(auth)  # type: ignore
    api.update_status(status=message)
    print("Posted to X")


def post_to_mastodon(message: str, server: str, visibility: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run][Mastodon:{server}] {message}")
        return
    if requests is None:
        raise RuntimeError("Install requests to post to Mastodon")
    token = os.environ.get("MASTODON_ACCESS_TOKEN")
    if not server or not token:
        raise RuntimeError("Set MASTODON_SERVER and MASTODON_ACCESS_TOKEN")
    endpoint = f"https://{server}/api/v1/statuses"
    response = requests.post(  # type: ignore
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        data={"status": message, "visibility": visibility},
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Mastodon API error: {response.status_code} {response.text}")
    print("Posted to Mastodon")


def post_to_bluesky(message: str, api_host: str, dry_run: bool) -> None:
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    if dry_run:
        print(f"[dry-run][Bluesky] {message}")
        return
    if requests is None:
        raise RuntimeError("Install requests to post to Bluesky")
    if not handle or not password:
        raise RuntimeError("Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD")
    host = api_host or "https://bsky.social"
    session_resp = requests.post(  # type: ignore
        f"{host}/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=15,
    )
    if session_resp.status_code >= 400:
        raise RuntimeError(f"Bluesky auth failed: {session_resp.status_code} {session_resp.text}")
    data = session_resp.json()
    access_jwt = data["accessJwt"]
    did = data["did"]
    record = {
        "$type": "app.bsky.feed.post",
        "text": message,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    post_resp = requests.post(  # type: ignore
        f"{host}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {access_jwt}"},
        json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        timeout=15,
    )
    if post_resp.status_code >= 400:
        raise RuntimeError(f"Bluesky post failed: {post_resp.status_code} {post_resp.text}")
    print("Posted to Bluesky")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post a blog entry to social platforms.")
    parser.add_argument("markdown", help="Path to the markdown source post")
    parser.add_argument("--site-base-url", default=os.environ.get("SITE_BASE_URL", ""))
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument("--platforms", nargs="*", default=["all"], choices=["x", "mastodon", "bluesky", "all"])
    parser.add_argument("--mastodon-server", default=os.environ.get("MASTODON_SERVER", ""))
    parser.add_argument("--mastodon-visibility", default=os.environ.get("MASTODON_VISIBILITY", "public"))
    parser.add_argument("--bluesky-host", default=os.environ.get("BLUESKY_API_HOST", ""))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    md_path = Path(args.markdown).resolve()
    if not md_path.exists():
        raise FileNotFoundError(md_path)
    platforms = [p.lower() for p in args.platforms]
    if "all" in platforms:
        platforms = ["x", "mastodon", "bluesky"]
    post = load_post_context(md_path, args.site_base_url, args.tags)

    if "x" in platforms:
        message = compose_message(post, limit=280)
        post_to_x(message, args.dry_run)

    if "mastodon" in platforms:
        message = compose_message(post, limit=500)
        if not args.mastodon_server:
            raise RuntimeError("Set --mastodon-server or MASTODON_SERVER")
        post_to_mastodon(message, args.mastodon_server, args.mastodon_visibility, args.dry_run)

    if "bluesky" in platforms:
        message = compose_message(post, limit=300)
        post_to_bluesky(message, args.bluesky_host, args.dry_run)


if __name__ == "__main__":
    main()
