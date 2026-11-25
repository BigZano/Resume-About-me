import contextlib
import io
import itertools
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import fetch_listening
from fetch_listening import (
    PLAY_LOG_PATH,
    RECENT_LIMIT,
    TRACK_LIMIT,
    WINDOW_DAYS,
    aggregate_weekly_top,
    load_play_log,
    main,
    merge_play_log,
    parse_recently_played,
    plan_publish,
    publish_chart,
    save_play_log,
    update_play_log,
)

NOW = datetime(2026, 9, 10, 14, 0, 0, tzinfo=UTC)
# A play log long past its warm-up, for tests that are not about warming up.
MATURE_SINCE = NOW - timedelta(days=30)
# The warm-up length as a literal, so a mutated WINDOW_DAYS fails these tests
# even though every symbolic comparison would stay green.
SEVEN_DAYS = timedelta(days=7)
REPO_ROOT = Path(fetch_listening.__file__).resolve().parent.parent


def _stamp(moment):
    """The form Spotify sends: ISO-8601, millisecond precision, trailing Z."""
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ago(**delta):
    return NOW - timedelta(**delta)


def _item(artist, title, played_at):
    return {
        "track": {"name": title, "artists": [{"name": artist}]},
        "played_at": played_at,
    }


def _payload(*items):
    return {"items": list(items)}


def _play(artist, title, moment):
    return {"artist": artist, "title": title, "played_at": _stamp(moment)}


class TestConstants(unittest.TestCase):
    def test_literals_are_pinned(self):
        # Pinned as literals so a mutated constant fails here even though
        # every symbolic test stays green.
        self.assertEqual(TRACK_LIMIT, 10)
        self.assertEqual(WINDOW_DAYS, 7)
        self.assertEqual(RECENT_LIMIT, 50)

    def test_play_log_is_gitignored(self):
        # The log holds timestamps and the repo is public.
        self.assertEqual(PLAY_LOG_PATH.parent.name, ".cache")
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".cache/", ignored.splitlines())


class TestParseRecentlyPlayed(unittest.TestCase):
    def test_extracts_artist_title_and_played_at(self):
        result = parse_recently_played(
            _payload(_item("Tech N9ne", "Speedom", "2026-09-10T14:00:00.123Z"))
        )
        self.assertEqual(result, [{
            "artist": "Tech N9ne",
            "title": "Speedom",
            "played_at": "2026-09-10T14:00:00.123Z",
        }])

    def test_preserves_payload_order(self):
        # Spotify sends newest first; parse must not reorder.
        result = parse_recently_played(_payload(
            _item("B", "2", "2026-09-10T14:00:00Z"),
            _item("A", "1", "2026-09-10T15:00:00Z"),
            _item("C", "3", "2026-09-10T13:00:00Z"),
        ))
        self.assertEqual([p["title"] for p in result], ["2", "1", "3"])

    def test_keeps_repeat_plays_of_one_track(self):
        # Counting plays is the whole point; parse must not de-duplicate.
        result = parse_recently_played(_payload(
            _item("A", "Song", "2026-09-10T14:00:00Z"),
            _item("A", "Song", "2026-09-10T13:00:00Z"),
        ))
        self.assertEqual(len(result), 2)

    def test_uses_only_the_first_artist(self):
        payload = _payload({
            "track": {
                "name": "Collab",
                "artists": [{"name": "First"}, {"name": "Second"}],
            },
            "played_at": "2026-09-10T14:00:00Z",
        })
        self.assertEqual(parse_recently_played(payload)[0]["artist"], "First")

    def test_strips_whitespace(self):
        result = parse_recently_played(
            _payload(_item("  A  ", "  T  ", "  2026-09-10T14:00:00Z  "))
        )
        self.assertEqual(result[0]["artist"], "A")
        self.assertEqual(result[0]["title"], "T")
        self.assertEqual(result[0]["played_at"], "2026-09-10T14:00:00.000Z")

    def test_equivalent_timestamps_normalise_to_one_form(self):
        spellings = [
            "2026-09-10T14:00:00Z",
            "2026-09-10T14:00:00.000Z",
            "2026-09-10T14:00:00+00:00",
            "2026-09-10T16:00:00+02:00",
            "2026-09-10T09:00:00-05:00",
        ]
        for spelling in spellings:
            with self.subTest(spelling=spelling):
                result = parse_recently_played(
                    _payload(_item("A", "T", spelling))
                )
                self.assertEqual(
                    result[0]["played_at"], "2026-09-10T14:00:00.000Z"
                )

    def test_unicode_and_markup_pass_through_untouched(self):
        # Escaping is the renderer's job, not the fetcher's.
        result = parse_recently_played(_payload(
            _item("Simon & Garfunkel", "<b>Jor\u014dgumo</b> \U0001f525",
                  "2026-09-10T14:00:00Z"),
        ))
        self.assertEqual(result[0]["artist"], "Simon & Garfunkel")
        self.assertEqual(result[0]["title"], "<b>Jor\u014dgumo</b> \U0001f525")

    def test_fifty_plays_all_come_back(self):
        payload = _payload(*[
            _item(f"A{i}", f"T{i}", _stamp(_ago(minutes=i)))
            for i in range(RECENT_LIMIT)
        ])
        self.assertEqual(len(parse_recently_played(payload)), 50)

    def test_skips_unusable_items_but_keeps_good_ones(self):
        good_time = "2026-09-10T14:00:00Z"
        payload = _payload(
            _item("Good", "Song", good_time),
            "not a dict",
            None,
            {"played_at": good_time},                                    # no track
            {"track": None, "played_at": good_time},                     # local/removed
            {"track": "string", "played_at": good_time},
            {"track": {"name": "No artists", "artists": []},
             "played_at": good_time},
            {"track": {"name": "Null artist", "artists": [{"name": None}]},
             "played_at": good_time},
            {"track": {"name": "Artist not a dict", "artists": ["x"]},
             "played_at": good_time},
            {"track": {"name": "Artists not a list", "artists": "x"},
             "played_at": good_time},
            {"track": {"artists": [{"name": "No title"}]},
             "played_at": good_time},
            {"track": {"name": "  ", "artists": [{"name": "Blank title"}]},
             "played_at": good_time},
            {"track": {"name": 7, "artists": [{"name": "Numeric title"}]},
             "played_at": good_time},
            # a podcast episode has a show, not artists
            {"track": {"name": "Episode 12", "show": {"name": "A Podcast"}},
             "played_at": good_time},
            _item("No time", "Song", None),
            _item("Bad time", "Song", "yesterday-ish"),
            _item("Number time", "Song", 1757512800),
            _item("Naive time", "Song", "2026-09-10T14:00:00"),
            _item("Overflow time", "Song", "0001-01-01T00:00:00+05:00"),
        )
        result = parse_recently_played(payload)
        self.assertEqual(
            result,
            [{"artist": "Good", "title": "Song",
              "played_at": "2026-09-10T14:00:00.000Z"}],
        )


class TestParseRecentlyPlayedQuietStretch(unittest.TestCase):
    """A well-formed payload with no entries is "no plays", not a fault.

    A red run every 4 hours over a quiet stretch would train the owner to
    ignore real failures.
    """

    def test_an_empty_items_list_means_no_plays(self):
        self.assertEqual(parse_recently_played({"items": []}), [])

    def test_extra_keys_do_not_matter_for_an_empty_list(self):
        payload = {"items": [], "limit": 50, "next": None, "cursors": None}
        self.assertEqual(parse_recently_played(payload), [])

    def test_no_plays_merges_into_an_unchanged_log(self):
        log = [_play("B", "2", _ago(days=3)), _play("A", "1", _ago(hours=1))]
        fresh = parse_recently_played({"items": []})
        self.assertEqual(merge_play_log(log, fresh, NOW), log)

    def test_no_plays_into_an_empty_log_is_an_empty_log_not_an_error(self):
        fresh = parse_recently_played({"items": []})
        self.assertEqual(merge_play_log([], fresh, NOW), [])


class TestParseRecentlyPlayedRejections(unittest.TestCase):
    """Structurally broken payloads must raise, never look like "no plays"."""

    def test_non_empty_items_with_nothing_usable_raises(self):
        # Spotify returned entries but none parse: that smells like a shape
        # change, so it must not be mistaken for a quiet stretch.
        for items in (
            ["x", 1, {}, {"track": {}}],
            [{"track": None, "played_at": "2026-09-10T14:00:00Z"}],
            [_item("A", "T", "not a time")],
            [{"played_at": "2026-09-10T14:00:00Z", "track": {"name": "T"}}],
            [None],
        ):
            with self.subTest(items=items), self.assertRaises(ValueError):
                parse_recently_played({"items": items})

    def test_missing_items_key_raises(self):
        with self.assertRaises(ValueError):
            parse_recently_played({"total": 0})

    def test_items_not_a_list_raises(self):
        for bad in ["Speedom", None, {}, 3]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recently_played({"items": bad})

    def test_non_dict_payload_raises(self):
        for bad in [None, "payload", 42, [], True]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recently_played(bad)

    def test_a_spotify_error_body_raises(self):
        with self.assertRaises(ValueError):
            parse_recently_played(
                {"error": {"status": 401, "message": "token expired"}}
            )


class TestMergePlayLog(unittest.TestCase):
    def test_empty_log_takes_the_fresh_plays(self):
        fresh = [_play("A", "1", _ago(hours=1))]
        self.assertEqual(merge_play_log([], fresh, NOW), fresh)

    def test_nothing_new_leaves_the_log_alone(self):
        log = [_play("A", "1", _ago(hours=1))]
        self.assertEqual(merge_play_log(log, [], NOW), log)

    def test_overlapping_polls_do_not_double_count(self):
        # Every poll returns the last 50 plays, so most of each response is
        # already in the log. Re-merging the same plays must be a no-op.
        shared = _play("A", "1", _ago(hours=2))
        existing = [_play("B", "0", _ago(hours=5)), shared]
        fresh = [shared, _play("C", "2", _ago(hours=1))]
        merged = merge_play_log(existing, fresh, NOW)
        self.assertEqual(len(merged), 3)
        self.assertEqual(sum(p["title"] == "1" for p in merged), 1)

    def test_same_instant_in_a_different_spelling_still_dedupes(self):
        existing = [{"artist": "A", "title": "1",
                     "played_at": "2026-09-10T12:00:00Z"}]
        fresh = [{"artist": "A", "title": "1",
                  "played_at": "2026-09-10T14:00:00+02:00"}]
        self.assertEqual(len(merge_play_log(existing, fresh, NOW)), 1)

    def test_same_track_at_two_times_is_two_plays(self):
        fresh = [_play("A", "1", _ago(hours=1)), _play("A", "1", _ago(hours=2))]
        self.assertEqual(len(merge_play_log([], fresh, NOW)), 2)

    def test_different_tracks_at_one_instant_are_kept_apart(self):
        moment = _ago(hours=1)
        fresh = [_play("A", "1", moment), _play("A", "2", moment),
                 _play("B", "1", moment)]
        self.assertEqual(len(merge_play_log([], fresh, NOW)), 3)

    def test_exactly_seven_days_old_is_kept(self):
        play = _play("A", "1", _ago(days=7))
        self.assertEqual(merge_play_log([], [play], NOW), [play])

    def test_seven_days_and_one_second_is_dropped(self):
        play = _play("A", "1", _ago(days=7, seconds=1))
        self.assertEqual(merge_play_log([], [play], NOW), [])

    def test_seven_days_and_one_millisecond_is_dropped(self):
        play = _play("A", "1", _ago(days=7, milliseconds=1))
        self.assertEqual(merge_play_log([], [play], NOW), [])

    def test_six_days_is_kept(self):
        play = _play("A", "1", _ago(days=6, hours=23, minutes=59))
        self.assertEqual(merge_play_log([], [play], NOW), [play])

    def test_prunes_old_entries_from_both_inputs(self):
        old_existing = _play("A", "old-log", _ago(days=8))
        old_fresh = _play("B", "old-fresh", _ago(days=9))
        keep = _play("C", "keep", _ago(days=1))
        merged = merge_play_log([old_existing, keep], [old_fresh], NOW)
        self.assertEqual(merged, [keep])

    def test_result_is_oldest_first(self):
        a = _play("A", "1", _ago(hours=1))
        b = _play("B", "2", _ago(hours=3))
        c = _play("C", "3", _ago(hours=2))
        self.assertEqual(merge_play_log([a], [b, c], NOW), [b, c, a])

    def test_result_does_not_depend_on_input_order(self):
        plays = [_play("A", "1", _ago(hours=h)) for h in (1, 2, 3)]
        plays.append(_play("B", "2", _ago(hours=2)))
        expected = merge_play_log(plays, [], NOW)
        for perm in itertools.permutations(plays):
            with self.subTest(perm=[p["title"] for p in perm]):
                self.assertEqual(merge_play_log(list(perm), [], NOW), expected)

    def test_merging_twice_changes_nothing(self):
        existing = [_play("A", "1", _ago(days=3)), _play("B", "2", _ago(days=9))]
        fresh = [_play("A", "1", _ago(days=3)), _play("C", "3", _ago(hours=1))]
        once = merge_play_log(existing, fresh, NOW)
        self.assertEqual(merge_play_log(once, fresh, NOW), once)
        self.assertEqual(merge_play_log(once, [], NOW), once)

    def test_later_now_only_ever_shrinks_the_log(self):
        log = [_play("A", str(i), _ago(hours=i * 12)) for i in range(20)]
        previous = None
        for step in range(0, 14 * 24, 6):
            size = len(merge_play_log(log, [], NOW + timedelta(hours=step)))
            if previous is not None:
                self.assertLessEqual(size, previous)
            previous = size
        self.assertEqual(previous, 0)

    def test_unusable_entries_are_dropped_not_fatal(self):
        good = _play("A", "1", _ago(hours=1))
        junk = [
            None, "x", 3, [], {},
            {"artist": "A", "title": "1"},                       # no played_at
            {"artist": "", "title": "1", "played_at": _stamp(_ago(hours=1))},
            {"artist": "A", "title": None, "played_at": _stamp(_ago(hours=1))},
            {"artist": "A", "title": "1", "played_at": "garbage"},
            {"artist": "A", "title": "1", "played_at": "2026-09-10T12:00:00"},
        ]
        self.assertEqual(merge_play_log(junk, junk, NOW), [])
        self.assertEqual(merge_play_log([good, *junk], junk, NOW), [good])

    def test_entries_keep_only_the_three_known_keys(self):
        noisy = dict(_play("A", "1", _ago(hours=1)), id="spotify:track:xyz",
                     uri="https://open.spotify.com/track/xyz")
        merged = merge_play_log([noisy], [], NOW)
        self.assertEqual(set(merged[0]), {"artist", "title", "played_at"})

    def test_does_not_mutate_its_inputs(self):
        existing = [_play("A", "1", _ago(hours=1))]
        fresh = [_play("B", "2", _ago(days=9))]
        before = json.dumps([existing, fresh], sort_keys=True)
        merge_play_log(existing, fresh, NOW)
        self.assertEqual(json.dumps([existing, fresh], sort_keys=True), before)

    def test_a_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_play_log([], [], datetime(2026, 9, 10, 14, 0, 0))

    def test_now_in_another_timezone_gives_the_same_window(self):
        offset_now = NOW.astimezone(timezone(timedelta(hours=-7)))
        plays = [_play("A", "1", _ago(days=7)),
                 _play("B", "2", _ago(days=7, seconds=1))]
        self.assertEqual(
            merge_play_log([], plays, offset_now),
            merge_play_log([], plays, NOW),
        )


class TestAggregateWeeklyTop(unittest.TestCase):
    def test_counts_plays_per_track(self):
        entries = [
            _play("A", "1", _ago(hours=1)),
            _play("A", "1", _ago(hours=2)),
            _play("A", "1", _ago(hours=3)),
            _play("B", "2", _ago(hours=4)),
        ]
        self.assertEqual(aggregate_weekly_top(entries, NOW), [
            {"artist": "A", "title": "1", "plays": 3},
            {"artist": "B", "title": "2", "plays": 1},
        ])

    def test_most_played_first_regardless_of_input_order(self):
        entries = [
            _play("Low", "x", _ago(hours=1)),
            _play("High", "y", _ago(hours=2)),
            _play("High", "y", _ago(hours=3)),
            _play("Mid", "z", _ago(hours=4)),
            _play("Mid", "z", _ago(hours=5)),
            _play("High", "y", _ago(hours=6)),
        ]
        result = aggregate_weekly_top(entries, NOW)
        self.assertEqual([t["title"] for t in result], ["y", "z", "x"])
        self.assertEqual([t["plays"] for t in result], [3, 2, 1])

    def test_tie_goes_to_the_most_recently_played(self):
        entries = [
            _play("Older", "a", _ago(days=3)),
            _play("Older", "a", _ago(days=4)),
            _play("Newer", "b", _ago(hours=1)),
            _play("Newer", "b", _ago(days=5)),
        ]
        result = aggregate_weekly_top(entries, NOW)
        self.assertEqual([t["title"] for t in result], ["b", "a"])

    def test_recency_means_the_latest_play_not_the_first_seen(self):
        # "x" is listed first and has the older of the two plays seen first;
        # its LATEST play is still older than y's.
        entries = [
            _play("X", "x", _ago(days=6)),
            _play("X", "x", _ago(days=2)),
            _play("Y", "y", _ago(days=1)),
            _play("Y", "y", _ago(days=5)),
        ]
        result = aggregate_weekly_top(entries, NOW)
        self.assertEqual([t["title"] for t in result], ["y", "x"])

    def test_full_tie_falls_back_to_artist_then_title(self):
        moment = _ago(hours=1)
        entries = [
            _play("B", "a", moment),
            _play("A", "z", moment),
            _play("A", "b", moment),
        ]
        expected = [("A", "b"), ("A", "z"), ("B", "a")]
        for perm in itertools.permutations(entries):
            with self.subTest(order=[(p["artist"], p["title"]) for p in perm]):
                result = aggregate_weekly_top(list(perm), NOW)
                self.assertEqual(
                    [(t["artist"], t["title"]) for t in result], expected
                )

    def test_output_does_not_depend_on_input_order(self):
        entries = [
            _play("A", "1", _ago(hours=1)),
            _play("A", "1", _ago(hours=2)),
            _play("B", "2", _ago(hours=3)),
            _play("B", "2", _ago(hours=4)),
            _play("C", "3", _ago(hours=5)),
        ]
        expected = aggregate_weekly_top(entries, NOW)
        for perm in itertools.permutations(entries):
            self.assertEqual(aggregate_weekly_top(list(perm), NOW), expected)

    def test_default_limit_is_ten(self):
        entries = [_play(f"A{i}", f"T{i}", _ago(hours=i)) for i in range(25)]
        self.assertEqual(len(aggregate_weekly_top(entries, NOW)), 10)

    def test_limit_parameter_is_honoured(self):
        entries = [_play(f"A{i}", f"T{i}", _ago(hours=i)) for i in range(25)]
        self.assertEqual(len(aggregate_weekly_top(entries, NOW, limit=3)), 3)
        self.assertEqual(len(aggregate_weekly_top(entries, NOW, limit=25)), 25)
        self.assertEqual(len(aggregate_weekly_top(entries, NOW, limit=99)), 25)

    def test_the_limit_cuts_the_weakest_not_the_first(self):
        entries = [_play("Rare", "r", _ago(hours=1))]
        entries += [_play("Loud", "l", _ago(hours=h)) for h in range(2, 6)]
        entries += [_play("Mid", "m", _ago(hours=h)) for h in range(6, 8)]
        result = aggregate_weekly_top(entries, NOW, limit=2)
        self.assertEqual([t["title"] for t in result], ["l", "m"])

    def test_returns_fewer_than_limit_when_that_is_all_there_is(self):
        entries = [_play("A", "1", _ago(hours=1))]
        self.assertEqual(len(aggregate_weekly_top(entries, NOW)), 1)

    def test_limit_below_one_raises(self):
        entries = [_play("A", "1", _ago(hours=1))]
        for bad in (0, -1):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                aggregate_weekly_top(entries, NOW, limit=bad)

    def test_play_exactly_seven_days_old_counts(self):
        entries = [_play("A", "1", _ago(days=7))]
        self.assertEqual(
            aggregate_weekly_top(entries, NOW),
            [{"artist": "A", "title": "1", "plays": 1}],
        )

    def test_play_seven_days_and_one_second_old_does_not(self):
        entries = [_play("A", "1", _ago(days=7, seconds=1))]
        self.assertEqual(aggregate_weekly_top(entries, NOW), [])

    def test_stale_plays_neither_count_nor_break_ties(self):
        entries = [
            _play("A", "1", _ago(days=8)),
            _play("A", "1", _ago(days=9)),
            _play("A", "1", _ago(days=10)),
            _play("B", "2", _ago(days=2)),
        ]
        self.assertEqual(
            aggregate_weekly_top(entries, NOW),
            [{"artist": "B", "title": "2", "plays": 1}],
        )

    def test_an_old_play_cannot_win_a_recency_tie(self):
        # Both tracks have one in-window play; only B's play is more recent.
        # A's extra play is out of the window and must not matter.
        entries = [
            _play("A", "1", _ago(days=3)),
            _play("A", "1", _ago(days=30)),
            _play("B", "2", _ago(days=1)),
        ]
        result = aggregate_weekly_top(entries, NOW)
        self.assertEqual([t["title"] for t in result], ["2", "1"])
        self.assertEqual([t["plays"] for t in result], [1, 1])

    def test_nothing_in_the_window_gives_empty_for_the_caller_to_handle(self):
        self.assertEqual(aggregate_weekly_top([], NOW), [])
        self.assertEqual(
            aggregate_weekly_top([_play("A", "1", _ago(days=40))], NOW), []
        )

    def test_same_title_by_two_artists_is_two_tracks(self):
        entries = [_play("A", "Intro", _ago(hours=1)),
                   _play("B", "Intro", _ago(hours=2))]
        self.assertEqual(len(aggregate_weekly_top(entries, NOW)), 2)

    def test_output_carries_no_timestamps_or_ids(self):
        # Spec section 5: the committed file stays minimal.
        entries = [_play("A", "1", _ago(hours=1)), _play("A", "1", _ago(hours=2))]
        for track in aggregate_weekly_top(entries, NOW):
            self.assertEqual(set(track), {"artist", "title", "plays"})

    def test_plays_are_positive_ints_and_never_exceed_the_input(self):
        entries = [_play(f"A{i % 4}", f"T{i % 3}", _ago(minutes=i * 7))
                   for i in range(60)]
        result = aggregate_weekly_top(entries, NOW, limit=100)
        self.assertLessEqual(sum(t["plays"] for t in result), len(entries))
        self.assertEqual(sum(t["plays"] for t in result), len(entries))
        for track in result:
            self.assertIs(type(track["plays"]), int)
            self.assertGreaterEqual(track["plays"], 1)

    def test_counts_never_increase_down_the_chart(self):
        entries = [_play(f"A{i % 5}", f"T{i % 5}", _ago(minutes=i * 13))
                   for i in range(40)]
        counts = [t["plays"] for t in aggregate_weekly_top(entries, NOW)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_unusable_entries_are_skipped(self):
        entries = [None, "x", {}, {"artist": "A"},
                   {"artist": "A", "title": "1", "played_at": "nope"},
                   _play("Real", "Song", _ago(hours=1))]
        self.assertEqual(
            aggregate_weekly_top(entries, NOW),
            [{"artist": "Real", "title": "Song", "plays": 1}],
        )

    def test_accepts_any_iterable(self):
        entries = (_play("A", "1", _ago(hours=h)) for h in (1, 2))
        self.assertEqual(aggregate_weekly_top(entries, NOW)[0]["plays"], 2)

    def test_a_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_weekly_top([], datetime(2026, 9, 10, 14, 0, 0))


class TestPlayLogFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / ".cache" / "spotify-plays.json"

    def _write_raw(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            self.path.write_bytes(data)
        else:
            self.path.write_text(data, encoding="utf-8")

    def test_missing_file_starts_fresh_without_a_warning(self):
        self.assertEqual(load_play_log(self.path, NOW), ([], NOW, None))

    def test_round_trip(self):
        plays = [_play("A", "1", _ago(hours=2)), _play("B", "2", _ago(hours=1))]
        started = _ago(days=3)
        save_play_log(self.path, plays, started)
        self.assertEqual(load_play_log(self.path, NOW), (plays, started, None))

    def test_save_creates_the_missing_directory(self):
        self.assertFalse(self.path.parent.exists())
        save_play_log(self.path, [], NOW)
        self.assertTrue(self.path.is_file())

    def test_save_leaves_no_temp_files_behind(self):
        save_play_log(self.path, [_play("A", "1", _ago(hours=1))], NOW)
        save_play_log(self.path, [_play("A", "2", _ago(hours=1))], NOW)
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])

    def test_save_overwrites_atomically(self):
        save_play_log(self.path, [_play("A", "1", _ago(hours=1))], NOW)
        with self.assertRaises(TypeError):
            save_play_log(self.path, [object()], NOW)   # not serialisable
        # The failed write must neither truncate the file nor strand a temp.
        self.assertEqual(load_play_log(self.path, NOW)[0][0]["title"], "1")
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])

    def test_corrupt_json_starts_fresh_with_a_warning(self):
        for raw in ["{not json", "", "   ", "[1, 2", '{"plays": [}', "\x00\x01"]:
            with self.subTest(raw=raw):
                self._write_raw(raw)
                plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(plays, [])
                self.assertEqual(since, NOW)
                self.assertIsInstance(warning, str)
                self.assertTrue(warning)

    def test_binary_garbage_starts_fresh_with_a_warning(self):
        self._write_raw(b"\xff\xfe\x00\x80 not utf-8 \xc3\x28")
        plays, since, warning = load_play_log(self.path, NOW)
        self.assertEqual(plays, [])
        self.assertEqual(since, NOW)
        self.assertTrue(warning)

    def test_absurdly_deep_nesting_starts_fresh_with_a_warning(self):
        self._write_raw("[" * 200000)
        plays, since, warning = load_play_log(self.path, NOW)
        self.assertEqual(plays, [])
        self.assertEqual(since, NOW)
        self.assertTrue(warning)

    def test_wrong_shape_starts_fresh_with_a_warning(self):
        for raw in ["[]", "42", '"plays"', "null", "{}", '{"plays": null}',
                    '{"plays": {"a": 1}}', '{"plays": "x"}']:
            with self.subTest(raw=raw):
                self._write_raw(raw)
                plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(plays, [])
                self.assertEqual(since, NOW)
                self.assertTrue(warning)

    def test_a_directory_where_the_file_should_be_starts_fresh(self):
        self.path.mkdir(parents=True)
        plays, since, warning = load_play_log(self.path, NOW)
        self.assertEqual(plays, [])
        self.assertEqual(since, NOW)
        self.assertTrue(warning)

    def test_bad_entries_are_dropped_but_good_ones_survive(self):
        good = _play("A", "1", _ago(hours=1))
        self._write_raw(json.dumps(
            {"plays": [good, None, "x", {"artist": "A"}, {"played_at": 5}]}
        ))
        # No `since` in the file: treated as starting now, without a warning.
        self.assertEqual(load_play_log(self.path, NOW), ([good], NOW, None))

    def test_a_corrupt_log_still_publishes_from_what_the_fetch_brings(self):
        # The whole recovery path: corrupt cache -> fresh start -> merge the
        # 50 plays just fetched -> a chart that is smaller, but not empty.
        self._write_raw("{corrupt")
        existing, _since, _warning = load_play_log(self.path, NOW)
        fresh = parse_recently_played(_payload(
            _item("A", "1", _stamp(_ago(hours=1))),
            _item("A", "1", _stamp(_ago(hours=2))),
        ))
        log = merge_play_log(existing, fresh, NOW)
        self.assertEqual(
            aggregate_weekly_top(log, NOW),
            [{"artist": "A", "title": "1", "plays": 2}],
        )

    def test_file_holds_only_what_the_log_needs(self):
        save_play_log(self.path, [_play("A", "1", _ago(hours=1))], NOW)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"since", "plays"})


class TestPlayLogSince(unittest.TestCase):
    """The log remembers when it started, so a thin one can be told apart."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / ".cache" / "spotify-plays.json"

    def _write_raw(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            data if isinstance(data, str) else json.dumps(data),
            encoding="utf-8",
        )

    def _on_disk(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    # --- how it is written ---------------------------------------------------

    def test_since_is_written_as_an_iso_8601_zulu_timestamp(self):
        save_play_log(self.path, [], datetime(2026, 9, 3, 9, 30, 15, tzinfo=UTC))
        self.assertEqual(self._on_disk()["since"], "2026-09-03T09:30:15.000Z")

    def test_since_in_another_zone_is_written_in_utc(self):
        plus_two = timezone(timedelta(hours=2))
        save_play_log(self.path, [], datetime(2026, 9, 3, 11, 30, tzinfo=plus_two))
        self.assertEqual(self._on_disk()["since"], "2026-09-03T09:30:00.000Z")

    def test_a_naive_since_is_refused_and_leaves_the_file_alone(self):
        save_play_log(self.path, [], NOW)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_play_log(self.path, [], datetime(2026, 9, 3, 9, 30))
        self.assertEqual(self.path.read_bytes(), before)

    def test_since_cannot_be_left_out_of_a_save(self):
        with self.assertRaises(TypeError):
            save_play_log(self.path, [])

    def test_an_empty_log_still_records_when_it_started(self):
        save_play_log(self.path, [], _ago(days=2))
        self.assertEqual(
            load_play_log(self.path, NOW), ([], _ago(days=2), None)
        )

    # --- how it is read ------------------------------------------------------

    def test_a_stored_since_comes_back_as_an_aware_utc_datetime(self):
        self._write_raw({"since": "2026-09-08T10:00:00.000Z", "plays": []})
        _plays, since, warning = load_play_log(self.path, NOW)
        self.assertIsNone(warning)
        self.assertEqual(since, datetime(2026, 9, 8, 10, 0, tzinfo=UTC))
        self.assertEqual(since.utcoffset(), timedelta(0))

    def test_equivalent_spellings_of_since_read_as_one_instant(self):
        for spelling in ("2026-09-08T10:00:00Z", "2026-09-08T10:00:00.000Z",
                         "2026-09-08T10:00:00+00:00",
                         "2026-09-08T12:00:00+02:00", "  2026-09-08T10:00:00Z "):
            with self.subTest(spelling=spelling):
                self._write_raw({"since": spelling, "plays": []})
                _plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(since, datetime(2026, 9, 8, 10, 0, tzinfo=UTC))
                self.assertIsNone(warning)

    def test_a_log_without_since_is_treated_as_starting_now(self):
        # Every log written before the warm-up existed looks like this.
        good = _play("A", "1", _ago(hours=1))
        for raw in ({"plays": [good]}, {"plays": [good], "since": None}):
            with self.subTest(raw=raw):
                self._write_raw(raw)
                self.assertEqual(
                    load_play_log(self.path, NOW), ([good], NOW, None)
                )

    def test_an_unusable_since_is_treated_as_starting_now_with_a_warning(self):
        good = _play("A", "1", _ago(hours=1))
        for bad in ("", "   ", "yesterday", "2026-09-08", "2026-09-08T10:00:00",
                    7, 1757512800, True, [], {}, ["2026-09-08T10:00:00Z"]):
            with self.subTest(since=bad):
                self._write_raw({"since": bad, "plays": [good]})
                plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(plays, [good])      # the plays are still good
                self.assertEqual(since, NOW)
                self.assertTrue(warning)

    def test_a_since_in_the_future_is_treated_as_starting_now(self):
        # Otherwise a bad value would hold the old chart for far more than a
        # week, and nothing would ever say why.
        good = _play("A", "1", _ago(hours=1))
        for ahead in (timedelta(seconds=1), timedelta(days=3),
                      timedelta(days=3650)):
            with self.subTest(ahead=ahead):
                self._write_raw({"since": _stamp(NOW + ahead), "plays": [good]})
                plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(plays, [good])
                self.assertEqual(since, NOW)
                self.assertTrue(warning)

    def test_a_since_of_exactly_now_is_not_in_the_future(self):
        self._write_raw({"since": _stamp(NOW), "plays": []})
        self.assertEqual(load_play_log(self.path, NOW), ([], NOW, None))

    def test_a_very_old_since_is_kept_as_it_is(self):
        # A mature log is the normal case for six days out of seven.
        old = _ago(days=400)
        self._write_raw({"since": _stamp(old), "plays": []})
        self.assertEqual(load_play_log(self.path, NOW), ([], old, None))

    def test_a_corrupt_log_resets_since_to_now_even_if_it_stored_one(self):
        # The cache holds a record of how long ago it started; once the file
        # is unreadable that record cannot be trusted, so it starts over.
        old = _stamp(_ago(days=5))
        for raw in ("{not json", "", f'{{"since": "{old}", "plays": [}}',
                    json.dumps({"since": old}),
                    json.dumps({"since": old, "plays": None}),
                    json.dumps({"since": old, "plays": "x"}),
                    json.dumps({"since": old, "plays": {"a": 1}}),
                    json.dumps([{"since": old}])):
            with self.subTest(raw=raw):
                self._write_raw(raw)
                plays, since, warning = load_play_log(self.path, NOW)
                self.assertEqual(plays, [])
                self.assertEqual(since, NOW)
                self.assertTrue(warning)

    def test_a_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            load_play_log(self.path, datetime(2026, 9, 10, 14, 0, 0))

    # --- surviving a poll ----------------------------------------------------

    def test_the_first_poll_starts_the_log_at_that_poll(self):
        self.assertFalse(self.path.exists())
        fresh = [_play("A", "1", _ago(hours=1))]
        plays, since, previously, warning = update_play_log(
            self.path, fresh, NOW
        )
        self.assertEqual(plays, fresh)
        self.assertEqual(since, NOW)
        self.assertEqual(previously, 0)
        self.assertIsNone(warning)
        self.assertEqual(self._on_disk()["since"], _stamp(NOW))

    def test_a_first_poll_with_no_plays_still_starts_the_log(self):
        update_play_log(self.path, [], NOW)
        self.assertEqual(load_play_log(self.path, NOW), ([], NOW, None))

    def test_since_survives_every_later_poll_unchanged(self):
        started = NOW
        update_play_log(self.path, [_play("A", "1", started)], started)
        recorded = self._on_disk()["since"]
        for step in range(1, 43):                 # a poll every 4h for 7 days
            moment = started + timedelta(hours=4 * step)
            update_play_log(
                self.path, [_play("A", str(step), moment)], moment
            )
            with self.subTest(step=step):
                self.assertEqual(self._on_disk()["since"], recorded)

    def test_since_survives_a_poll_that_brings_nothing(self):
        update_play_log(self.path, [_play("A", "1", NOW)], NOW)
        recorded = self._on_disk()["since"]
        later = NOW + timedelta(hours=4)
        update_play_log(self.path, [], later)
        self.assertEqual(self._on_disk()["since"], recorded)

    def test_since_survives_the_plays_aging_out_of_the_window(self):
        # Long after the 7-day window has dropped every play, the log is empty
        # but it still began when it began.
        update_play_log(self.path, [_play("A", "1", NOW)], NOW)
        recorded = self._on_disk()["since"]
        much_later = NOW + timedelta(days=30)
        plays, since, _previously, _warning = update_play_log(
            self.path, [], much_later
        )
        self.assertEqual(plays, [])
        self.assertEqual(since, NOW)
        self.assertEqual(self._on_disk()["since"], recorded)

    def test_a_poll_reports_what_the_log_held_before_it(self):
        update_play_log(self.path, [_play("A", "1", _ago(hours=5))], NOW)
        plays, _since, previously, _warning = update_play_log(
            self.path,
            [_play("A", "1", _ago(hours=5)), _play("B", "2", _ago(hours=1))],
            NOW,
        )
        self.assertEqual(previously, 1)
        self.assertEqual(len(plays), 2)

    def test_a_corrupt_log_restarts_at_the_poll_that_found_it(self):
        started = _ago(days=5)
        update_play_log(self.path, [_play("A", "1", started)], started)
        self.path.write_text("{corrupt", encoding="utf-8")
        fresh = [_play("B", "2", _ago(hours=1))]
        plays, since, _previously, warning = update_play_log(
            self.path, fresh, NOW
        )
        self.assertEqual(plays, fresh)
        self.assertEqual(since, NOW)
        self.assertTrue(warning)
        self.assertEqual(self._on_disk()["since"], _stamp(NOW))

    def test_an_evicted_cache_restarts_at_the_poll_that_found_it_gone(self):
        started = _ago(days=5)
        update_play_log(self.path, [_play("A", "1", started)], started)
        self.path.unlink()
        _plays, since, previously, warning = update_play_log(self.path, [], NOW)
        self.assertEqual(since, NOW)
        self.assertEqual(previously, 0)
        self.assertIsNone(warning)

    def test_a_legacy_log_without_since_is_stamped_by_the_next_poll(self):
        good = _play("A", "1", _ago(hours=1))
        self._write_raw({"plays": [good]})
        update_play_log(self.path, [], NOW)
        self.assertEqual(self._on_disk()["since"], _stamp(NOW))
        # ...and from then on it is preserved like any other.
        update_play_log(self.path, [], NOW + timedelta(days=2))
        self.assertEqual(self._on_disk()["since"], _stamp(NOW))

    def test_a_naive_now_is_rejected_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            update_play_log(self.path, [], datetime(2026, 9, 10, 14, 0, 0))
        self.assertFalse(self.path.exists())


class TestPlanPublish(unittest.TestCase):
    CHART = [{"artist": "A", "title": "1", "plays": 3}]
    OTHER = [{"artist": "B", "title": "2", "plays": 1}]

    def _plan(self, tracks, existing, keep_alive):
        """plan_publish for a log well past its warm-up."""
        return plan_publish(
            tracks, existing, keep_alive, since=MATURE_SINCE, now=NOW
        )

    def test_changed_tracks_are_written(self):
        to_write, message = self._plan(self.CHART, self.OTHER, False)
        self.assertEqual(to_write, self.CHART)
        self.assertIsInstance(message, str)

    def test_first_ever_chart_is_written(self):
        self.assertEqual(self._plan(self.CHART, None, False)[0], self.CHART)

    def test_unchanged_tracks_write_nothing(self):
        self.assertIsNone(self._plan(self.CHART, list(self.CHART), False)[0])

    def test_unchanged_tracks_with_keep_alive_are_rewritten(self):
        to_write, _message = self._plan(self.CHART, list(self.CHART), True)
        self.assertEqual(to_write, self.CHART)

    def test_a_changed_play_count_is_a_change(self):
        bumped = [{"artist": "A", "title": "1", "plays": 4}]
        self.assertEqual(self._plan(bumped, self.CHART, False)[0], bumped)

    def test_the_old_top_tracks_format_is_replaced(self):
        # Committed files from before the switch have no `plays`.
        old = [{"artist": "A", "title": "1"}]
        self.assertEqual(self._plan(self.CHART, old, False)[0], self.CHART)

    def test_no_tracks_never_writes_zero_tracks(self):
        for existing in (None, [], self.CHART):
            for keep_alive in (False, True):
                with self.subTest(existing=existing, keep_alive=keep_alive):
                    to_write, _message = self._plan([], existing, keep_alive)
                    self.assertNotEqual(to_write, [])

    def test_no_tracks_and_no_committed_chart_writes_nothing_even_for_keep_alive(self):
        self.assertIsNone(self._plan([], None, True)[0])
        self.assertIsNone(self._plan([], [], True)[0])

    def test_no_tracks_leaves_the_committed_chart_alone(self):
        self.assertIsNone(self._plan([], self.CHART, False)[0])

    def test_no_tracks_with_keep_alive_restamps_the_committed_chart(self):
        # A long quiet spell must still be able to reset the 60-day clock.
        self.assertEqual(self._plan([], self.CHART, True)[0], self.CHART)

    def test_nothing_it_returns_is_ever_an_empty_list(self):
        chart_options = ([], self.CHART)
        existing_options = (None, [], self.CHART, self.OTHER)
        for tracks, existing, keep_alive in itertools.product(
            chart_options, existing_options, (False, True)
        ):
            with self.subTest(tracks=tracks, existing=existing, ka=keep_alive):
                to_write, _message = self._plan(tracks, existing, keep_alive)
                self.assertTrue(to_write is None or len(to_write) > 0)


class TestWarmUp(unittest.TestCase):
    """A play log under 7 days old cannot show a full week.

    Spotify returns the last 50 plays and nothing older, so a log that has
    only just started (first run, or the cache was evicted) would replace a
    good chart with a thin one. For its first 7 days the committed chart stays.
    """

    COMMITTED = [{"artist": f"Old{i}", "title": f"o{i}", "plays": 10 - i}
                 for i in range(10)]
    THIN = [{"artist": "New", "title": "n", "plays": 1}]

    def _plan(self, tracks, existing, keep_alive, age):
        """plan_publish for a log that started `age` ago."""
        return plan_publish(
            tracks, existing, keep_alive, since=NOW - age, now=NOW
        )

    # --- the boundary --------------------------------------------------------

    def test_one_second_short_of_seven_days_keeps_the_committed_chart(self):
        to_write, message = self._plan(
            self.THIN, self.COMMITTED, False, SEVEN_DAYS - timedelta(seconds=1)
        )
        self.assertIsNone(to_write)
        self.assertTrue(message.startswith("Warming up:"))

    def test_one_microsecond_short_of_seven_days_still_keeps_it(self):
        to_write, _message = self._plan(
            self.THIN, self.COMMITTED, False,
            SEVEN_DAYS - timedelta(microseconds=1),
        )
        self.assertIsNone(to_write)

    def test_exactly_seven_days_publishes(self):
        to_write, message = self._plan(
            self.THIN, self.COMMITTED, False, SEVEN_DAYS
        )
        self.assertEqual(to_write, self.THIN)
        self.assertNotIn("Warming up", message)

    def test_one_second_past_seven_days_publishes(self):
        to_write, _message = self._plan(
            self.THIN, self.COMMITTED, False, SEVEN_DAYS + timedelta(seconds=1)
        )
        self.assertEqual(to_write, self.THIN)

    def test_a_log_that_started_just_now_is_warming_up(self):
        to_write, _message = self._plan(
            self.THIN, self.COMMITTED, False, timedelta(0)
        )
        self.assertIsNone(to_write)

    def test_the_switch_happens_exactly_once_across_the_whole_week(self):
        # Hour by hour: kept for every hour before 168, published from 168 on,
        # and never back again.
        decisions = []
        for hours in range(0, 24 * 10):
            to_write, _message = self._plan(
                self.THIN, self.COMMITTED, False, timedelta(hours=hours)
            )
            decisions.append(to_write is not None)
        self.assertEqual(decisions, [False] * 168 + [True] * (24 * 10 - 168))

    def test_a_since_in_the_future_is_still_warming_and_never_negative(self):
        # load_play_log never lets this through, but the planner must not
        # produce nonsense like "-1d" if it is ever handed one.
        to_write, message = plan_publish(
            self.THIN, self.COMMITTED, False,
            since=NOW + timedelta(days=2), now=NOW,
        )
        self.assertIsNone(to_write)
        self.assertEqual(
            message,
            "Warming up: play log covers 0d 0h of 7d; "
            "keeping the committed chart.",
        )

    def test_the_same_instant_in_another_zone_decides_the_same_way(self):
        elsewhere = timezone(timedelta(hours=-7))
        for age, expect_kept in ((SEVEN_DAYS - timedelta(seconds=1), True),
                                 (SEVEN_DAYS, False)):
            with self.subTest(age=age):
                to_write, _message = plan_publish(
                    self.THIN, self.COMMITTED, False,
                    since=(NOW - age).astimezone(elsewhere),
                    now=NOW.astimezone(timezone(timedelta(hours=9))),
                )
                self.assertEqual(to_write is None, expect_kept)

    # --- what stays ----------------------------------------------------------

    def test_a_richer_new_chart_still_waits_for_the_week_to_finish(self):
        # Warm-up is about the log's age, not whether the new chart looks
        # better: even a full-looking chart rests on a log that is not.
        richer = [{"artist": f"N{i}", "title": f"n{i}", "plays": 5}
                  for i in range(10)]
        to_write, _message = self._plan(
            richer, self.COMMITTED, False, timedelta(days=1)
        )
        self.assertIsNone(to_write)

    def test_an_empty_window_while_warming_keeps_the_chart_too(self):
        to_write, message = self._plan(
            [], self.COMMITTED, False, timedelta(days=1)
        )
        self.assertIsNone(to_write)
        self.assertTrue(message.startswith("Warming up:"))

    def test_identical_tracks_while_warming_write_nothing(self):
        to_write, _message = self._plan(
            list(self.COMMITTED), self.COMMITTED, False, timedelta(days=1)
        )
        self.assertIsNone(to_write)

    def test_the_old_chart_format_without_plays_counts_as_a_chart(self):
        old = [{"artist": "A", "title": "1"}]
        to_write, _message = self._plan(
            self.THIN, old, False, timedelta(days=1)
        )
        self.assertIsNone(to_write)

    def test_one_usable_track_among_junk_is_enough_to_keep_the_chart(self):
        junk = [None, "x", 3, [], {}, {"artist": "A"}, {"title": "t"},
                {"artist": "  ", "title": "t"}, {"artist": "A", "title": ""},
                {"artist": 7, "title": "t"}, {"artist": "A", "title": None}]
        to_write, _message = self._plan(
            self.THIN, [*junk, {"artist": "Real", "title": "Song"}], False,
            timedelta(days=1),
        )
        self.assertIsNone(to_write)

    # --- what does not count as a committed chart ----------------------------

    def test_no_committed_chart_publishes_whatever_the_log_has(self):
        for existing in (None, []):
            with self.subTest(existing=existing):
                to_write, message = self._plan(
                    self.THIN, existing, False, timedelta(days=1)
                )
                self.assertEqual(to_write, self.THIN)
                self.assertNotIn("Warming up", message)

    def test_a_malformed_committed_chart_counts_as_none(self):
        malformed = (
            [None], ["x"], [3], [[]], [{}],
            [{"artist": "A"}], [{"title": "t"}],
            [{"artist": "", "title": "t"}], [{"artist": "A", "title": "  "}],
            [{"artist": 7, "title": "t"}], [{"artist": "A", "title": 7}],
            [{"artist": None, "title": None}],
            [None, "x", {}, {"artist": "A"}],
            {"artist": "A", "title": "1"}, "A - 1", 3,   # not even a list
        )
        for existing in malformed:
            with self.subTest(existing=existing):
                to_write, _message = self._plan(
                    self.THIN, existing, False, timedelta(days=1)
                )
                self.assertEqual(to_write, self.THIN)

    def test_no_chart_and_no_plays_still_writes_nothing(self):
        # The "never zero tracks" rule is untouched by the warm-up.
        for existing in (None, []):
            for keep_alive in (False, True):
                with self.subTest(existing=existing, keep_alive=keep_alive):
                    to_write, _message = self._plan(
                        [], existing, keep_alive, timedelta(days=1)
                    )
                    self.assertIsNone(to_write)

    # --- keep-alive ----------------------------------------------------------

    def test_keep_alive_while_warming_restamps_the_committed_chart(self):
        to_write, message = self._plan(
            self.THIN, self.COMMITTED, True, timedelta(days=1)
        )
        self.assertEqual(to_write, self.COMMITTED)
        self.assertNotEqual(to_write, self.THIN)
        self.assertTrue(message.startswith("Warming up:"))
        self.assertIn("keep-alive", message)

    def test_keep_alive_while_warming_never_changes_the_tracks(self):
        for tracks in (self.THIN, [], list(self.COMMITTED)):
            with self.subTest(tracks=tracks):
                to_write, _message = self._plan(
                    tracks, self.COMMITTED, True, timedelta(days=1)
                )
                self.assertEqual(to_write, self.COMMITTED)

    def test_keep_alive_without_a_usable_chart_publishes_normally(self):
        to_write, message = self._plan(
            self.THIN, None, True, timedelta(days=1)
        )
        self.assertEqual(to_write, self.THIN)
        self.assertNotIn("Warming up", message)

    def test_keep_alive_after_the_week_is_the_ordinary_keep_alive(self):
        to_write, message = self._plan(
            list(self.COMMITTED), self.COMMITTED, True, SEVEN_DAYS
        )
        self.assertEqual(to_write, self.COMMITTED)
        self.assertNotIn("Warming up", message)

    def test_a_warming_run_is_never_asked_to_write_an_empty_chart(self):
        for existing in (None, [], [None], self.COMMITTED):
            for tracks in ([], self.THIN):
                for keep_alive in (False, True):
                    for age in (timedelta(0), timedelta(days=3), SEVEN_DAYS):
                        with self.subTest(existing=existing, tracks=tracks,
                                          keep_alive=keep_alive, age=age):
                            to_write, _message = self._plan(
                                tracks, existing, keep_alive, age
                            )
                            self.assertTrue(
                                to_write is None or len(to_write) > 0
                            )

    # --- the notice ----------------------------------------------------------

    def test_the_notice_says_how_far_through_the_week_the_log_is(self):
        to_write, message = self._plan(
            self.THIN, self.COMMITTED, False,
            timedelta(days=2, hours=4, minutes=30),
        )
        self.assertIsNone(to_write)
        self.assertEqual(
            message,
            "Warming up: play log covers 2d 4h of 7d; "
            "keeping the committed chart.",
        )

    def test_the_notice_rounds_down_so_it_never_overstates(self):
        _to_write, message = self._plan(
            self.THIN, self.COMMITTED, False, SEVEN_DAYS - timedelta(seconds=1)
        )
        self.assertIn("covers 6d 23h of 7d", message)

    def test_the_notice_for_a_log_started_this_hour(self):
        _to_write, message = self._plan(
            self.THIN, self.COMMITTED, False, timedelta(minutes=59)
        )
        self.assertIn("covers 0d 0h of 7d", message)

    def test_the_keep_alive_notice_is_a_sentence_of_its_own(self):
        _to_write, message = self._plan(
            self.THIN, self.COMMITTED, True, timedelta(days=2, hours=4)
        )
        self.assertEqual(
            message,
            "Warming up: play log covers 2d 4h of 7d; keeping the committed "
            "chart (timestamp refreshed as keep-alive).",
        )

    # --- misuse --------------------------------------------------------------

    def test_since_and_now_are_required(self):
        with self.assertRaises(TypeError):
            plan_publish(self.THIN, self.COMMITTED, False)
        with self.assertRaises(TypeError):
            plan_publish(self.THIN, self.COMMITTED, False, since=NOW)
        with self.assertRaises(TypeError):
            plan_publish(self.THIN, self.COMMITTED, False, now=NOW)

    def test_since_and_now_cannot_be_swapped_by_position(self):
        with self.assertRaises(TypeError):
            plan_publish(self.THIN, self.COMMITTED, False, NOW, NOW)

    def test_naive_datetimes_are_rejected(self):
        naive = datetime(2026, 9, 10, 14, 0, 0)
        with self.assertRaises(ValueError):
            plan_publish(self.THIN, None, False, since=naive, now=NOW)
        with self.assertRaises(ValueError):
            plan_publish(self.THIN, None, False, since=NOW, now=naive)

    def test_it_does_not_mutate_what_it_is_given(self):
        before = json.dumps([self.THIN, self.COMMITTED], sort_keys=True)
        for keep_alive in (False, True):
            self._plan(self.THIN, self.COMMITTED, keep_alive, timedelta(days=1))
            self._plan(self.THIN, self.COMMITTED, keep_alive, SEVEN_DAYS)
        self.assertEqual(
            json.dumps([self.THIN, self.COMMITTED], sort_keys=True), before
        )


class TestPublishChart(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "content" / "listening.json"

    def _seed(self, tracks, fetched_at="2020-01-01T00:00:00Z"):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"fetched_at": fetched_at, "tracks": tracks}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _publish(self, plays, now, keep_alive, path, since=MATURE_SINCE):
        return publish_chart(plays, now, keep_alive, path, since=since)

    LOG = [
        {"artist": "A", "title": "1", "played_at": "2026-09-09T10:00:00.000Z"},
        {"artist": "A", "title": "1", "played_at": "2026-09-09T11:00:00.000Z"},
        {"artist": "B", "title": "2", "played_at": "2026-09-09T12:00:00.000Z"},
    ]
    CHART = [
        {"artist": "A", "title": "1", "plays": 2},
        {"artist": "B", "title": "2", "plays": 1},
    ]

    def test_writes_the_documented_shape(self):
        message = self._publish(self.LOG, NOW, False, self.path)
        data = self._read()
        self.assertIsInstance(message, str)
        self.assertEqual(set(data), {"fetched_at", "tracks"})
        self.assertRegex(data["fetched_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(data["tracks"], self.CHART)

    def test_the_committed_file_carries_no_timestamps_ids_or_urls(self):
        self._publish(self.LOG, NOW, False, self.path)
        for track in self._read()["tracks"]:
            self.assertEqual(set(track), {"artist", "title", "plays"})
        self.assertNotIn("played_at", self.path.read_text(encoding="utf-8"))

    def test_an_empty_log_writes_nothing_at_all(self):
        self._publish([], NOW, False, self.path)
        self.assertFalse(self.path.exists())

    def test_an_empty_log_with_keep_alive_still_writes_nothing_new(self):
        self._publish([], NOW, True, self.path)
        self.assertFalse(self.path.exists())

    def test_a_log_of_only_stale_plays_leaves_the_committed_chart_untouched(self):
        self._seed(self.CHART)
        before = self.path.read_bytes()
        stale = [{"artist": "Z", "title": "z",
                  "played_at": "2026-08-01T00:00:00.000Z"}]
        self._publish(stale, NOW, False, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unchanged_tracks_leave_the_file_byte_identical(self):
        self._seed(self.CHART)
        before = self.path.read_bytes()
        self._publish(self.LOG, NOW, False, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unchanged_tracks_with_keep_alive_refresh_the_timestamp(self):
        self._seed(self.CHART)
        self._publish(self.LOG, NOW, True, self.path)
        data = self._read()
        self.assertEqual(data["tracks"], self.CHART)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_changed_tracks_replace_the_old_chart(self):
        self._seed([{"artist": "Old", "title": "o", "plays": 9}])
        self._publish(self.LOG, NOW, False, self.path)
        data = self._read()
        self.assertEqual(data["tracks"], self.CHART)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_a_thin_log_still_publishes_what_it_has(self):
        # Cache evicted: only the latest poll's plays exist. Publish those.
        thin = self.LOG[2:]
        self._publish(thin, NOW, False, self.path)
        self.assertEqual(
            self._read()["tracks"],
            [{"artist": "B", "title": "2", "plays": 1}],
        )

    def test_a_corrupt_committed_file_is_replaced_not_fatal(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{corrupt", encoding="utf-8")
        self._publish(self.LOG, NOW, False, self.path)
        self.assertEqual(self._read()["tracks"], self.CHART)

    def test_leaves_no_temp_files_behind(self):
        self._publish(self.LOG, NOW, False, self.path)
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])


class TestPublishChartWarmUp(unittest.TestCase):
    """The warm-up as the files see it: what is on disk after a publish."""

    COMMITTED = [{"artist": f"Old{i}", "title": f"o{i}", "plays": 10 - i}
                 for i in range(10)]
    LOG = [
        {"artist": "A", "title": "1", "played_at": "2026-09-09T10:00:00.000Z"},
        {"artist": "A", "title": "1", "played_at": "2026-09-09T11:00:00.000Z"},
        {"artist": "B", "title": "2", "played_at": "2026-09-09T12:00:00.000Z"},
    ]
    THIN = [
        {"artist": "A", "title": "1", "plays": 2},
        {"artist": "B", "title": "2", "plays": 1},
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "content" / "listening.json"

    def _seed(self, tracks=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"fetched_at": "2020-01-01T00:00:00Z",
                        "tracks": self.COMMITTED if tracks is None else tracks},
                       indent=2) + "\n",
            encoding="utf-8",
        )

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _publish(self, age, keep_alive=False, plays=None):
        return publish_chart(
            self.LOG if plays is None else plays, NOW, keep_alive, self.path,
            since=NOW - age,
        )

    def test_a_thin_log_does_not_replace_the_committed_chart(self):
        # The bug this exists for: a new or evicted log holds a few plays,
        # and publishing them would swap ten tracks for two.
        self._seed()
        before = self.path.read_bytes()
        message = self._publish(timedelta(hours=1))
        self.assertTrue(message.startswith("Warming up:"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_seven_days_less_a_second_still_leaves_the_file_byte_identical(self):
        self._seed()
        before = self.path.read_bytes()
        self._publish(SEVEN_DAYS - timedelta(seconds=1))
        self.assertEqual(self.path.read_bytes(), before)

    def test_exactly_seven_days_replaces_the_chart(self):
        self._seed()
        message = self._publish(SEVEN_DAYS)
        self.assertNotIn("Warming up", message)
        data = self._read()
        self.assertEqual(data["tracks"], self.THIN)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_keep_alive_restamps_without_touching_the_tracks(self):
        self._seed()
        message = self._publish(timedelta(days=2), keep_alive=True)
        self.assertTrue(message.startswith("Warming up:"))
        data = self._read()
        self.assertEqual(data["tracks"], self.COMMITTED)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(set(data), {"fetched_at", "tracks"})

    def test_keep_alive_with_a_quiet_log_while_warming_restamps_too(self):
        self._seed()
        self._publish(timedelta(days=2), keep_alive=True, plays=[])
        data = self._read()
        self.assertEqual(data["tracks"], self.COMMITTED)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_no_committed_file_publishes_during_the_warm_up(self):
        self.assertFalse(self.path.exists())
        message = self._publish(timedelta(hours=1))
        self.assertNotIn("Warming up", message)
        self.assertEqual(self._read()["tracks"], self.THIN)

    def test_a_malformed_committed_file_counts_as_none(self):
        self.path.parent.mkdir(parents=True)
        for raw in ("{corrupt", "", "[]", "null", "{}",
                    '{"tracks": "x"}', '{"tracks": null}', '{"tracks": []}',
                    '{"tracks": [null]}', '{"tracks": [{"artist": "A"}]}',
                    '{"tracks": [{"artist": "", "title": ""}]}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                self._publish(timedelta(hours=1))
                self.assertEqual(self._read()["tracks"], self.THIN)

    def test_a_malformed_committed_file_with_an_empty_log_stays_untouched(self):
        # Nothing to publish and nothing worth protecting: leave it alone
        # rather than invent a chart.
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{corrupt", encoding="utf-8")
        self._publish(timedelta(hours=1), plays=[])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{corrupt")

    def test_no_committed_file_and_an_empty_log_writes_nothing_at_all(self):
        for keep_alive in (False, True):
            with self.subTest(keep_alive=keep_alive):
                self._publish(timedelta(hours=1), keep_alive=keep_alive,
                              plays=[])
                self.assertFalse(self.path.exists())

    def test_a_warming_publish_leaves_no_temp_files_behind(self):
        self._seed()
        self._publish(timedelta(days=1))
        self._publish(timedelta(days=1), keep_alive=True)
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])

    def test_since_is_required(self):
        with self.assertRaises(TypeError):
            publish_chart(self.LOG, NOW, False, self.path)


class TestWarmUpAcrossARealWeek(unittest.TestCase):
    """Polls and publishes, week long, through the real files.

    Nothing is mocked: every step takes its own `now`.
    """

    START = NOW
    COMMITTED = [{"artist": f"Old{i}", "title": f"o{i}", "plays": 10 - i}
                 for i in range(10)]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.log_path = root / ".cache" / "spotify-plays.json"
        self.chart_path = root / "content" / "listening.json"
        self.chart_path.parent.mkdir(parents=True)
        self.chart_path.write_text(
            json.dumps({"fetched_at": "2020-01-01T00:00:00Z",
                        "tracks": self.COMMITTED}, indent=2) + "\n",
            encoding="utf-8",
        )
        self.committed_bytes = self.chart_path.read_bytes()

    def _at(self, **delta):
        return self.START + timedelta(**delta)

    def _poll_and_publish(self, now, plays, keep_alive=False):
        """One workflow run that publishes."""
        fresh = [_play(a, t, moment) for a, t, moment in plays]
        log, since, _previously, _warning = update_play_log(
            self.log_path, fresh, now
        )
        return publish_chart(log, now, keep_alive, self.chart_path, since=since)

    def _chart(self):
        return json.loads(self.chart_path.read_text(encoding="utf-8"))["tracks"]

    def test_the_old_chart_holds_all_week_then_the_new_one_takes_over(self):
        s = self._at
        runs = [
            (s(), [("A", "1", s(hours=-1)), ("A", "1", s(hours=-2)),
                   ("B", "2", s(hours=-3))]),
            (s(days=3), [("C", "3", s(days=3))]),
            (s(days=5), [("D", "4", s(days=5))]),
            (s(days=7) - timedelta(seconds=1), [("C", "3", s(days=6))]),
        ]
        for now, plays in runs:
            with self.subTest(now=now):
                message = self._poll_and_publish(now, plays)
                self.assertTrue(message.startswith("Warming up:"), message)
                self.assertEqual(self.chart_path.read_bytes(),
                                 self.committed_bytes)

        # Exactly seven days in. The plays from before the log started have
        # just aged out of the window; the week itself is what is left.
        message = self._poll_and_publish(
            s(days=7), [("C", "3", s(days=7))]
        )
        self.assertNotIn("Warming up", message)
        self.assertEqual(self._chart(), [
            {"artist": "C", "title": "3", "plays": 3},
            {"artist": "D", "title": "4", "plays": 1},
        ])

    def test_an_evicted_cache_restarts_the_week(self):
        s = self._at
        self._poll_and_publish(s(), [("A", "1", s(hours=-1))])
        # Day 5: the cache is gone. The next poll starts a new log.
        self.log_path.unlink()
        self._poll_and_publish(s(days=5), [("B", "2", s(days=5))])
        # Day 7 would have been the end of the first week. It is not now.
        self._poll_and_publish(s(days=7), [("B", "2", s(days=7))])
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)
        # Seven days after the restart, it is.
        self._poll_and_publish(
            s(days=12) - timedelta(seconds=1), [("B", "2", s(days=11))]
        )
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)
        self._poll_and_publish(s(days=12), [("B", "2", s(days=12))])
        self.assertNotEqual(self.chart_path.read_bytes(), self.committed_bytes)
        self.assertEqual(
            self._chart(), [{"artist": "B", "title": "2", "plays": 4}]
        )

    def test_a_corrupt_cache_restarts_the_week_the_same_way(self):
        s = self._at
        self._poll_and_publish(s(), [("A", "1", s(hours=-1))])
        self.log_path.write_text("{corrupt", encoding="utf-8")
        self._poll_and_publish(s(days=5), [("B", "2", s(days=5))])
        self._poll_and_publish(s(days=7), [("B", "2", s(days=7))])
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)

    def test_a_legacy_log_warms_up_from_the_next_poll(self):
        # Written by the old code: plays, no `since`.
        legacy = [_play("A", "1", self._at(days=-3))]
        self.log_path.parent.mkdir(parents=True)
        self.log_path.write_text(json.dumps({"plays": legacy}), encoding="utf-8")
        message = self._poll_and_publish(self._at(), [])
        self.assertTrue(message.startswith("Warming up:"))
        self.assertIn("covers 0d 0h of 7d", message)
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)

    def test_keep_alive_polls_through_the_week_never_change_the_tracks(self):
        s = self._at
        for days in (0, 2, 4, 6):
            self._poll_and_publish(
                s(days=days), [("Z", "z", s(days=days))], keep_alive=True
            )
            with self.subTest(days=days):
                self.assertEqual(self._chart(), self.COMMITTED)
        self.assertNotEqual(self.chart_path.read_bytes(), self.committed_bytes)

    def test_without_a_committed_chart_the_very_first_poll_publishes(self):
        self.chart_path.unlink()
        s = self._at
        message = self._poll_and_publish(s(), [("A", "1", s(hours=-1))])
        self.assertNotIn("Warming up", message)
        self.assertEqual(
            self._chart(), [{"artist": "A", "title": "1", "plays": 1}]
        )


class TestRunPoll(unittest.TestCase):
    """Everything main() does after the fetch, with a `now` of our choosing."""

    COMMITTED = [{"artist": f"Old{i}", "title": f"o{i}", "plays": 10 - i}
                 for i in range(10)]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.log_path = root / ".cache" / "spotify-plays.json"
        self.chart_path = root / "content" / "listening.json"
        self.chart_path.parent.mkdir(parents=True)
        self.chart_path.write_text(
            json.dumps({"fetched_at": "2020-01-01T00:00:00Z",
                        "tracks": self.COMMITTED}, indent=2) + "\n",
            encoding="utf-8",
        )
        self.committed_bytes = self.chart_path.read_bytes()

    def _run(self, now, fresh, publish=True, keep_alive=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fetch_listening.run_poll(
                fresh, now, self.log_path, publish, keep_alive,
                self.chart_path,
            )
        return code, out.getvalue(), err.getvalue()

    def _since_on_disk(self):
        data = json.loads(self.log_path.read_text(encoding="utf-8"))
        return data["since"]

    def test_the_first_publish_keeps_the_chart_says_so_and_exits_zero(self):
        fresh = [_play("A", "1", _ago(hours=1))]
        code, out, err = self._run(NOW, fresh)
        self.assertEqual(code, 0)
        self.assertIn(
            "Warming up: play log covers 0d 0h of 7d; "
            "keeping the committed chart.",
            out,
        )
        self.assertEqual(err, "")
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)

    def test_the_log_is_stamped_by_the_poll_that_created_it(self):
        self._run(NOW, [_play("A", "1", _ago(hours=1))])
        self.assertEqual(self._since_on_disk(), _stamp(NOW))

    def test_a_later_run_reads_how_old_the_log_is_from_that_stamp(self):
        self._run(NOW, [])
        code, out, _err = self._run(NOW + timedelta(days=2, hours=4), [])
        self.assertEqual(code, 0)
        self.assertIn("covers 2d 4h of 7d", out)
        self.assertEqual(self._since_on_disk(), _stamp(NOW))

    def test_the_week_ends_where_the_log_says_it_does(self):
        self._run(NOW, [_play("A", "1", _ago(hours=1))])
        late = NOW + SEVEN_DAYS - timedelta(seconds=1)
        _code, out, _err = self._run(late, [_play("B", "2", late)])
        self.assertIn("Warming up", out)
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)

        done = NOW + SEVEN_DAYS
        code, out, _err = self._run(done, [_play("B", "2", done)])
        self.assertEqual(code, 0)
        self.assertNotIn("Warming up", out)
        self.assertEqual(
            json.loads(self.chart_path.read_text(encoding="utf-8"))["tracks"],
            [{"artist": "B", "title": "2", "plays": 2}],
        )

    def test_keep_alive_during_warm_up_restamps_and_still_exits_zero(self):
        code, out, _err = self._run(NOW, [], keep_alive=True)
        self.assertEqual(code, 0)
        self.assertIn("Warming up", out)
        data = json.loads(self.chart_path.read_text(encoding="utf-8"))
        self.assertEqual(data["tracks"], self.COMMITTED)
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_a_poll_only_run_never_touches_the_chart_or_warms_up_aloud(self):
        for moment in (NOW, NOW + timedelta(days=30)):
            with self.subTest(now=moment):
                code, out, _err = self._run(
                    moment, [_play("A", "1", moment)], publish=False
                )
                self.assertEqual(code, 0)
                self.assertNotIn("Warming up", out)
                self.assertIn("Poll only", out)
                self.assertEqual(self.chart_path.read_bytes(),
                                 self.committed_bytes)

    def test_a_poll_only_run_still_stamps_the_log(self):
        self._run(NOW, [], publish=False)
        self.assertEqual(self._since_on_disk(), _stamp(NOW))

    def test_a_corrupt_log_warns_on_stderr_and_restarts_the_warm_up(self):
        self._run(NOW, [])
        self.log_path.write_text("{corrupt", encoding="utf-8")
        later = NOW + timedelta(days=6)
        code, out, err = self._run(later, [_play("A", "1", later)])
        self.assertEqual(code, 0)
        self.assertIn("Warning:", err)
        self.assertIn("covers 0d 0h of 7d", out)
        self.assertEqual(self._since_on_disk(), _stamp(later))
        self.assertEqual(self.chart_path.read_bytes(), self.committed_bytes)

    def test_the_summary_line_reports_the_log_size_before_and_after(self):
        self._run(NOW, [_play("A", "1", _ago(hours=5))])
        _code, out, _err = self._run(NOW, [
            _play("A", "1", _ago(hours=5)), _play("B", "2", _ago(hours=1)),
        ])
        self.assertIn("Fetched 2 recent plays; the log now holds 2 from the "
                      "last 7 days (was 1).", out)


class TestFullPipeline(unittest.TestCase):
    """Raw Spotify payload -> merged log -> chart, with nothing mocked."""

    def test_two_overlapping_polls_produce_one_consistent_chart(self):
        first = parse_recently_played(_payload(
            _item("Trivium", "The Terror", _stamp(_ago(hours=9))),
            _item("Trivium", "Death Throes", _stamp(_ago(hours=10))),
            _item("Trivium", "The Terror", _stamp(_ago(hours=11))),
        ))
        # Four hours later the API repeats two of those plays and adds one.
        second = parse_recently_played(_payload(
            _item("Trivium", "Death Throes", _stamp(_ago(hours=5))),
            _item("Trivium", "The Terror", _stamp(_ago(hours=9))),
            _item("Trivium", "Death Throes", _stamp(_ago(hours=10))),
        ))
        log = merge_play_log(merge_play_log([], first, NOW), second, NOW)
        self.assertEqual(aggregate_weekly_top(log, NOW), [
            {"artist": "Trivium", "title": "Death Throes", "plays": 2},
            {"artist": "Trivium", "title": "The Terror", "plays": 2},
        ])

    def test_chart_ages_out_as_the_log_ages(self):
        plays = parse_recently_played(
            _payload(_item("A", "1", _stamp(_ago(days=6))))
        )
        log = merge_play_log([], plays, NOW)
        self.assertEqual(len(aggregate_weekly_top(log, NOW)), 1)
        self.assertEqual(
            aggregate_weekly_top(log, NOW + timedelta(days=1)),
            [{"artist": "A", "title": "1", "plays": 1}],
        )
        self.assertEqual(
            aggregate_weekly_top(log, NOW + timedelta(days=1, seconds=1)), []
        )


class TestCommandLine(unittest.TestCase):
    def _exit_code(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(argv)
        return caught.exception.code

    def test_keep_alive_without_publish_is_rejected_before_any_network(self):
        self.assertEqual(self._exit_code(["--keep-alive"]), 2)

    def test_unknown_flag_is_rejected(self):
        self.assertEqual(self._exit_code(["--nonsense"]), 2)


if __name__ == "__main__":
    unittest.main()
