import contextlib
import io
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from Gen_Content.generate_series import (
    build_series_nav,
    build_series_step,
    generate_series,
    inject_series_nav,
    series_parts,
)

TEMPLATE = (
    "<!doctype html><title>{{ Title }}</title>"
    '<link href="./index.css" rel="stylesheet">'
    "<body><article>{{ Content }}</article></body>"
)

PARTS = {
    "01-generator.md": "<!-- page-date: 2026-11-01 -->\n# The generator\n\nIt builds pages.\n",
    "02-fire.md": "<!-- page-date: 2026-11-02 -->\n# The fire\n\nIt burns.\n",
    "03-listening.md": "<!-- page-date: 2026-11-03 -->\n# Listening\n\nIt plays.\n",
}


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class _Links(HTMLParser):
    """Collects (class-of-parent-nav, attrs-of-<a>, text) for every link."""

    def __init__(self):
        super().__init__()
        self.navs = []          # stack of nav classes
        self.links = []         # (nav_class, attrs, text)
        self._current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav":
            self.navs.append(attrs.get("class"))
        elif tag == "a":
            self._current = [self.navs[-1] if self.navs else None, attrs, ""]

    def handle_endtag(self, tag):
        if tag == "nav" and self.navs:
            self.navs.pop()
        elif tag == "a" and self._current:
            self.links.append(tuple(self._current))
            self._current = None

    def handle_data(self, data):
        if self._current is not None:
            self._current[2] += data


def _links(markup, nav_class):
    parser = _Links()
    parser.feed(markup)
    return [(a, t) for cls, a, t in parser.links if cls == nav_class]


class _SeriesCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "content" / "how_it_works"
        self.src.mkdir(parents=True)
        self.template = self.root / "template.html"
        self.template.write_text(TEMPLATE, encoding="utf-8")
        # Under a directory named docs, as in the real build, so
        # generate_page rewrites ./ asset paths for the subdirectory.
        self.out = self.root / "docs" / "how_it_works"

    def write_parts(self, parts=PARTS):
        for name, text in parts.items():
            (self.src / name).write_text(text, encoding="utf-8")

    def build(self):
        return _quiet(
            generate_series, str(self.src), str(self.template), str(self.out)
        )

    def page(self, name):
        return (self.out / name).read_text(encoding="utf-8")


class TestBuildSeriesNav(unittest.TestCase):
    PARTS = [
        {"stem": "01-generator", "title": "The generator"},
        {"stem": "02-fire", "title": "The fire"},
        {"stem": "03-listening", "title": "Listening"},
    ]

    def test_matches_the_contract_for_the_middle_part(self):
        self.assertEqual(
            build_series_nav(self.PARTS, 1),
            '<nav class="series-nav" aria-label="How this site works">\n'
            '  <p class="series-name"><a href="../index.html">BigZano</a>'
            " / How this site works</p>\n"
            '  <ol class="series-parts">\n'
            '    <li><a href="01-generator.html">The generator</a></li>\n'
            '    <li><a href="02-fire.html" aria-current="page">The fire</a></li>\n'
            '    <li><a href="03-listening.html">Listening</a></li>\n'
            "  </ol>\n"
            "</nav>",
        )

    def test_exactly_one_part_is_current(self):
        for index in range(3):
            with self.subTest(index=index):
                nav = build_series_nav(self.PARTS, index)
                self.assertEqual(nav.count("aria-current"), 1)
                current = [a for a, _ in _links(nav, "series-nav")
                           if "aria-current" in a]
                self.assertEqual(
                    current[0]["href"], f"{self.PARTS[index]['stem']}.html"
                )

    def test_titles_and_stems_are_escaped(self):
        parts = [{"stem": 'a"b', "title": "<script>x</script> & <b>"}]
        nav = build_series_nav(parts, 0)
        self.assertNotIn("<script>", nav)
        self.assertNotIn("<b>", nav)
        self.assertIn("&lt;script&gt;x&lt;/script&gt; &amp; &lt;b&gt;", nav)
        self.assertIn('href="a&quot;b.html"', nav)


class TestBuildSeriesStep(unittest.TestCase):
    PARTS = TestBuildSeriesNav.PARTS

    def test_middle_part_has_both_links_in_the_contract_markup(self):
        self.assertEqual(
            build_series_step(self.PARTS, 1),
            '<nav class="series-step" aria-label="Previous and next part">\n'
            '  <a class="series-prev" rel="prev" href="01-generator.html">'
            '<span class="vh">Previous part: </span>← The generator</a>\n'
            '  <a class="series-next" rel="next" href="03-listening.html">'
            '<span class="vh">Next part: </span>Listening →</a>\n'
            "</nav>",
        )

    def test_first_part_has_no_previous_link(self):
        step = build_series_step(self.PARTS, 0)
        self.assertNotIn("series-prev", step)
        self.assertNotIn('rel="prev"', step)
        self.assertIn('href="02-fire.html"', step)

    def test_last_part_has_no_next_link(self):
        step = build_series_step(self.PARTS, 2)
        self.assertNotIn("series-next", step)
        self.assertNotIn('rel="next"', step)
        self.assertIn('href="02-fire.html"', step)

    def test_a_series_of_one_has_no_step_navigation(self):
        self.assertEqual(build_series_step(self.PARTS[:1], 0), "")

    def test_titles_are_escaped(self):
        parts = [{"stem": "a", "title": "<i>A</i>"}, {"stem": "b", "title": "<u>B</u>"}]
        step = build_series_step(parts, 0) + build_series_step(parts, 1)
        self.assertNotIn("<i>", step)
        self.assertNotIn("<u>", step)
        self.assertIn("&lt;u&gt;B&lt;/u&gt;", step)


class TestInjectSeriesNav(unittest.TestCase):
    def test_nav_goes_first_and_step_goes_last_inside_the_article(self):
        page = inject_series_nav(
            "<body><article><h1>T</h1><p>x</p></article></body>", "<NAV>", "<STEP>"
        )
        self.assertEqual(
            page,
            "<body><article>\n<NAV>\n<h1>T</h1><p>x</p>\n<STEP>\n</article></body>",
        )

    def test_empty_step_adds_nothing(self):
        page = inject_series_nav("<article><h1>T</h1></article>", "<NAV>", "")
        self.assertEqual(page, "<article>\n<NAV>\n<h1>T</h1></article>")

    def test_article_with_attributes_is_found(self):
        page = inject_series_nav(
            '<article class="post" id="x">body</article>', "<NAV>", "<STEP>"
        )
        self.assertTrue(page.startswith('<article class="post" id="x">\n<NAV>'))

    def test_uses_the_last_closing_article_tag(self):
        page = inject_series_nav(
            "<article>a<article>b</article>c</article>", "<NAV>", "<STEP>"
        )
        self.assertTrue(page.endswith("c\n<STEP>\n</article>"))

    def test_missing_article_is_an_error_not_a_silent_skip(self):
        for markup in ("<body>no article</body>", "<article>never closed",
                       "</article><article>backwards"):
            with self.subTest(markup=markup):
                with self.assertRaises(ValueError):
                    inject_series_nav(markup, "<NAV>", "<STEP>")


class TestSeriesParts(_SeriesCase):
    def test_sorted_by_filename_and_titled_from_the_h1(self):
        self.write_parts({
            "03-listening.md": PARTS["03-listening.md"],
            "01-generator.md": PARTS["01-generator.md"],
            "02-fire.md": PARTS["02-fire.md"],
        })
        parts = series_parts(str(self.src))
        self.assertEqual([p["stem"] for p in parts],
                         ["01-generator", "02-fire", "03-listening"])
        self.assertEqual([p["title"] for p in parts],
                         ["The generator", "The fire", "Listening"])

    def test_comments_before_the_h1_do_not_hide_it(self):
        self.write_parts({"01-a.md": "<!-- page-date: 2026-01-01 -->\n<!-- x -->\n# Real\n"})
        self.assertEqual(series_parts(str(self.src))[0]["title"], "Real")

    def test_ignores_non_markdown_and_subdirectories(self):
        self.write_parts({"01-a.md": "# A\n"})
        (self.src / "notes.txt").write_text("x", encoding="utf-8")
        (self.src / "drafts.md").mkdir()
        self.assertEqual([p["stem"] for p in series_parts(str(self.src))], ["01-a"])

    def test_missing_directory_gives_no_parts(self):
        self.assertEqual(series_parts(str(self.root / "nope")), [])

    def test_a_part_without_an_h1_is_a_clear_error(self):
        self.write_parts({"01-a.md": "no heading\n"})
        with self.assertRaises(ValueError) as caught:
            series_parts(str(self.src))
        self.assertIn("01-a.md", str(caught.exception))


class TestGenerateSeries(_SeriesCase):
    def test_writes_one_page_per_part_in_order(self):
        self.write_parts()
        written = self.build()
        self.assertEqual(
            [Path(p).name for p in written],
            ["01-generator.html", "02-fire.html", "03-listening.html"],
        )
        for path in written:
            self.assertTrue(Path(path).is_file())

    def test_table_of_contents_lists_every_part_in_order_on_every_page(self):
        self.write_parts()
        self.build()
        for name in PARTS:
            page = self.page(name.replace(".md", ".html"))
            with self.subTest(page=name):
                hrefs = [a["href"] for a, _ in _links(page, "series-nav")]
                self.assertEqual(
                    hrefs,
                    ["../index.html", "01-generator.html", "02-fire.html",
                     "03-listening.html"],
                )

    def test_aria_current_marks_the_page_you_are_on(self):
        self.write_parts()
        self.build()
        for name in PARTS:
            stem = name.replace(".md", "")
            with self.subTest(page=stem):
                page = self.page(f"{stem}.html")
                current = [a for a, _ in _links(page, "series-nav")
                           if a.get("aria-current") == "page"]
                self.assertEqual([a["href"] for a in current], [f"{stem}.html"])

    def test_first_part_has_next_only(self):
        self.write_parts()
        self.build()
        step = _links(self.page("01-generator.html"), "series-step")
        self.assertEqual([(a["rel"], a["href"]) for a, _ in step],
                         [("next", "02-fire.html")])

    def test_middle_part_has_prev_and_next(self):
        self.write_parts()
        self.build()
        step = _links(self.page("02-fire.html"), "series-step")
        self.assertEqual(
            [(a["rel"], a["href"]) for a, _ in step],
            [("prev", "01-generator.html"), ("next", "03-listening.html")],
        )

    def test_last_part_has_prev_only(self):
        self.write_parts()
        self.build()
        step = _links(self.page("03-listening.html"), "series-step")
        self.assertEqual([(a["rel"], a["href"]) for a, _ in step],
                         [("prev", "02-fire.html")])

    def test_a_single_part_series_has_no_step_navigation(self):
        self.write_parts({"01-only.md": "# Only\n\nHi.\n"})
        self.build()
        self.assertNotIn("series-step", self.page("01-only.html"))
        self.assertIn("series-nav", self.page("01-only.html"))

    def test_navigation_sits_inside_the_article_around_the_content(self):
        self.write_parts()
        self.build()
        page = self.page("02-fire.html")
        article = page.split("<article>", 1)[1].rsplit("</article>", 1)[0]
        self.assertTrue(article.lstrip().startswith('<nav class="series-nav"'))
        self.assertTrue(article.rstrip().endswith("</nav>"))
        self.assertLess(article.index("series-nav"), article.index("<h1>"))
        self.assertGreater(article.index("series-step"), article.index("It burns."))

    def test_page_body_is_still_rendered(self):
        self.write_parts()
        self.build()
        page = self.page("02-fire.html")
        self.assertIn("<h1>The fire</h1>", page)
        self.assertIn("It burns.", page)
        self.assertNotIn("{{", page)

    def test_assets_are_rewritten_for_the_subdirectory(self):
        self.write_parts()
        self.build()
        self.assertIn('href="../index.css"', self.page("01-generator.html"))

    def test_canonical_url_includes_the_subdirectory(self):
        self.template.write_text(
            '<link rel="canonical" href="{{ Canonical }}"><article>{{ Content }}</article>',
            encoding="utf-8",
        )
        self.write_parts({"01-a.md": "# A\n"})
        self.build()
        self.assertIn('href="/how_it_works/01-a.html"', self.page("01-a.html"))

    def test_prose_about_the_placeholders_is_left_alone(self):
        """A part that documents the template syntax must keep it verbatim,
        not have it filled in with this page's own values."""
        self.template.write_text(
            "<title>{{ Title }}</title><meta content=\"{{ Description }}\">"
            "<article>{{ Content }}</article>",
            encoding="utf-8",
        )
        self.write_parts({
            "01-a.md": "# A\n\nIntro line.\n\nUse `{{ Description }}`, "
                       "`{{ Canonical }}` and `{{ PageDate }}`.\n",
        })
        self.build()
        body = self.page("01-a.html").split("<article>", 1)[1]
        self.assertIn("{{ Description }}", body)
        self.assertIn("{{ Canonical }}", body)
        self.assertIn("{{ PageDate }}", body)

    def test_hostile_titles_are_escaped_in_the_navigation(self):
        self.write_parts({
            "01-a.md": "# <img src=x onerror=alert(1)>\n\nBody.\n",
            "02-b.md": "# Fish & Chips\n\nBody.\n",
        })
        self.build()
        for name in ("01-a.html", "02-b.html"):
            page = self.page(name)
            nav_markup = "".join(
                re.findall(r'<nav class="series-.*?</nav>', page, re.DOTALL)
            )
            with self.subTest(page=name):
                self.assertNotIn("<img", nav_markup)
                self.assertIn("&lt;img src=x onerror=alert(1)&gt;", nav_markup)
                self.assertIn("Fish &amp; Chips", nav_markup)

    def test_empty_or_missing_series_writes_nothing(self):
        self.assertEqual(self.build(), [])
        shutil_missing = _quiet(
            generate_series, str(self.root / "nope"), str(self.template),
            str(self.out),
        )
        self.assertEqual(shutil_missing, [])
        self.assertFalse(self.out.exists())

    def test_a_part_without_an_h1_writes_no_pages_at_all(self):
        self.write_parts({"01-ok.md": "# Fine\n", "02-bad.md": "no heading\n"})
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.out.exists())

    def test_template_without_an_article_fails_loudly(self):
        self.template.write_text("<body>{{ Content }}</body>", encoding="utf-8")
        self.write_parts({"01-a.md": "# A\n"})
        with self.assertRaises(ValueError):
            self.build()

    def test_part_titles_in_the_nav_match_the_h1_on_each_page(self):
        self.write_parts()
        self.build()
        page = self.page("01-generator.html")
        titles = [t for _, t in _links(page, "series-nav")][1:]
        self.assertEqual(titles, ["The generator", "The fire", "Listening"])


if __name__ == "__main__":
    unittest.main()
