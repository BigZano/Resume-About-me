"""Render hand-written HTML page templates, and write small redirect stubs.

Pages like the guestbook and the workshop are written as HTML, not markdown,
so they skip the markdown pipeline and only need the site-wide placeholders
filled in. This module is that one step, shared.

Templating only. Nothing here touches the network; the build is offline by
design.
"""
import datetime
import html
import os

DEFAULT_CONFIG = {
    "title": "Untitled",
    "site_title": "BigZano",
    "site_author": "BigZano",
    "description": "",
}


def _escape(value):
    """Config values land in text and in quoted attributes, so escape both."""
    return html.escape(str(value), quote=True)


def _write(dest_path, text):
    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as handle:
        handle.write(text)


def generate_static_page(template_path, dest_path, config, canonical):
    """Fill the site placeholders in `template_path` and write `dest_path`.

    Placeholders: {{ Title }} {{ Description }} {{ Canonical }}
    {{ SiteTitle }} {{ SiteDescription }} {{ SiteAuthor }} {{ Year }}.

    Args:
        template_path: The HTML template to read.
        dest_path: Where to write the finished page.
        config: Dict with title/site_title/site_author/description, plus an
            optional site_description. Missing keys fall back to
            DEFAULT_CONFIG, and site_description falls back to description.
            The caller's dict is never mutated. None is accepted.
        canonical: Site-absolute URL path of the page, e.g. "/workshop.html".

    Raises:
        OSError: If the template cannot be read or the destination written.
    """
    merged = dict(DEFAULT_CONFIG)
    if config:
        merged.update(config)
    site_description = merged.get("site_description", merged["description"])

    with open(template_path, "r", encoding="utf-8") as handle:
        template = handle.read()

    current_year = datetime.datetime.now(datetime.UTC).year

    page_html = (
        template
        .replace("{{ Title }}", _escape(merged["title"]))
        .replace("{{ Description }}", _escape(merged["description"]))
        .replace("{{ Canonical }}", _escape(canonical))
        .replace("{{ SiteTitle }}", _escape(merged["site_title"]))
        .replace("{{ SiteDescription }}", _escape(site_description))
        .replace("{{ SiteAuthor }}", _escape(merged["site_author"]))
        .replace("{{ Year }}", str(current_year))
    )

    _write(dest_path, page_html)
    print(f"Static page written to {dest_path}")


def write_redirect_page(dest_path, target, title, message_html):
    """Write a tiny page that sends visitors on to `target`.

    For old URLs that must not 404 after a page is retired. The refresh is
    instant, the page is kept out of search indexes, and the body carries a
    plain link for readers whose browser ignores meta refresh.

    Args:
        dest_path: Where to write the stub.
        target: Relative URL of the replacement page, e.g. "workshop.html".
            The canonical link is the same path from the site root.
        title: The stub's <title>. Escaped here.
        message_html: Trusted markup for the body, written by the caller
            (it carries the visible link), so it is NOT escaped.
    """
    safe_target = _escape(target)
    canonical = _escape("/" + target.lstrip("/"))
    page_html = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{_escape(title)}</title>\n"
        '<meta name="robots" content="noindex">\n'
        f'<meta http-equiv="refresh" content="0; url={safe_target}">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        "</head>\n"
        "<body>\n"
        f"{message_html}\n"
        "</body>\n"
        "</html>\n"
    )
    _write(dest_path, page_html)
    print(f"Redirect page written to {dest_path}")
