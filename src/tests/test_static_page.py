import contextlib
import datetime
import io
import tempfile
import unittest
from pathlib import Path

from Gen_Content.generate_guestbook_page import generate_guestbook_page
from Gen_Content.generate_static_page import (
    generate_static_page,
    write_redirect_page,
)

TEMPLATE = (
    "<title>{{ Title }}</title>\n"
    '<meta name="description" content="{{ Description }}">\n'
    '<link rel="canonical" href="{{ Canonical }}">\n'
    "<h1>{{ SiteTitle }}</h1>\n"
    "<p>{{ SiteDescription }}</p>\n"
    "<footer>{{ Year }} - {{ SiteAuthor }}</footer>\n"
)

CONFIG = {
    "title": "Workshop",
    "site_title": "Bret Zanotelli",
    "site_author": "Bret Zanotelli",
    "description": "Things Bret Zanotelli has built.",
}


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.template = self.root / "page.html"
        self.template.write_text(TEMPLATE, encoding="utf-8")
        self.dest = self.root / "out" / "page.html"

    def _generate(self, config=CONFIG, canonical="/workshop.html"):
        with contextlib.redirect_stdout(io.StringIO()):
            generate_static_page(
                str(self.template), str(self.dest), config, canonical
            )
        return self.dest.read_text(encoding="utf-8")


class TestGenerateStaticPage(_TempDirCase):
    def test_fills_every_placeholder(self):
        page = self._generate()
        self.assertNotIn("{{", page)

    def test_substitutes_each_field(self):
        page = self._generate()
        self.assertIn("<title>Workshop</title>", page)
        self.assertIn('content="Things Bret Zanotelli has built."', page)
        self.assertIn('href="/workshop.html"', page)
        self.assertIn("<h1>Bret Zanotelli</h1>", page)
        self.assertIn("- Bret Zanotelli</footer>", page)

    def test_year_is_the_current_utc_year(self):
        year = str(datetime.datetime.now(datetime.UTC).year)
        self.assertIn(f"<footer>{year} -", self._generate())

    def test_site_description_defaults_to_description(self):
        self.assertIn("<p>Things Bret Zanotelli has built.</p>", self._generate())

    def test_site_description_can_be_overridden(self):
        config = dict(CONFIG, site_description="The site tagline")
        page = self._generate(config)
        self.assertIn("<p>The site tagline</p>", page)
        self.assertIn('content="Things Bret Zanotelli has built."', page)

    def test_config_values_are_html_escaped(self):
        config = dict(CONFIG, title='<b>"x"</b> & co', description='" onload="x')
        page = self._generate(config)
        self.assertNotIn("<b>", page)
        self.assertIn("&lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; co", page)
        self.assertNotIn('content="" onload=', page)

    def test_canonical_is_escaped(self):
        page = self._generate(canonical='/a"b.html')
        self.assertIn("/a&quot;b.html", page)

    def test_none_config_uses_defaults(self):
        page = self._generate(config=None)
        self.assertNotIn("{{", page)
        self.assertIn("<title>Untitled</title>", page)

    def test_partial_config_keeps_defaults_for_the_rest(self):
        page = self._generate({"title": "Only a title"})
        self.assertIn("<title>Only a title</title>", page)
        self.assertIn("BigZano", page)

    def test_does_not_mutate_the_callers_config(self):
        supplied = {"title": "Workshop"}
        self._generate(supplied)
        self.assertEqual(supplied, {"title": "Workshop"})

    def test_creates_missing_parent_directories(self):
        self._generate()
        self.assertTrue(self.dest.parent.is_dir())

    def test_overwrites_an_existing_destination(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text("stale", encoding="utf-8")
        self.assertNotIn("stale", self._generate())

    def test_missing_template_raises_oserror(self):
        with self.assertRaises(OSError):
            generate_static_page(
                str(self.root / "nope.html"), str(self.dest), CONFIG, "/x.html"
            )

    def test_non_ascii_template_text_round_trips(self):
        self.template.write_text("forged — {{ Year }}", encoding="utf-8")
        self.assertIn("—", self._generate())


class TestGuestbookWrapper(_TempDirCase):
    def test_uses_the_guestbook_canonical_and_defaults(self):
        with contextlib.redirect_stdout(io.StringIO()):
            generate_guestbook_page(str(self.template), str(self.dest))
        page = self.dest.read_text(encoding="utf-8")
        self.assertIn('href="/guestbook.html"', page)
        self.assertIn("<title>Guestbook</title>", page)
        self.assertIn("<p>Sign the guestbook</p>", page)


class TestWriteRedirectPage(_TempDirCase):
    def _write(self):
        dest = self.root / "docs" / "resume.html"
        with contextlib.redirect_stdout(io.StringIO()):
            write_redirect_page(
                str(dest),
                "workshop.html",
                "Moved: Workshop",
                "<p>The resume is retired. "
                '<a href="workshop.html">The Workshop has what I\'ve built.</a></p>',
            )
        return dest.read_text(encoding="utf-8")

    def test_matches_the_contract(self):
        page = self._write()
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', page)
        self.assertIn("<title>Moved: Workshop</title>", page)
        self.assertIn('<meta name="robots" content="noindex">', page)
        self.assertIn(
            '<meta http-equiv="refresh" content="0; url=workshop.html">', page
        )
        self.assertIn('<link rel="canonical" href="/workshop.html">', page)
        self.assertIn(
            "<p>The resume is retired. "
            '<a href="workshop.html">The Workshop has what I\'ve built.</a></p>',
            page,
        )

    def test_creates_the_parent_directory(self):
        self._write()
        self.assertTrue((self.root / "docs").is_dir())

    def test_title_and_target_are_escaped(self):
        dest = self.root / "r.html"
        with contextlib.redirect_stdout(io.StringIO()):
            write_redirect_page(
                str(dest), 'a"b.html', "<x> & y", "<p>msg</p>"
            )
        page = dest.read_text(encoding="utf-8")
        self.assertIn("<title>&lt;x&gt; &amp; y</title>", page)
        self.assertIn("url=a&quot;b.html", page)
        self.assertIn("<p>msg</p>", page)

    def test_canonical_is_rooted_even_if_target_has_a_leading_slash(self):
        dest = self.root / "r.html"
        with contextlib.redirect_stdout(io.StringIO()):
            write_redirect_page(str(dest), "/workshop.html", "t", "<p>m</p>")
        self.assertIn(
            'href="/workshop.html"', dest.read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
