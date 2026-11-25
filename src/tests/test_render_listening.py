import json
import os
import tempfile
import unittest
from html.parser import HTMLParser

from Gen_Content.render_listening import (
    STAMP_EMPTY,
    load_listening,
    render_listening,
)


def _data(*pairs):
    return {"tracks": [{"artist": a, "title": t} for a, t in pairs]}


def _ranked(*triples, fetched_at=None):
    """Data whose tracks carry play counts: (artist, title, plays)."""
    data = {"tracks": [
        {"artist": a, "title": t, "plays": p} for a, t, p in triples
    ]}
    if fetched_at is not None:
        data["fetched_at"] = fetched_at
    return data


class _Tags(HTMLParser):
    """Records every start tag as (tag, attrs) and all character data."""

    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def _parse(markup):
    parser = _Tags()
    parser.feed(markup)
    return parser


class TestRenderListening(unittest.TestCase):
    def test_renders_one_track(self):
        html, stamp = render_listening(_data(("Tech N9ne", "Speedom")))
        self.assertIn(
            '<li><span class="artist">Tech N9ne</span> '
            '<span class="title">Speedom</span></li>',
            html,
        )
        self.assertEqual(stamp, "top 1 this week")

    def test_renders_every_track_in_order(self):
        html, _ = render_listening(
            _data(("A", "One"), ("B", "Two"), ("C", "Three"))
        )
        self.assertEqual(html.count("<li"), 3)
        self.assertLess(html.index("One"), html.index("Two"))
        self.assertLess(html.index("Two"), html.index("Three"))

    def test_none_gives_empty_state(self):
        html, stamp = render_listening(None)
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_empty_track_list_gives_empty_state(self):
        html, stamp = render_listening({"tracks": []})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_missing_tracks_key_gives_empty_state(self):
        html, stamp = render_listening({"fetched_at": "2026-08-09T00:00:00Z"})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_tracks_not_a_list_gives_empty_state(self):
        html, stamp = render_listening({"tracks": "Speedom"})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_non_dict_input_gives_empty_state(self):
        for bad in ["string", 42, [], True]:
            with self.subTest(bad=bad):
                html, stamp = render_listening(bad)
                self.assertIn("Nothing logged yet", html)
                self.assertEqual(stamp, STAMP_EMPTY)

    def test_skips_malformed_entries_but_keeps_good_ones(self):
        data = {"tracks": [
            {"artist": "Good", "title": "Song"},
            "not a dict",
            {"artist": "", "title": ""},
            {"no": "keys"},
        ]}
        html, stamp = render_listening(data)
        self.assertEqual(html.count("<li"), 1)
        self.assertIn("Good", html)
        self.assertEqual(stamp, "top 1 this week")

    def test_all_entries_malformed_gives_empty_state(self):
        html, stamp = render_listening({"tracks": ["x", 1, {}]})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)


class TestEscaping(unittest.TestCase):
    def test_ampersand_is_escaped(self):
        html, _ = render_listening(_data(("Simon & Garfunkel", "The Boxer")))
        self.assertIn("Simon &amp; Garfunkel", html)
        self.assertNotIn("Simon & Garfunkel", html)

    def test_angle_brackets_are_escaped(self):
        html, _ = render_listening(_data(("<script>", "</script>")))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_input_can_inject_a_raw_tag(self):
        """Property: no supplied text ever reaches output as live markup.

        Parses the output and checks the only elements are the ones this
        module emits, with only the attributes it emits. A payload that
        broke out of its span would show up as an extra tag or attribute.
        """
        hostile = [
            '<img src=x onerror=alert(1)>',
            '"><script>alert(1)</script>',
            "' onmouseover='alert(1)",
            "</span></li><li>injected",
            "&<>\"'",
        ]
        allowed = {
            ("li", frozenset()),
            ("li", frozenset({"class"})),
            ("span", frozenset({"class"})),
        }
        for payload in hostile:
            with self.subTest(payload=payload):
                data = {"tracks": [
                    {"artist": payload, "title": payload, "plays": 3},
                    {"artist": payload, "title": payload, "plays": 1},
                ]}
                markup, stamp = render_listening(data)
                parsed = _parse(markup)
                for tag, attrs in parsed.tags:
                    self.assertIn((tag, frozenset(attrs)), allowed)
                    if "class" in attrs:
                        self.assertIn(attrs["class"], {
                            "same-artist", "artist", "title", "plays", "vh",
                        })
                # Two rows in, exactly two <li> out.
                self.assertEqual(
                    [t for t, _ in parsed.tags].count("li"), 2
                )
                # The payload survives as inert text, not as markup.
                self.assertIn(payload, "".join(parsed.text))
                self.assertNotIn("<", stamp)

    def test_unicode_and_emoji_survive_intact(self):
        html, _ = render_listening(_data(("Sigur Rós", "Hoppípolla 🎵")))
        self.assertIn("Sigur Rós", html)
        self.assertIn("Hoppípolla 🎵", html)

    def test_whitespace_is_trimmed(self):
        html, _ = render_listening(_data(("  Spaced  ", "  Out  ")))
        self.assertIn('<span class="artist">Spaced</span>', html)
        self.assertIn('<span class="title">Out</span>', html)


class TestPlays(unittest.TestCase):
    def test_renders_the_play_count_with_a_screen_reader_suffix(self):
        html, _ = render_listening(_ranked(("Trivium", "Jorōgumo", 14)))
        self.assertIn(
            '<span class="plays">×14<span class="vh"> plays</span></span>',
            html,
        )

    def test_exact_row_markup_matches_the_contract(self):
        html, _ = render_listening(_ranked(("Trivium", "Jorōgumo", 14)))
        self.assertEqual(
            html.strip(),
            '<li><span class="artist">Trivium</span> '
            '<span class="title">Jorōgumo</span> '
            '<span class="plays">×14<span class="vh"> plays</span></span>'
            "</li>",
        )

    def test_one_play_is_singular(self):
        html, _ = render_listening(_ranked(("A", "B", 1)))
        self.assertIn('×1<span class="vh"> play</span>', html)
        self.assertNotIn("plays</span>", html)

    def test_missing_plays_omits_the_span(self):
        html, _ = render_listening(_data(("A", "B")))
        self.assertNotIn("plays", html)
        self.assertNotIn("×", html)

    def test_unusable_plays_omit_the_span_but_keep_the_row(self):
        for bad in (True, False, 0, -3, 2.0, 2.5, "14", None, [], {}):
            with self.subTest(plays=bad):
                data = {"tracks": [{"artist": "A", "title": "B", "plays": bad}]}
                html, stamp = render_listening(data)
                self.assertIn('<span class="title">B</span>', html)
                self.assertNotIn("plays", html)
                self.assertEqual(stamp, "top 1 this week")

    def test_large_counts_render_plainly(self):
        html, _ = render_listening(_ranked(("A", "B", 12345)))
        self.assertIn("×12345", html)


class TestSameArtist(unittest.TestCase):
    def _classes(self, data):
        html, _ = render_listening(data)
        return [
            "same-artist" if '<li class="same-artist">' in line else "plain"
            for line in html.splitlines()
        ]

    def test_first_row_is_never_a_repeat(self):
        self.assertEqual(self._classes(_data(("A", "x"))), ["plain"])

    def test_consecutive_same_artist_is_marked(self):
        data = _ranked(("Trivium", "One", 14), ("Trivium", "Two", 11))
        html, _ = render_listening(data)
        self.assertIn(
            '<li class="same-artist"><span class="artist">Trivium</span> '
            '<span class="title">Two</span>',
            html,
        )

    def test_repeated_artist_row_is_still_complete(self):
        """The CSS hides the name; the markup must keep it for screen readers."""
        data = _ranked(("Trivium", "One", 14), ("Trivium", "Two", 11))
        html, _ = render_listening(data)
        second = html.splitlines()[1]
        self.assertIn('<span class="artist">Trivium</span>', second)
        self.assertIn('<span class="plays">', second)

    def test_run_of_three_marks_the_second_and_third(self):
        data = _data(("A", "1"), ("A", "2"), ("A", "3"))
        self.assertEqual(self._classes(data), ["plain", "same-artist", "same-artist"])

    def test_a_different_artist_between_breaks_the_run(self):
        data = _data(("A", "1"), ("B", "2"), ("A", "3"))
        self.assertEqual(self._classes(data), ["plain", "plain", "plain"])

    def test_comparison_is_case_sensitive(self):
        data = _data(("trivium", "1"), ("Trivium", "2"))
        self.assertEqual(self._classes(data), ["plain", "plain"])

    def test_comparison_ignores_surrounding_whitespace(self):
        data = _data(("Trivium", "1"), ("  Trivium ", "2"))
        self.assertEqual(self._classes(data), ["plain", "same-artist"])

    def test_skipped_malformed_entry_does_not_break_the_run(self):
        data = {"tracks": [
            {"artist": "A", "title": "1"},
            "junk",
            {"artist": "A", "title": "2"},
        ]}
        self.assertEqual(self._classes(data), ["plain", "same-artist"])

    def test_rows_without_an_artist_are_never_marked(self):
        data = _data(("", "Untitled 1"), ("", "Untitled 2"))
        self.assertEqual(self._classes(data), ["plain", "plain"])

    def test_missing_title_still_renders_the_artist(self):
        html, _ = render_listening(_data(("Solo", "")))
        self.assertIn('<span class="artist">Solo</span>', html)
        self.assertNotIn('class="title"', html)

    def test_missing_artist_still_renders_the_title(self):
        html, _ = render_listening(_data(("", "Orphan")))
        self.assertIn('<span class="title">Orphan</span>', html)
        self.assertNotIn('class="artist"', html)


class TestStamp(unittest.TestCase):
    def test_live_stamp_names_the_count_and_the_date(self):
        data = _ranked(*[("A", str(i), 1) for i in range(10)],
                       fetched_at="2026-11-24T01:38:35Z")
        _, stamp = render_listening(data)
        self.assertEqual(stamp, "top 10 this week · updated Nov 24")

    def test_day_has_no_leading_zero(self):
        data = _ranked(("A", "x", 1), fetched_at="2026-09-02T12:00:00Z")
        _, stamp = render_listening(data)
        self.assertEqual(stamp, "top 1 this week · updated Sep 2")

    def test_fewer_than_ten_uses_the_real_count(self):
        data = _ranked(*[("A", str(i), 1) for i in range(7)],
                       fetched_at="2026-11-24T01:38:35Z")
        _, stamp = render_listening(data)
        self.assertTrue(stamp.startswith("top 7 this week"))

    def test_count_is_of_rendered_rows_not_input_rows(self):
        data = {"tracks": [{"artist": "A", "title": "x"}, "junk", {}],
                "fetched_at": "2026-11-24T01:38:35Z"}
        _, stamp = render_listening(data)
        self.assertTrue(stamp.startswith("top 1 this week"))

    def test_missing_fetched_at_drops_the_date(self):
        _, stamp = render_listening(_ranked(*[("A", str(i), 1) for i in range(10)]))
        self.assertEqual(stamp, "top 10 this week")

    def test_unparsable_fetched_at_drops_the_date(self):
        for bad in ("yesterday", "", "2026-13-40T00:00:00Z", 12345, None, []):
            with self.subTest(fetched_at=bad):
                data = _ranked(("A", "x", 1))
                data["fetched_at"] = bad
                _, stamp = render_listening(data)
                self.assertEqual(stamp, "top 1 this week")

    def test_date_is_read_in_the_timestamps_own_zone(self):
        """01:38 UTC is still the 24th, whatever the build machine's zone."""
        data = _ranked(("A", "x", 1), fetched_at="2026-11-24T01:38:35Z")
        _, stamp = render_listening(data)
        self.assertTrue(stamp.endswith("Nov 24"))

    def test_every_month_label(self):
        names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for month, name in enumerate(names, start=1):
            with self.subTest(month=month):
                data = _ranked(("A", "x", 1),
                               fetched_at=f"2026-{month:02d}-15T00:00:00Z")
                _, stamp = render_listening(data)
                self.assertTrue(stamp.endswith(f"{name} 15"))

    def test_empty_state_stamp_is_unchanged(self):
        self.assertEqual(render_listening({"tracks": []})[1], "not yet live")


class TestLoadListening(unittest.TestCase):
    def test_missing_file_is_silent(self):
        data, warning = load_listening("/nonexistent/listening.json")
        self.assertIsNone(data)
        self.assertIsNone(warning)

    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "listening.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(_data(("A", "B")), handle)
            data, warning = load_listening(path)
            self.assertIsNone(warning)
            assert data is not None
            self.assertEqual(data["tracks"][0]["artist"], "A")

    def test_malformed_json_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "listening.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            data, warning = load_listening(path)
            self.assertIsNone(data)
            assert warning is not None
            self.assertIn("Warning", warning)


if __name__ == "__main__":
    unittest.main()
