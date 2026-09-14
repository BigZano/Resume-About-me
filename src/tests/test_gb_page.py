"""The guestbook page generator is templating only.

It must never touch the network -- the build is offline by design. Entries
are fetched by static/guestbook.js in the browser, not at build time.

The second half of this module guards the contract between the shipped
template, the stylesheet, and the frontend JS. Those three files are edited
independently; the tests are what stop them drifting apart.
"""
import datetime
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Makes `Gen_Content.*` importable when this module is run directly,
# without depending on scripts/run_tests.py's own sys.path insertion.
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from Gen_Content.generate_guestbook_page import (  # noqa: E402
    generate_guestbook_page,
)

TEMPLATE = """<!doctype html>
<title>{{ Title }}</title>
<body class="guestbook">
<h1>{{ SiteTitle }}</h1>
<footer>{{ Year }} - {{ SiteAuthor }}</footer>
</body>
"""

CONFIG = {
    "title": "Guestbook",
    "site_title": "Bret Zanotelli",
    "site_author": "Bret Zanotelli",
    "description": "Sign the guestbook",
}


class TestGenerateGuestbookPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.template = Path(self.tmp) / "guestbook.html"
        self.template.write_text(TEMPLATE, encoding="utf-8")
        self.dest = Path(self.tmp) / "out" / "guestbook.html"

    def _generate(self, config=CONFIG):
        generate_guestbook_page(str(self.template), str(self.dest), config)
        return self.dest.read_text(encoding="utf-8")

    def test_writes_the_destination_file(self):
        self._generate()
        self.assertTrue(self.dest.exists())

    def test_creates_missing_parent_directories(self):
        self._generate()
        self.assertTrue(self.dest.parent.is_dir())

    def test_substitutes_title(self):
        self.assertIn("<title>Guestbook</title>", self._generate())

    def test_substitutes_site_author(self):
        self.assertIn("Bret Zanotelli", self._generate())

    def test_substitutes_year_with_four_digits(self):
        year = str(datetime.datetime.now(datetime.UTC).year)
        self.assertIn(year, self._generate())

    def test_leaves_no_unsubstituted_placeholders(self):
        self.assertNotIn("{{", self._generate())

    def test_missing_template_raises_oserror(self):
        with self.assertRaises(OSError):
            generate_guestbook_page(
                "/nonexistent/guestbook.html", str(self.dest), CONFIG
            )

    def test_omitted_config_falls_back_to_defaults(self):
        self.assertIn("<title>Guestbook</title>", self._generate(None))

    def test_partial_config_keeps_defaults_for_the_rest(self):
        page = self._generate({"title": "Sign the book"})
        self.assertIn("<title>Sign the book</title>", page)
        self.assertIn("Bret Zanotelli", page)

    def test_does_not_mutate_the_callers_config(self):
        supplied = {"title": "Guestbook"}
        self._generate(supplied)
        self.assertEqual(supplied, {"title": "Guestbook"})

    def test_overwrites_an_existing_destination(self):
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self.dest.write_text("stale", encoding="utf-8")
        self.assertNotIn("stale", self._generate())

    def test_writes_a_bare_filename_destination(self):
        dest = Path(self.tmp) / "bare.html"
        generate_guestbook_page(str(self.template), str(dest), CONFIG)
        self.assertTrue(dest.exists())

    def test_substitutes_the_canonical_placeholder(self):
        template = Path(self.tmp) / "canon.html"
        template.write_text("<link href='{{ Canonical }}'>", encoding="utf-8")
        dest = Path(self.tmp) / "canon-out.html"
        generate_guestbook_page(str(template), str(dest), CONFIG)
        self.assertIn("guestbook.html", dest.read_text(encoding="utf-8"))

    def test_substitutes_the_description_placeholders(self):
        template = Path(self.tmp) / "desc.html"
        template.write_text(
            "{{ Description }}|{{ SiteDescription }}", encoding="utf-8"
        )
        dest = Path(self.tmp) / "desc-out.html"
        generate_guestbook_page(str(template), str(dest), CONFIG)
        rendered = dest.read_text(encoding="utf-8")
        self.assertEqual(rendered, "Sign the guestbook|Sign the guestbook")

    def test_round_trips_non_ascii_template_text(self):
        template = Path(self.tmp) / "utf8.html"
        template.write_text("forged — {{ Year }}", encoding="utf-8")
        dest = Path(self.tmp) / "utf8-out.html"
        generate_guestbook_page(str(template), str(dest), CONFIG)
        self.assertIn("—", dest.read_text(encoding="utf-8"))

    def test_generator_imports_nothing_that_reaches_the_network(self):
        """The build is offline. No HTTP client may appear in this module."""
        source = (
            REPO_ROOT / "src" / "Gen_Content" / "generate_guestbook_page.py"
        ).read_text(encoding="utf-8")
        for banned in ("urllib", "http.client", "requests", "socket", "ssl"):
            self.assertNotIn(banned, source)


class TestRealTemplate(unittest.TestCase):
    """Guards the contract between the shipped template and the frontend JS."""

    def setUp(self):
        self.markup = (REPO_ROOT / "guestbook.html").read_text(encoding="utf-8")

    def test_has_the_entries_mount_point(self):
        self.assertIn('id="gb-entries"', self.markup)

    def test_has_the_empty_state_node(self):
        self.assertIn('id="gb-empty"', self.markup)

    def test_has_the_form(self):
        self.assertIn('id="gb-form"', self.markup)

    def test_has_the_honeypot_field(self):
        self.assertIn('name="website"', self.markup)

    def test_honeypot_is_hidden_from_assistive_tech(self):
        self.assertIn('aria-hidden="true"', self.markup)

    def test_honeypot_is_not_tabbable(self):
        self.assertIn('tabindex="-1"', self.markup)

    def test_has_an_aria_live_status_region(self):
        self.assertIn('aria-live="polite"', self.markup)

    def test_has_the_status_node(self):
        self.assertIn('id="gb-status"', self.markup)

    def test_has_the_blocked_panel(self):
        self.assertIn('id="gb-reject"', self.markup)

    def test_blocked_panel_image_has_alt_text(self):
        panel = self.markup.split('id="gb-reject"', 1)[1]
        img = panel.split("<img", 1)[1].split(">", 1)[0]
        self.assertRegex(img, r'alt="[^"]+"')

    def test_blocked_panel_is_a_modal(self):
        """<dialog> buys focus trapping, Escape, and a backdrop from the
        browser rather than hand-written script."""
        tag = re.search(r"<dialog\s[^>]*>", self.markup)
        self.assertIsNotNone(tag, "no <dialog> element in the page")
        self.assertIn('id="gb-reject"', tag.group(0))

    def test_blocked_panel_is_labelled(self):
        tag = re.search(r"<dialog\s[^>]*>", self.markup)
        self.assertIsNotNone(tag)
        self.assertIn("aria-labelledby=", tag.group(0))

    def test_has_the_bonfire(self):
        self.assertIn('id="gb-fire"', self.markup)

    def test_bonfire_ships_lit(self):
        """The no-JS and offline paths never fetch, so whatever ships in
        the markup is what those readers get."""
        panel = self.markup.split('id="gb-fire"', 1)[1].split(">", 1)[0]
        self.assertIn("data-heat=", panel)
        self.assertNotIn('data-heat="cold"', panel)

    def test_bonfire_art_is_hidden_from_assistive_tech(self):
        """The drawing is decorative; the figcaption carries the state."""
        svg = self.markup.split("<svg", 1)[1].split(">", 1)[0]
        self.assertIn('aria-hidden="true"', svg)

    def test_bonfire_has_a_flourish_node(self):
        self.assertIn('id="gb-fire-flourish"', self.markup)

    def test_flourish_ships_empty(self):
        """Text baked into the served markup would show on the no-JS path
        too, announcing something that never happened."""
        tag = self.markup.split('id="gb-fire-flourish"', 1)[1]
        body = tag.split(">", 1)[1].split("</figcaption>", 1)[0]
        self.assertEqual(body.strip(), "")

    def test_flourish_is_hidden_from_assistive_tech(self):
        """The status line is the accessible confirmation; announcing
        both would say the same thing twice."""
        tag = self.markup.split('id="gb-fire-flourish"', 1)[1].split(">", 1)[0]
        self.assertIn('aria-hidden="true"', tag)

    def test_has_the_live_counter_node(self):
        self.assertIn('id="gb-count"', self.markup)

    def test_has_the_submit_button(self):
        self.assertIn('id="gb-submit"', self.markup)

    def test_name_input_caps_at_40(self):
        self.assertIn('maxlength="40"', self.markup)

    def test_message_input_caps_at_500(self):
        self.assertIn('maxlength="500"', self.markup)

    def test_loads_the_guestbook_script(self):
        self.assertIn("guestbook.js", self.markup)

    def test_loads_the_guestbook_stylesheet(self):
        self.assertIn("guestbook.css", self.markup)

    def test_form_fields_have_labels(self):
        self.assertIn('<label for="gb-name"', self.markup)
        self.assertIn('<label for="gb-message"', self.markup)

    def test_real_template_renders_with_no_placeholders_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "guestbook.html"
            generate_guestbook_page(
                str(REPO_ROOT / "guestbook.html"), str(dest), CONFIG
            )
            self.assertNotIn("{{", dest.read_text(encoding="utf-8"))


class TestStylesheet(unittest.TestCase):
    def setUp(self):
        self.css = (
            REPO_ROOT / "static" / "guestbook.css"
        ).read_text(encoding="utf-8")

    def test_honeypot_is_offscreen_not_display_none(self):
        """Some bots skip display:none fields. Offscreen catches more."""
        rule = self.css.split(".gb-hp", 1)[1].split("}", 1)[0]
        self.assertIn("-9999px", rule)
        self.assertNotIn("display:none", rule.replace(" ", ""))

    def test_serves_a_static_frame_when_motion_is_reduced(self):
        self.assertIn("prefers-reduced-motion", self.css)

    def test_defines_no_new_colour_values(self):
        """The forge palette lives in index.css. This file reuses it."""
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.css))
        self.assertNotIn("rgb(", self.css)
        self.assertNotIn("hsl(", self.css)


    def test_closed_dialog_is_hidden_explicitly(self):
        """Not left to the UA stylesheet: an unknown-element fallback has
        no default display:none, so the panel needs this explicitly."""
        self.assertRegex(
            self.css, r"\.gb-reject:not\(\[open\]\)\s*\{[^}]*display:\s*none"
        )


class TestFrontendScript(unittest.TestCase):
    def setUp(self):
        self.js = (
            REPO_ROOT / "static" / "guestbook.js"
        ).read_text(encoding="utf-8")

    def test_never_injects_html(self):
        """The XSS boundary. The Worker does not sanitise; the client
        must build nodes, never parse strings."""
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("outerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("document.write", self.js)

    def test_renders_entry_text_with_textcontent(self):
        self.assertIn("textContent", self.js)

    def test_reveal_toggle_is_a_real_button(self):
        self.assertIn('createElement("button")', self.js)

    def test_targets_the_worker_origin(self):
        self.assertIn("https://api.bretzanotelli.work", self.js)

    def test_maps_every_documented_error_code_to_copy(self):
        for code in (
            "empty",
            "name_too_long",
            "message_too_long",
            "url_not_allowed",
            "rate_limited",
        ):
            self.assertIn(f'"{code}"', self.js)

    def test_re_enables_the_button_in_a_finally_block(self):
        self.assertIn("finally", self.js)


if __name__ == "__main__":
    unittest.main()
