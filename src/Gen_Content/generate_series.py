"""Build a paginated series of markdown pages, e.g. "How this site works".

Each part is an ordinary markdown page rendered through generate_page, then
given two navigation blocks: a table of contents at the top of the article
and previous/next links at the bottom. The parts live in one directory and
read in filename order, so `01-generator.md`, `02-fire.md` ... is the
reading order.
"""
import html
import os
import re

from Gen_Content.extract_title_markdown import extract_title
from Gen_Content.generate_page import generate_page

SERIES_NAME = "How this site works"
HOME_HREF = "../index.html"
HOME_LABEL = "BigZano"

_ARTICLE_OPEN = re.compile(r"<article\b[^>]*>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _text(value):
    return html.escape(str(value), quote=False)


def _attr(value):
    return html.escape(str(value), quote=True)


def build_series_nav(parts, current, series_name=SERIES_NAME,
                     home_href=HOME_HREF, home_label=HOME_LABEL):
    """The table of contents for part number `current` (0-based).

    `parts` is an ordered list of {"stem": ..., "title": ...} dicts. Links
    are relative to the series directory. The current part is marked
    aria-current rather than left as a dead link, so it stays findable.
    """
    items = []
    for index, part in enumerate(parts):
        current_attr = ' aria-current="page"' if index == current else ""
        items.append(
            f'    <li><a href="{_attr(part["stem"])}.html"{current_attr}>'
            f'{_text(part["title"])}</a></li>'
        )
    return (
        f'<nav class="series-nav" aria-label="{_attr(series_name)}">\n'
        f'  <p class="series-name"><a href="{_attr(home_href)}">'
        f"{_text(home_label)}</a> / {_text(series_name)}</p>\n"
        '  <ol class="series-parts">\n'
        + "\n".join(items)
        + "\n  </ol>\n"
        "</nav>"
    )


def build_series_step(parts, current):
    """Previous/next links for part `current`, or "" when there is neither.

    The first part has no previous link and the last has no next. The
    visually hidden prefix gives a screen reader the direction that the
    arrow glyph carries for sighted readers.
    """
    links = []
    if current > 0:
        prev = parts[current - 1]
        links.append(
            f'  <a class="series-prev" rel="prev" href="{_attr(prev["stem"])}.html">'
            f'<span class="vh">Previous part: </span>← {_text(prev["title"])}</a>'
        )
    if current < len(parts) - 1:
        nxt = parts[current + 1]
        links.append(
            f'  <a class="series-next" rel="next" href="{_attr(nxt["stem"])}.html">'
            f'<span class="vh">Next part: </span>{_text(nxt["title"])} →</a>'
        )
    if not links:
        return ""
    return (
        '<nav class="series-step" aria-label="Previous and next part">\n'
        + "\n".join(links)
        + "\n</nav>"
    )


def inject_series_nav(page_html, nav, step):
    """Put `nav` right after the opening <article> and `step` before </article>.

    Raises ValueError if the page has no <article>, since the navigation
    would otherwise vanish silently.
    """
    opening = _ARTICLE_OPEN.search(page_html)
    closing = page_html.rfind("</article>")
    if opening is None or closing == -1 or closing < opening.end():
        raise ValueError("page has no <article> element to put the series navigation in")

    before = page_html[: opening.end()]
    body = page_html[opening.end(): closing]
    after = page_html[closing:]
    step_block = f"\n{step}\n" if step else ""
    return f"{before}\n{nav}\n{body}{step_block}{after}"


def _part_title(path):
    with open(path, "r", encoding="utf-8") as handle:
        markdown = _COMMENT.sub("", handle.read())
    try:
        return extract_title(markdown)
    except ValueError as exc:
        raise ValueError(f"{os.path.basename(path)}: {exc}") from exc


def series_parts(series_dir):
    """Ordered [{"stem", "title", "src"}] for every .md in `series_dir`."""
    if not os.path.isdir(series_dir):
        return []
    parts = []
    for name in sorted(os.listdir(series_dir)):
        src = os.path.join(series_dir, name)
        if name.lower().endswith(".md") and os.path.isfile(src):
            parts.append({
                "stem": os.path.splitext(name)[0],
                "title": _part_title(src),
                "src": src,
            })
    return parts


def generate_series(series_dir, template_path, out_dir, series_name=SERIES_NAME,
                    home_href=HOME_HREF, home_label=HOME_LABEL):
    """Render every part of the series into `out_dir`. Returns the paths written.

    Titles are read from every part before anything is written, so a part
    with no h1 fails the whole series up front instead of leaving a
    half-linked set of pages behind.

    Note that generate_page writes a page-date comment back into any source
    markdown that lacks one.
    """
    parts = series_parts(series_dir)
    written = []
    for index, part in enumerate(parts):
        dest = os.path.join(out_dir, f"{part['stem']}.html")
        generate_page(part["src"], template_path, dest)

        with open(dest, "r", encoding="utf-8") as handle:
            page = handle.read()
        page = inject_series_nav(
            page,
            build_series_nav(parts, index, series_name, home_href, home_label),
            build_series_step(parts, index),
        )
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(page)
        written.append(dest)
    return written
