"""Render the guestbook page template.

Templating only. This module never contacts the Worker -- the build is
offline by design. Entries are fetched by static/guestbook.js in the
browser, not at build time, so nothing here needs the network and nothing
here may acquire it.

The work itself lives in generate_static_page; this is the guestbook's
defaults and canonical URL on top of it.
"""
from Gen_Content.generate_static_page import generate_static_page

GUESTBOOK_CANONICAL = "/guestbook.html"

GUESTBOOK_DEFAULTS = {
    "title": "Guestbook",
    "site_title": "BigZano",
    "site_author": "BigZano",
    "description": "Sign the guestbook",
}


def generate_guestbook_page(template_path, dest_path, site_config=None):
    """Write the guestbook page to `dest_path`.

    Args:
        template_path: Path to the guestbook.html template.
        dest_path: Destination path for the generated page.
        site_config: Optional dict with title/site_title/site_author/
            description. Missing keys fall back to the defaults above; the
            caller's dict is never mutated.

    Raises:
        OSError: If the template cannot be read or the destination written.
    """
    config = dict(GUESTBOOK_DEFAULTS)
    if site_config:
        config.update(site_config)

    generate_static_page(template_path, dest_path, config, GUESTBOOK_CANONICAL)
