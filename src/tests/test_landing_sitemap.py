import contextlib
import io
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from Gen_Content.generate_landing_page import (
    DEV_DIARY_BLURB,
    GUESTBOOK_BLURB,
    SERIES_BLURB,
    WORKSHOP_BLURB,
    build_sitemap_html,
    gather_sitemap_entries,
    generate_landing_page,
)


class _Entries(HTMLParser):
    """Collects each <li class="page-entry"> as a dict of its parts."""

    def __init__(self):
        super().__init__()
        self.entries = []
        self._field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and attrs.get("class") == "page-entry":
            self.entries.append({})
        elif tag == "a" and self.entries:
            self.entries[-1]["href"] = attrs.get("href")
            self._field = "title"
        elif tag == "p" and self.entries:
            cls = attrs.get("class", "")
            self._field = {"page-blurb": "blurb", "page-stamp": "stamp"}.get(cls)

    def handle_endtag(self, tag):
        if tag in ("a", "p"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.entries:
            self.entries[-1][self._field] = (
                self.entries[-1].get(self._field, "") + data
            )


def _parse(markup):
    parser = _Entries()
    parser.feed(markup)
    return parser.entries


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class TestBuildSitemapHtml(unittest.TestCase):
    def test_exact_markup_for_a_full_entry(self):
        markup = build_sitemap_html([{
            "href": "dev_diary.html",
            "title": "Dev Diary",
            "blurb": "Build notes.",
            "stamp": "9 entries · newest Sep 2, 2026",
        }])
        self.assertEqual(
            markup,
            '              <li class="page-entry">\n'
            '                <a href="dev_diary.html">Dev Diary</a>\n'
            '                <p class="page-blurb">Build notes.</p>\n'
            '                <p class="page-stamp">9 entries · newest Sep 2, 2026</p>\n'
            "              </li>",
        )

    def test_stamp_is_omitted_when_absent(self):
        markup = build_sitemap_html(
            [{"href": "a.html", "title": "A", "blurb": "b"}]
        )
        self.assertNotIn("page-stamp", markup)
        self.assertIn("page-blurb", markup)

    def test_blurb_is_omitted_when_absent_or_empty(self):
        for blurb in (None, ""):
            with self.subTest(blurb=blurb):
                markup = build_sitemap_html(
                    [{"href": "a.html", "title": "A", "blurb": blurb}]
                )
                self.assertNotIn("page-blurb", markup)

    def test_title_only_entry(self):
        markup = build_sitemap_html([{"href": "a.html", "title": "A"}])
        self.assertEqual(
            _parse(markup), [{"href": "a.html", "title": "A"}]
        )

    def test_keeps_the_given_order(self):
        markup = build_sitemap_html([
            {"href": "z.html", "title": "Zed"},
            {"href": "a.html", "title": "Aye"},
            {"href": "m.html", "title": "Em"},
        ])
        self.assertEqual(
            [e["title"] for e in _parse(markup)], ["Zed", "Aye", "Em"]
        )

    def test_no_entries_gives_no_markup(self):
        self.assertEqual(build_sitemap_html([]), "")

    def test_text_is_escaped(self):
        markup = build_sitemap_html([{
            "href": 'x.html"><script>',
            "title": "<b>Bold</b> & co",
            "blurb": "</p><i>no</i>",
            "stamp": "<u>2</u>",
        }])
        self.assertNotIn("<script>", markup)
        for tag in ("<b>", "<i>", "<u>"):
            self.assertNotIn(tag, markup)
        self.assertIn("&lt;b&gt;Bold&lt;/b&gt; &amp; co", markup)
        self.assertIn("&quot;&gt;&lt;script&gt;", markup)

    def test_apostrophes_in_text_stay_readable(self):
        markup = build_sitemap_html(
            [{"href": "a.html", "title": "A", "blurb": "What I've built"}]
        )
        self.assertIn("What I've built", markup)

    def test_parsed_structure_is_one_entry_per_item(self):
        markup = build_sitemap_html([
            {"href": "a.html", "title": "A", "blurb": "ba", "stamp": "sa"},
            {"href": "b.html", "title": "B"},
        ])
        self.assertEqual(_parse(markup), [
            {"href": "a.html", "title": "A", "blurb": "ba", "stamp": "sa"},
            {"href": "b.html", "title": "B"},
        ])


class _SiteCase(unittest.TestCase):
    """A throwaway site: content/ plus a repo-root-like folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.content = self.root / "content"
        self.content.mkdir()

    def write(self, relative, text):
        path = self.content / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def gather(self):
        return _quiet(gather_sitemap_entries, str(self.content), str(self.root))

    def titles(self):
        return [e["title"] for e in self.gather()]

    def entry(self, title):
        return next(e for e in self.gather() if e["title"] == title)


class TestGatherOrderAndPresence(_SiteCase):
    def test_empty_site_still_lists_the_guestbook(self):
        entries = self.gather()
        self.assertEqual([e["title"] for e in entries], ["Guestbook"])
        self.assertEqual(entries[0]["href"], "guestbook.html")
        self.assertEqual(entries[0]["blurb"], GUESTBOOK_BLURB)
        self.assertFalse(entries[0].get("stamp"))

    def test_full_site_order(self):
        self.write("dev_diary/2026-01-01-a.md", "# A\n")
        (self.root / "workshop.html").write_text("<html>", encoding="utf-8")
        self.write("how_it_works/01-generator.md", "# Gen\n")
        self.write("aboutme.md", "# About Me\n")
        self.write("zebra.md", "# Zebra\n")
        self.assertEqual(
            self.titles(),
            ["Dev Diary", "Workshop", "How This Site Works", "Guestbook",
             "About Me", "Zebra"],
        )

    def test_dev_diary_needs_its_directory(self):
        self.assertNotIn("Dev Diary", self.titles())
        (self.content / "dev_diary").mkdir()
        self.assertIn("Dev Diary", self.titles())

    def test_workshop_needs_its_template(self):
        self.assertNotIn("Workshop", self.titles())
        (self.root / "workshop.html").write_text("<html>", encoding="utf-8")
        self.assertIn("Workshop", self.titles())

    def test_series_needs_at_least_one_markdown_part(self):
        (self.content / "how_it_works").mkdir()
        self.assertNotIn("How This Site Works", self.titles())
        self.write("how_it_works/notes.txt", "not markdown")
        self.assertNotIn("How This Site Works", self.titles())
        self.write("how_it_works/01-generator.md", "# Gen\n")
        self.assertIn("How This Site Works", self.titles())

    def test_fixed_copy(self):
        self.write("dev_diary/2026-01-01-a.md", "# A\n")
        (self.root / "workshop.html").write_text("<html>", encoding="utf-8")
        self.write("how_it_works/01-generator.md", "# Gen\n")
        self.assertEqual(self.entry("Dev Diary")["blurb"], DEV_DIARY_BLURB)
        self.assertEqual(self.entry("Workshop")["blurb"], WORKSHOP_BLURB)
        self.assertEqual(self.entry("How This Site Works")["blurb"], SERIES_BLURB)
        self.assertEqual(self.entry("Dev Diary")["href"], "dev_diary.html")
        self.assertEqual(self.entry("Workshop")["href"], "workshop.html")

    def test_workshop_has_no_stamp(self):
        (self.root / "workshop.html").write_text("<html>", encoding="utf-8")
        self.assertFalse(self.entry("Workshop").get("stamp"))

    def test_missing_content_directory_still_lists_the_guestbook(self):
        entries = _quiet(
            gather_sitemap_entries, str(self.root / "nope"), str(self.root)
        )
        self.assertEqual([e["title"] for e in entries], ["Guestbook"])


class TestSeriesEntry(_SiteCase):
    def test_links_to_the_first_part_in_sorted_order(self):
        self.write("how_it_works/03-listening.md", "# L\n")
        self.write("how_it_works/01-generator.md", "# G\n")
        self.write("how_it_works/02-fire.md", "# F\n")
        entry = self.entry("How This Site Works")
        self.assertEqual(entry["href"], "how_it_works/01-generator.html")
        self.assertEqual(entry["stamp"], "3 parts")

    def test_one_part_is_singular(self):
        self.write("how_it_works/01-generator.md", "# G\n")
        self.assertEqual(self.entry("How This Site Works")["stamp"], "1 part")

    def test_only_markdown_counts_as_a_part(self):
        self.write("how_it_works/01-generator.md", "# G\n")
        self.write("how_it_works/draft.txt", "x")
        self.assertEqual(self.entry("How This Site Works")["stamp"], "1 part")


class TestDevDiaryStamp(_SiteCase):
    def stamp(self):
        return self.entry("Dev Diary")["stamp"]

    def test_counts_entries_and_names_the_newest(self):
        self.write("dev_diary/2025-11-11-a.md",
                   "<!-- page-date: 2025-11-11 -->\n# A\n")
        self.write("dev_diary/2026-09-02-b.md",
                   "<!-- page-date: 2026-09-02 -->\n# B\n")
        self.assertEqual(self.stamp(), "2 entries · newest Sep 2, 2026")

    def test_one_entry_is_singular(self):
        self.write("dev_diary/2026-09-02-b.md",
                   "<!-- page-date: 2026-09-02 -->\n# B\n")
        self.assertEqual(self.stamp(), "1 entry · newest Sep 2, 2026")

    def test_page_date_comment_beats_the_filename(self):
        self.write("dev_diary/2020-01-01-old-name.md",
                   "<!-- page-date: 2026-03-04 -->\n# A\n")
        self.assertEqual(self.stamp(), "1 entry · newest Mar 4, 2026")

    def test_falls_back_to_the_filename_date(self):
        self.write("dev_diary/2026-05-28-carried-away.md", "# A\n")
        self.assertEqual(self.stamp(), "1 entry · newest May 28, 2026")

    def test_filename_date_with_an_unpadded_day(self):
        self.write("dev_diary/2025-12-1-advent.md", "# A\n")
        self.assertEqual(self.stamp(), "1 entry · newest Dec 1, 2025")

    def test_newest_is_by_date_not_by_filename_order(self):
        self.write("dev_diary/a-first-alphabetically.md",
                   "<!-- page-date: 2026-06-06 -->\n# A\n")
        self.write("dev_diary/z-last-alphabetically.md",
                   "<!-- page-date: 2025-01-01 -->\n# Z\n")
        self.assertEqual(self.stamp(), "2 entries · newest Jun 6, 2026")

    def test_undated_posts_still_count_but_cannot_be_newest(self):
        self.write("dev_diary/2026-02-02-dated.md", "# A\n")
        self.write("dev_diary/untitled-notes.md", "# B\n")
        self.assertEqual(self.stamp(), "2 entries · newest Feb 2, 2026")

    def test_no_dates_at_all_gives_just_the_count(self):
        self.write("dev_diary/notes.md", "# A\n")
        self.assertEqual(self.stamp(), "1 entry")

    def test_impossible_dates_are_ignored(self):
        self.write("dev_diary/2026-02-31-bad.md",
                   "<!-- page-date: 2026-13-45 -->\n# A\n")
        self.assertEqual(self.stamp(), "1 entry")

    def test_empty_diary_has_no_stamp(self):
        (self.content / "dev_diary").mkdir()
        self.assertFalse(self.entry("Dev Diary").get("stamp"))

    def test_non_markdown_files_are_not_entries(self):
        self.write("dev_diary/2026-02-02-a.md", "# A\n")
        self.write("dev_diary/images.txt", "x")
        self.assertTrue(self.stamp().startswith("1 entry"))

    def test_never_writes_back_to_a_post(self):
        """generate_blog_index stamps a missing page-date into the file. The
        landing page must only read."""
        body = "# Undated\n\nText.\n"
        path = self.write("dev_diary/2026-02-02-undated.md", body)
        before = path.read_bytes()
        self.gather()
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("page-date", path.read_text(encoding="utf-8"))

    def test_tolerates_a_non_utf8_post(self):
        (self.content / "dev_diary").mkdir()
        (self.content / "dev_diary" / "2026-02-02-bad.md").write_bytes(
            b"\xff\xfe\x00# bad"
        )
        self.assertEqual(self.stamp(), "1 entry · newest Feb 2, 2026")


class TestTopLevelPages(_SiteCase):
    def test_title_comes_from_the_h1(self):
        self.write("aboutme.md", "# About Me\n")
        self.assertEqual(self.entry("About Me")["href"], "aboutme.html")

    def test_landing_title_comment_wins(self):
        self.write("aboutme.md", "<!-- landing-title: Who I Am -->\n# About Me\n")
        self.assertIn("Who I Am", self.titles())
        self.assertNotIn("About Me", self.titles())

    def test_filename_is_the_last_resort(self):
        self.write("some_page-name.md", "no heading here\n")
        self.assertIn("Some Page Name", self.titles())

    def test_blurb_from_the_landing_blurb_comment(self):
        self.write(
            "aboutme.md",
            "<!-- page-date: 2025-11-11 -->\n"
            "<!-- landing-blurb: Diablo II, the Navy, Linux, and the Salamanders. -->\n"
            "# About Me\n",
        )
        self.assertEqual(
            self.entry("About Me")["blurb"],
            "Diablo II, the Navy, Linux, and the Salamanders.",
        )

    def test_blurb_only_counts_near_the_top(self):
        self.write("aboutme.md", "# About Me\n\n\n\n\n\n\n"
                   "<!-- landing-blurb: too far down -->\n")
        self.assertFalse(self.entry("About Me").get("blurb"))

    def test_no_blurb_comment_means_no_blurb(self):
        self.write("aboutme.md", "# About Me\n")
        self.assertFalse(self.entry("About Me").get("blurb"))

    def test_empty_blurb_comment_means_no_blurb(self):
        self.write("aboutme.md", "<!-- landing-blurb: -->\n# About Me\n")
        self.assertFalse(self.entry("About Me").get("blurb"))

    def test_subdirectories_are_not_top_level_pages(self):
        self.write("dev_diary/2026-01-01-a.md", "# Post\n")
        self.write("how_it_works/01-generator.md", "# Part\n")
        self.assertNotIn("Post", self.titles())
        self.assertNotIn("Part", self.titles())

    def test_pages_are_listed_in_filename_order(self):
        self.write("b.md", "# Bee\n")
        self.write("a.md", "# Aye\n")
        self.assertEqual(self.titles()[-2:], ["Aye", "Bee"])

    def test_non_markdown_files_are_ignored(self):
        self.write("listening.json", "{}")
        self.write("notes.txt", "x")
        self.assertEqual(self.titles(), ["Guestbook"])

    def test_unreadable_page_keeps_a_filename_title(self):
        (self.content / "broken_page.md").write_bytes(b"\xff\xfe\x00bad")
        self.assertIn("Broken Page", self.titles())

    def test_real_content_blurb_for_the_about_page(self):
        """The shipped aboutme.md carries the agreed blurb."""
        repo = Path(__file__).resolve().parents[2]
        entries = _quiet(
            gather_sitemap_entries, str(repo / "content"), str(repo)
        )
        about = next(e for e in entries if e["href"] == "aboutme.html")
        self.assertEqual(
            about["blurb"], "Diablo II, the Navy, Linux, and the Salamanders."
        )


TEMPLATE = """<title>{{ Title }}</title>
<p>{{ SiteDescription }} {{ Year }}</p>
<ul class="page-links">
{{ PageLinks }}
</ul>
<ul class="now-tracks">
{{ ListeningTracks }}
</ul>
<p class="now-stamp">{{ ListeningStamp }}</p>
<h4>Playing</h4>
<!-- playing:start -->
              <ul class="now-list now-games">
                <li><span class="title">Hand Picked Game</span></li>
              </ul>
              <p class="now-stamp">hand-picked</p>
<!-- playing:end -->
"""

CONFIG = {
    "title": "Home", "site_title": "T", "site_author": "A",
    "description": "d", "site_description": "sd",
}


class TestGenerateLandingPage(_SiteCase):
    def generate(self, template=TEMPLATE):
        template_path = self.root / "titlepage.html"
        template_path.write_text(template, encoding="utf-8")
        dest = self.root / "out" / "index.html"
        _quiet(
            generate_landing_page,
            str(self.content), str(template_path), str(dest), CONFIG,
        )
        return dest.read_text(encoding="utf-8")

    def test_page_links_are_the_sitemap(self):
        self.write("aboutme.md", "<!-- landing-blurb: hi -->\n# About Me\n")
        page = self.generate()
        entries = _parse(page.split('class="page-links"', 1)[1].split("</ul>", 1)[0])
        self.assertEqual([e["title"] for e in entries], ["Guestbook", "About Me"])

    def test_leaves_no_placeholders(self):
        self.assertNotIn("{{", self.generate())

    def test_no_playing_file_keeps_the_hand_picked_list_and_drops_markers(self):
        page = self.generate()
        self.assertIn("Hand Picked Game", page)
        self.assertIn("hand-picked", page)
        self.assertNotIn("playing:", page)

    def test_playing_file_replaces_the_hand_picked_list(self):
        self.write("playing.json", json.dumps({
            "fetched_at": "2026-11-24T01:38:35Z",
            "games": [{"name": "Hades", "hours_2weeks": 4.5}],
        }))
        page = self.generate()
        self.assertIn('<span class="title">Hades</span>', page)
        self.assertIn("4.5h", page)
        self.assertNotIn("Hand Picked Game", page)
        self.assertNotIn("playing:", page)

    def test_empty_games_file_shows_the_live_empty_state(self):
        self.write("playing.json", json.dumps({"games": []}))
        page = self.generate()
        self.assertIn("Nothing in the last two weeks", page)
        self.assertNotIn("Hand Picked Game", page)

    def test_malformed_playing_file_keeps_the_hand_picked_list(self):
        self.write("playing.json", "{not json")
        page = self.generate()
        self.assertIn("Hand Picked Game", page)

    def test_listening_without_plays_renders_fine(self):
        """A listening.json from before play counts existed."""
        self.write("listening.json", json.dumps({
            "fetched_at": "2026-11-24T01:38:35Z",
            "tracks": [{"artist": "Trivium", "title": "One"},
                       {"artist": "Trivium", "title": "Two"}],
        }))
        page = self.generate()
        self.assertIn('<span class="title">One</span>', page)
        self.assertIn('<li class="same-artist">', page)
        self.assertNotIn('class="plays"', page)
        self.assertIn("top 2 this week · updated Nov 24", page)

    def test_data_that_looks_like_a_placeholder_is_not_substituted(self):
        self.write("listening.json", json.dumps({"tracks": [
            {"artist": "{{ Year }}", "title": "{{ SiteDescription }}"},
        ]}))
        self.write("playing.json", json.dumps({
            "games": [{"name": "{{ Title }}", "hours_2weeks": 1}],
        }))
        page = self.generate()
        self.assertIn("{{ Year }}", page)
        self.assertIn("{{ SiteDescription }}", page)
        self.assertIn("{{ Title }}", page)

    def test_unknown_placeholders_are_left_alone(self):
        self.assertIn("{{ Mystery }}", self.generate(TEMPLATE + "{{ Mystery }}\n"))

    def test_creates_the_destination_directory(self):
        self.generate()
        self.assertTrue((self.root / "out" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
