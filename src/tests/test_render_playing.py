import json
import os
import tempfile
import unittest
from html.parser import HTMLParser

from Gen_Content.render_playing import (
    STAMP_LIVE,
    apply_playing,
    load_playing,
    render_playing,
)

FALLBACK = (
    '              <ul class="now-list now-games">\n'
    '                <li><span class="title">Oblivion Remastered</span></li>\n'
    "              </ul>\n"
    '              <p class="now-stamp">hand-picked</p>'
)

TEMPLATE = (
    "<section>\n"
    "              <h4>Playing</h4>\n"
    "<!-- playing:start -->\n"
    f"{FALLBACK}\n"
    "<!-- playing:end -->\n"
    "</section>\n"
)


def _data(*games):
    return {"fetched_at": "2026-11-24T01:38:35Z", "games": list(games)}


def _game(name, hours):
    return {"name": name, "hours_2weeks": hours}


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class TestRenderPlaying(unittest.TestCase):
    def test_matches_the_contract_exactly(self):
        block = render_playing(_data(_game("Oblivion Remastered", 6.2)))
        self.assertEqual(
            block,
            '              <ul class="now-list now-games">\n'
            '                <li><span class="title">Oblivion Remastered</span> '
            '<span class="hours">6.2h<span class="vh"> in the last two weeks'
            "</span></span></li>\n"
            "              </ul>\n"
            '              <p class="now-stamp">last two weeks · Steam</p>',
        )

    def test_stamp_constant_is_the_contract_copy(self):
        self.assertEqual(STAMP_LIVE, "last two weeks · Steam")

    def test_renders_every_game_in_order(self):
        block = render_playing(
            _data(_game("One", 5), _game("Two", 3), _game("Three", 1))
        )
        self.assertEqual(block.count("<li>"), 3)
        self.assertLess(block.index("One"), block.index("Two"))
        self.assertLess(block.index("Two"), block.index("Three"))

    def test_hours_use_one_decimal(self):
        for hours, shown in [(6.2, "6.2h"), (6, "6.0h"), (0.25, "0.2h"),
                             (12.34, "12.3h"), (0.1, "0.1h")]:
            with self.subTest(hours=hours):
                block = render_playing(_data(_game("G", hours)))
                self.assertIn(f'<span class="hours">{shown}<', block)

    def test_hours_that_round_to_zero_are_hidden(self):
        for hours in (0, 0.0, 0.04, 0.0001):
            with self.subTest(hours=hours):
                block = render_playing(_data(_game("Brief", hours)))
                self.assertIn('<li><span class="title">Brief</span></li>', block)
                self.assertNotIn('class="hours"', block)
                self.assertNotIn("0.0h", block)

    def test_hours_just_above_the_rounding_line_are_shown(self):
        block = render_playing(_data(_game("G", 0.06)))
        self.assertIn('<span class="hours">0.1h<', block)

    def test_non_dict_input_keeps_the_fallback(self):
        for bad in (None, "x", 42, [], True):
            with self.subTest(bad=bad):
                self.assertIsNone(render_playing(bad))

    def test_missing_or_bad_games_keeps_the_fallback(self):
        for bad in ({}, {"games": None}, {"games": "Oblivion"},
                    {"games": {"name": "x"}}, {"fetched_at": "2026-11-24T00:00:00Z"}):
            with self.subTest(bad=bad):
                self.assertIsNone(render_playing(bad))

    def test_empty_games_is_a_live_empty_state(self):
        """A public profile with nothing played lately is a real answer, not
        a reason to fall back to the hand-picked list."""
        self.assertEqual(
            render_playing(_data()),
            '              <ul class="now-list now-games">\n'
            "                <li>Nothing in the last two weeks</li>\n"
            "              </ul>\n"
            '              <p class="now-stamp">last two weeks · Steam</p>',
        )

    def test_all_entries_unusable_keeps_the_fallback(self):
        """Games were listed but none readable: that is malformed data, not
        an empty week, so the hand-picked list stays."""
        data = _data("junk", 5, None, {}, {"name": ""}, {"name": "   "},
                     {"name": 7}, {"hours_2weeks": 3})
        self.assertIsNone(render_playing(data))

    def test_skips_unusable_entries_but_keeps_good_ones(self):
        data = _data("junk", _game("Good", 2), {"name": ""}, _game("Also", 1))
        block = render_playing(data)
        self.assertEqual(block.count("<li>"), 2)
        self.assertIn("Good", block)
        self.assertIn("Also", block)

    def test_bad_hours_render_the_name_only(self):
        bad_values = [-1, -0.1, "6.2", None, True, False, [], {},
                      float("nan"), float("inf"), float("-inf")]
        for bad in bad_values:
            with self.subTest(hours=bad):
                block = render_playing(_data(_game("Solo", bad)))
                self.assertIn('<span class="title">Solo</span></li>', block)
                self.assertNotIn("hours", block.replace("now-games", ""))

    def test_missing_hours_renders_the_name_only(self):
        block = render_playing(_data({"name": "Solo"}))
        self.assertIn('<li><span class="title">Solo</span></li>', block)

    def test_name_is_trimmed(self):
        block = render_playing(_data(_game("  Spaced  ", 1)))
        self.assertIn('<span class="title">Spaced</span>', block)


class TestEscaping(unittest.TestCase):
    def test_ampersand_and_angle_brackets_are_escaped(self):
        block = render_playing(_data(_game("Tom & Jerry <3", 1)))
        self.assertIn("Tom &amp; Jerry &lt;3", block)

    def test_no_input_can_inject_a_raw_tag(self):
        """Property: no game name ever reaches output as live markup."""
        hostile = [
            "<img src=x onerror=alert(1)>",
            '"><script>alert(1)</script>',
            "' onmouseover='alert(1)",
            "</span></li><li>injected",
            "&<>\"'",
        ]
        allowed = {
            ("ul", frozenset({"class"})),
            ("li", frozenset()),
            ("span", frozenset({"class"})),
            ("p", frozenset({"class"})),
        }
        for payload in hostile:
            with self.subTest(payload=payload):
                parser = _Tags()
                parser.feed(render_playing(_data(_game(payload, 1.5))))
                for tag, attrs in parser.tags:
                    self.assertIn((tag, frozenset(attrs)), allowed)
                self.assertEqual([t for t, _ in parser.tags].count("li"), 1)
                self.assertIn(payload, "".join(parser.text))

    def test_unicode_survives_intact(self):
        block = render_playing(_data(_game("Pokémon ★ \U0001F3AE", 1)))
        self.assertIn("Pokémon ★ \U0001F3AE", block)


class TestApplyPlaying(unittest.TestCase):
    def test_swaps_the_region_for_live_markup(self):
        page = apply_playing(TEMPLATE, _data(_game("Hades", 4.5)))
        self.assertIn("Hades", page)
        self.assertIn("4.5h", page)
        self.assertNotIn("Oblivion", page)
        self.assertNotIn("hand-picked", page)

    def test_markers_are_removed_when_live(self):
        page = apply_playing(TEMPLATE, _data(_game("Hades", 4.5)))
        self.assertNotIn("playing:start", page)
        self.assertNotIn("playing:end", page)

    def test_surrounding_template_is_untouched(self):
        page = apply_playing(TEMPLATE, _data(_game("Hades", 4.5)))
        self.assertTrue(page.startswith("<section>\n              <h4>Playing</h4>\n"))
        self.assertTrue(page.endswith("</section>\n"))

    def test_live_result_is_exactly_the_block_between_the_neighbours(self):
        data = _data(_game("Hades", 4.5))
        page = apply_playing(TEMPLATE, data)
        self.assertEqual(
            page,
            "<section>\n"
            "              <h4>Playing</h4>\n"
            f"{render_playing(data)}\n"
            "</section>\n",
        )

    def test_no_data_keeps_the_fallback_and_drops_the_markers(self):
        page = apply_playing(TEMPLATE, None)
        self.assertEqual(
            page,
            "<section>\n"
            "              <h4>Playing</h4>\n"
            f"{FALLBACK}\n"
            "</section>\n",
        )

    def test_empty_games_replaces_the_fallback_with_the_empty_state(self):
        page = apply_playing(TEMPLATE, {"games": []})
        self.assertIn("Nothing in the last two weeks", page)
        self.assertIn("last two weeks · Steam", page)
        self.assertNotIn("Oblivion", page)
        self.assertNotIn("hand-picked", page)
        self.assertNotIn("playing:", page)

    def test_unusable_data_keeps_the_fallback(self):
        for bad in ({"games": "x"}, {"games": ["junk"]}, "x", 5, {}):
            with self.subTest(bad=bad):
                page = apply_playing(TEMPLATE, bad)
                self.assertIn("Oblivion Remastered", page)
                self.assertIn("hand-picked", page)
                self.assertNotIn("playing:", page)

    def test_missing_markers_return_the_template_unchanged(self):
        template = "<section>no markers here</section>\n"
        self.assertEqual(apply_playing(template, _data(_game("G", 1))), template)

    def test_a_lone_start_marker_returns_the_template_unchanged(self):
        template = "a\n<!-- playing:start -->\nb\n"
        self.assertEqual(apply_playing(template, _data(_game("G", 1))), template)

    def test_a_lone_end_marker_returns_the_template_unchanged(self):
        template = "a\n<!-- playing:end -->\nb\n"
        self.assertEqual(apply_playing(template, _data(_game("G", 1))), template)

    def test_end_before_start_returns_the_template_unchanged(self):
        template = "<!-- playing:end -->\nx\n<!-- playing:start -->\n"
        self.assertEqual(apply_playing(template, _data(_game("G", 1))), template)

    def test_only_the_first_region_is_replaced(self):
        template = TEMPLATE + TEMPLATE
        page = apply_playing(template, _data(_game("Hades", 1)))
        self.assertEqual(page.count("Hades"), 1)
        self.assertEqual(page.count("Oblivion Remastered"), 1)

    def test_tolerates_spacing_inside_the_marker_comments(self):
        template = f"<!--playing:start-->\n{FALLBACK}\n<!--  playing:end  -->\n"
        page = apply_playing(template, _data(_game("Hades", 1)))
        self.assertIn("Hades", page)
        self.assertNotIn("playing:", page)

    def test_game_names_with_regex_or_template_syntax_are_inserted_literally(self):
        """The replacement is spliced in by slicing, never as a regex template."""
        page = apply_playing(TEMPLATE, _data(_game(r"\1 \g<0> {{ Year }}", 1)))
        self.assertIn(r"\1 \g&lt;0&gt; {{ Year }}", page)

    def test_real_titlepage_markers_survive_a_fallback_run(self):
        """A template with no marker pair is passed through byte for byte."""
        template = "<html>\r\n<body>Playing</body>\r\n</html>\r\n"
        self.assertEqual(apply_playing(template, None), template)


class TestLoadPlaying(unittest.TestCase):
    def test_missing_file_is_silent(self):
        data, warning = load_playing("/nonexistent/playing.json")
        self.assertIsNone(data)
        self.assertIsNone(warning)

    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "playing.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(_data(_game("A", 1.5)), handle)
            data, warning = load_playing(path)
            self.assertIsNone(warning)
            assert data is not None
            self.assertEqual(data["games"][0]["name"], "A")

    def test_malformed_json_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "playing.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            data, warning = load_playing(path)
            self.assertIsNone(data)
            assert warning is not None
            self.assertIn("Warning", warning)

    def test_non_utf8_bytes_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "playing.json")
            with open(path, "wb") as handle:
                handle.write(b"\xff\xfe\x00bad")
            data, warning = load_playing(path)
            self.assertIsNone(data)
            assert warning is not None


if __name__ == "__main__":
    unittest.main()
