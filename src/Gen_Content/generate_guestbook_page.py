"""Render the guestbook page template.

Templating only. This module never contacts the Worker -- the build is
offline by design. Entries are fetched by static/guestbook.js in the
browser, not at build time, so nothing here needs the network and nothing
here may acquire it.
"""
import datetime
import os


def generate_guestbook_page(template_path, dest_path, site_config=None):
    """Write the guestbook page to `dest_path`.

    Args:
        template_path: Path to the guestbook.html template.
        dest_path: Destination path for the generated page.
        site_config: Optional dict with title/site_title/site_author/
            description. Missing keys fall back to the defaults below; the
            caller's dict is never mutated.

    Raises:
        OSError: If the template cannot be read or the destination written.
    """
    config = {
        "title": "Guestbook",
        "site_title": "Bret Zanotelli",
        "site_author": "Bret Zanotelli",
        "description": "Sign the guestbook",
    }
    if site_config:
        config.update(site_config)

    with open(template_path, "r", encoding="utf-8") as handle:
        template = handle.read()

    current_year = datetime.datetime.now(datetime.UTC).year

    page_html = (
        template
        .replace("{{ Title }}", config["title"])
        .replace("{{ Description }}", config["description"])
        .replace("{{ Canonical }}", "/guestbook.html")
        .replace("{{ SiteTitle }}", config["site_title"])
        .replace("{{ SiteDescription }}", config["description"])
        .replace("{{ SiteAuthor }}", config["site_author"])
        .replace("{{ Year }}", str(current_year))
    )

    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as handle:
        handle.write(page_html)

    print(f"Guestbook page written to {dest_path}")
