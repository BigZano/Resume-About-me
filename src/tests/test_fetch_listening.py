import unittest

from fetch_listening import TRACK_LIMIT, parse_top_tracks


def _item(artist, title):
    return {"name": title, "artists": [{"name": artist}]}


def _payload(*pairs):
    return {"items": [_item(a, t) for a, t in pairs]}


class TestParseTopTracks(unittest.TestCase):
    def test_extracts_artist_and_title(self):
        result = parse_top_tracks(_payload(("Tech N9ne", "Speedom")))
        self.assertEqual(
            result, [{"artist": "Tech N9ne", "title": "Speedom"}]
        )

    def test_preserves_order(self):
        result = parse_top_tracks(_payload(("A", "1"), ("B", "2"), ("C", "3")))
        self.assertEqual([t["title"] for t in result], ["1", "2", "3"])

    def test_uses_only_the_first_artist(self):
        payload = {"items": [{
            "name": "Collab",
            "artists": [{"name": "First"}, {"name": "Second"}],
        }]}
        self.assertEqual(parse_top_tracks(payload)[0]["artist"], "First")

    def test_honours_the_limit(self):
        payload = _payload(*[(f"A{i}", f"T{i}") for i in range(50)])
        self.assertEqual(len(parse_top_tracks(payload, limit=10)), 10)

    def test_default_limit_is_ten(self):
        self.assertEqual(TRACK_LIMIT, 10)
        payload = _payload(*[(f"A{i}", f"T{i}") for i in range(50)])
        self.assertEqual(len(parse_top_tracks(payload)), 10)

    def test_returns_fewer_than_limit_when_that_is_all_there_is(self):
        self.assertEqual(len(parse_top_tracks(_payload(("A", "1")))), 1)

    def test_strips_whitespace(self):
        result = parse_top_tracks(_payload(("  A  ", "  T  ")))
        self.assertEqual(result, [{"artist": "A", "title": "T"}])

    def test_skips_unusable_items_but_keeps_good_ones(self):
        payload = {"items": [
            _item("Good", "Song"),
            "not a dict",
            {"name": "No artists", "artists": []},
            {"name": "Null artist", "artists": [{"name": None}]},
            {"artists": [{"name": "No title"}]},
            {"name": "", "artists": [{"name": "Empty title"}]},
            {"name": "Bad artist entry", "artists": ["string"]},
        ]}
        result = parse_top_tracks(payload)
        self.assertEqual(result, [{"artist": "Good", "title": "Song"}])


class TestParseTopTracksRejections(unittest.TestCase):
    """Anything unusable must raise, never return empty.

    Returning [] would let the caller write an empty file and blank the
    page — the one thing this pipeline must never do.
    """

    def test_zero_tracks_raises(self):
        with self.assertRaises(ValueError):
            parse_top_tracks({"items": []})

    def test_all_items_unusable_raises(self):
        with self.assertRaises(ValueError):
            parse_top_tracks({"items": ["x", 1, {}]})

    def test_missing_items_key_raises(self):
        with self.assertRaises(ValueError):
            parse_top_tracks({"total": 0})

    def test_items_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            parse_top_tracks({"items": "Speedom"})

    def test_non_dict_payload_raises(self):
        for bad in [None, "payload", 42, []]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_top_tracks(bad)


if __name__ == "__main__":
    unittest.main()
