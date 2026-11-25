import datetime
import html
import os
import re

from Gen_Content.extract_title_markdown import extract_title
from Gen_Content.generate_blog_index import _extract_page_date
from Gen_Content.render_listening import MONTHS, load_listening, render_listening
from Gen_Content.render_playing import apply_playing, load_playing

DEV_DIARY_DIR = "dev_diary"
SERIES_DIR = "how_it_works"

# Copy for the pages that are not markdown files in content/. Markdown
# pages carry their own blurb in a `<!-- landing-blurb: ... -->` comment.
DEV_DIARY_BLURB = "Build notes, Advent of Code, and whatever got out of hand that month."
WORKSHOP_BLURB = "What I've built, what I'm building, and what I build it on."
SERIES_BLURB = "A tour of the generator, the fire, and the pipelines behind this page."
GUESTBOOK_BLURB = "Pull up a seat by the fire and leave a mark."

# How far into a markdown file the landing-* comments are looked for.
_COMMENT_SCAN_LINES = 5

# Indentation of the list inside titlepage.html's <ul class="page-links">.
_ENTRY_INDENT = " " * 14
_FIELD_INDENT = " " * 16

# A filename like 2025-12-1-Advent-of-Code.md: the day is not always padded.
_FILENAME_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_PLACEHOLDER = re.compile(r"\{\{ (\w+) \}\}")


# --- sitemap markup (pure) -------------------------------------------------

def _text(value):
    """Escape for an element's text. Quotes are fine there, so leave them."""
    return html.escape(str(value), quote=False)


def _render_entry(entry):
    lines = [
        f'{_ENTRY_INDENT}<li class="page-entry">',
        f'{_FIELD_INDENT}<a href="{html.escape(str(entry["href"]), quote=True)}">'
        f'{_text(entry["title"])}</a>',
    ]
    if entry.get("blurb"):
        lines.append(
            f'{_FIELD_INDENT}<p class="page-blurb">{_text(entry["blurb"])}</p>'
        )
    if entry.get("stamp"):
        lines.append(
            f'{_FIELD_INDENT}<p class="page-stamp">{_text(entry["stamp"])}</p>'
        )
    lines.append(f"{_ENTRY_INDENT}</li>")
    return "\n".join(lines)


def build_sitemap_html(entries):
    """Markup for the homepage sitemap from plain data.

    Each entry is a dict with `href` and `title`, and optionally `blurb` and
    `stamp`. A missing or empty blurb/stamp simply leaves that line out.
    Everything is escaped here, so callers pass raw text.
    """
    return "\n".join(_render_entry(entry) for entry in entries)


# --- gathering entries from disk -------------------------------------------

def _format_date(day):
    return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


def _plural(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


def _landing_comment(content, name):
    """The value of `<!-- name: value -->` near the top of a markdown file."""
    pattern = re.compile(rf"<!--\s*{re.escape(name)}:\s*(.*?)\s*-->")
    for line in content.splitlines()[:_COMMENT_SCAN_LINES]:
        match = pattern.match(line.strip())
        if match and match.group(1):
            return match.group(1)
    return None


def _filename_title(filename):
    stem = os.path.splitext(filename)[0]
    return stem.replace("_", " ").replace("-", " ").title()


def _page_title(content, filename):
    """landing-title comment, else the first h1, else the filename."""
    override = _landing_comment(content, "landing-title")
    if override:
        return override
    try:
        return extract_title(content)
    except ValueError:
        return _filename_title(filename)


def _post_date(filename, markdown):
    """A post's date: its page-date comment, else its filename prefix.

    Read-only. generate_blog_index writes a missing page-date back into the
    post; the landing page only wants to read one, so it never does.
    Returns None when neither source gives a real calendar date.
    """
    stamp, found = _extract_page_date(markdown)
    if found:
        try:
            return datetime.date.fromisoformat(stamp)
        except ValueError:
            pass
    match = _FILENAME_DATE.match(filename)
    if match:
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    return None


def _md_names(directory):
    return sorted(
        name for name in os.listdir(directory)
        if name.lower().endswith(".md")
        and os.path.isfile(os.path.join(directory, name))
    )


def _dev_diary_stamp(blog_dir):
    """'9 entries · newest Sep 2, 2026', or None for an empty diary."""
    names = _md_names(blog_dir)
    if not names:
        return None

    dates = []
    for name in names:
        try:
            with open(os.path.join(blog_dir, name), "r", encoding="utf-8") as f:
                markdown = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Warning: Could not read {name} for the diary stamp: {exc}")
            markdown = ""
        day = _post_date(name, markdown)
        if day:
            dates.append(day)

    count = _plural(len(names), "entry", "entries")
    if not dates:
        return count
    return f"{count} · newest {_format_date(max(dates))}"


def _top_level_pages(content_path):
    pages = []
    for filename in _md_names(content_path):
        html_name = f"{os.path.splitext(filename)[0]}.html"
        try:
            with open(os.path.join(content_path, filename), "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Warning: Could not process {filename}: {exc}")
            pages.append({"href": html_name, "title": _filename_title(filename)})
            continue
        pages.append({
            "href": html_name,
            "title": _page_title(content, filename),
            "blurb": _landing_comment(content, "landing-blurb"),
        })
    return pages


def gather_sitemap_entries(content_path, site_root):
    """The homepage's page entries, in display order, from what exists on disk.

    Args:
        content_path: The content/ directory.
        site_root: The directory holding the hand-written page templates
            (workshop.html lives there), i.e. the repo root.
    """
    entries = []

    blog_dir = os.path.join(content_path, DEV_DIARY_DIR)
    if os.path.isdir(blog_dir):
        entries.append({
            "href": "dev_diary.html",
            "title": "Dev Diary",
            "blurb": DEV_DIARY_BLURB,
            "stamp": _dev_diary_stamp(blog_dir),
        })

    if os.path.isfile(os.path.join(site_root, "workshop.html")):
        entries.append({
            "href": "workshop.html",
            "title": "Workshop",
            "blurb": WORKSHOP_BLURB,
        })

    series_dir = os.path.join(content_path, SERIES_DIR)
    parts = _md_names(series_dir) if os.path.isdir(series_dir) else []
    if parts:
        first = os.path.splitext(parts[0])[0]
        entries.append({
            "href": f"{SERIES_DIR}/{first}.html",
            "title": "How This Site Works",
            "blurb": SERIES_BLURB,
            "stamp": _plural(len(parts), "part", "parts"),
        })

    # Generated from guestbook.html, not markdown, so no scan finds it.
    # Listed unconditionally since this page is the only way in.
    entries.append({
        "href": "guestbook.html",
        "title": "Guestbook",
        "blurb": GUESTBOOK_BLURB,
    })

    if os.path.isdir(content_path):
        entries.extend(_top_level_pages(content_path))
    return entries


# --- the page --------------------------------------------------------------

def _fill_placeholders(template, values):
    """Replace `{{ Name }}` in one pass.

    A single pass means a substituted value is never scanned again, so text
    that came from data (a track or game name that looks like `{{ Year }}`)
    can't be mistaken for a placeholder. Unknown names are left as written.
    """
    return _PLACEHOLDER.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )


def generate_landing_page(content_path, template_path, dest_path, site_config=None):
    """
    Generate the landing page: intro, a sitemap of the site's pages, and the
    live Listening and Playing blocks.

    Args:
        content_path: Path to content directory containing .md files
        template_path: Path to titlepage.html template
        dest_path: Destination path for generated index.html
        site_config: Optional dict with site metadata (title, description, author)
    """
    config = {
        "title": "Welcome",
        "site_title": "My Portfolio",
        "site_description": "Welcome to my personal site",
        "site_author": "Your Name",
        "description": "Explore my projects, writing, and more"
    }
    if site_config:
        config.update(site_config)

    print(f"Generating landing page from {content_path} to {dest_path}")

    site_root = os.path.dirname(os.path.abspath(template_path))
    entries = gather_sitemap_entries(content_path, site_root)
    page_links = build_sitemap_html(entries)

    # Both data files are optional: a fresh clone has never fetched, and the
    # build must still succeed. See specs/2026-08-09-spotify-listening-design.md
    listening_data, listening_warning = load_listening(
        os.path.join(content_path, "listening.json")
    )
    if listening_warning:
        print(listening_warning)
    listening_tracks, listening_stamp = render_listening(listening_data)

    playing_data, playing_warning = load_playing(
        os.path.join(content_path, "playing.json")
    )
    if playing_warning:
        print(playing_warning)

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    current_year = datetime.datetime.now(datetime.UTC).year
    canonical = "/"

    landing_html = _fill_placeholders(template, {
        "Title": config["title"],
        "Description": config["description"],
        "Canonical": canonical,
        "SiteTitle": config["site_title"],
        "SiteDescription": config["site_description"],
        "SiteAuthor": config["site_author"],
        "Year": str(current_year),
        "PageLinks": page_links,
        "ListeningTracks": listening_tracks,
        "ListeningStamp": listening_stamp,
    })
    # After the placeholders, so nothing in a game name is ever rescanned.
    landing_html = apply_playing(landing_html, playing_data)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'w', encoding='utf-8') as f:
        f.write(landing_html)

    print(f"Landing page written to {dest_path}")
    print(f"Listed {len(entries)} page(s): {[e['title'] for e in entries]}")
