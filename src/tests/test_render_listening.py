import json
import os
import tempfile
import unittest

from Gen_Content.render_listening import (
    STAMP_EMPTY,
    STAMP_LIVE,
    load_listening,
    render_listening,
)


def _data(*pairs):
    return {"tracks": [{"artist": a, "title": t} for a, t in pairs]}


class TestRenderListening(unittest.TestCase):
    def test_renders_one_track(self):
        html, stamp = render_listening(_data(("Tech N9ne", "Speedom")))
        self.assertIn("<span>Tech N9ne</span> Speedom", html)
        self.assertEqual(stamp, STAMP_LIVE)

    def test_renders_every_track_in_order(self):
        html, _ = render_listening(
            _data(("A", "One"), ("B", "Two"), ("C", "Three"))
        )
        self.assertEqual(html.count("<li>"), 3)
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
        self.assertEqual(html.count("<li>"), 1)
        self.assertIn("Good", html)
        self.assertEqual(stamp, STAMP_LIVE)

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
        """Property: no supplied text ever reaches output as live markup."""
        hostile = [
            '<img src=x onerror=alert(1)>',
            '"><script>alert(1)</script>',
            "' onmouseover='alert(1)",
            "</span></li><li>injected",
            "&<>\"'",
        ]
        for payload in hostile:
            with self.subTest(payload=payload):
                html, _ = render_listening(_data((payload, payload)))
                # Strip the markup this module legitimately emits, then
                # assert nothing tag-like survives from the input.
                residue = (
                    html.replace("<li>", "")
                    .replace("</li>", "")
                    .replace("<span>", "")
                    .replace("</span>", "")
                )
                self.assertNotIn("<", residue)
                self.assertNotIn(">", residue)

    def test_unicode_and_emoji_survive_intact(self):
        html, _ = render_listening(_data(("Sigur Rós", "Hoppípolla 🎵")))
        self.assertIn("Sigur Rós", html)
        self.assertIn("Hoppípolla 🎵", html)

    def test_whitespace_is_trimmed(self):
        html, _ = render_listening(_data(("  Spaced  ", "  Out  ")))
        self.assertIn("<span>Spaced</span> Out", html)


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
