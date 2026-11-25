import contextlib
import io
import itertools
import json
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fetch_playing import (
    GAME_LIMIT,
    STEAM_URL,
    load_existing_games,
    main,
    parse_recent_games,
    write_playing,
)

API_KEY = "SECRETKEY0123456789ABCDEF"
STEAM_ID = "76561198000000000"
ENV = {"STEAM_API_KEY": API_KEY, "STEAM_ID": STEAM_ID}


def _game(name, minutes, **extra):
    return dict({"appid": 1, "name": name, "playtime_2weeks": minutes,
                 "playtime_forever": 99999}, **extra)


def _payload(*games):
    return {"response": {"total_count": len(games), "games": list(games)}}


def _fetch_returning(payload):
    def fetch(api_key, steam_id):
        return payload
    return fetch


def _fetch_forbidden(api_key, steam_id):
    raise AssertionError("the Steam API must not be called")


class TestConstants(unittest.TestCase):
    def test_literals_are_pinned(self):
        self.assertEqual(GAME_LIMIT, 5)
        self.assertEqual(
            STEAM_URL,
            "https://api.steampowered.com/IPlayerService/"
            "GetRecentlyPlayedGames/v1/",
        )


class TestParseRecentGames(unittest.TestCase):
    def test_extracts_name_and_hours(self):
        self.assertEqual(
            parse_recent_games(_payload(_game("Hades", 90))),
            [{"name": "Hades", "hours_2weeks": 1.5}],
        )

    def test_output_carries_only_name_and_hours(self):
        # No appids, icon hashes or lifetime playtime in a public repo.
        result = parse_recent_games(
            _payload(_game("Hades", 90, img_icon_url="abc", appid=1145360))
        )
        self.assertEqual(set(result[0]), {"name", "hours_2weeks"})

    def test_sorted_by_two_week_playtime_longest_first(self):
        result = parse_recent_games(_payload(
            _game("Short", 60), _game("Long", 600), _game("Mid", 300),
        ))
        self.assertEqual([g["name"] for g in result], ["Long", "Mid", "Short"])

    def test_uses_two_week_playtime_not_lifetime(self):
        result = parse_recent_games(_payload(
            _game("Old favourite", 60, playtime_forever=900000),
            _game("New obsession", 600, playtime_forever=700),
        ))
        self.assertEqual(result[0]["name"], "New obsession")

    def test_ties_break_on_name_whatever_the_input_order(self):
        games = [_game("Charlie", 120), _game("Alpha", 120), _game("Bravo", 120)]
        for perm in itertools.permutations(games):
            with self.subTest(order=[g["name"] for g in perm]):
                result = parse_recent_games(_payload(*perm))
                self.assertEqual(
                    [g["name"] for g in result], ["Alpha", "Bravo", "Charlie"]
                )

    def test_default_limit_is_five(self):
        payload = _payload(*[_game(f"G{i}", 100 + i) for i in range(12)])
        result = parse_recent_games(payload)
        self.assertEqual(len(result), 5)
        # and they are the five longest, not the first five
        self.assertEqual([g["name"] for g in result],
                         ["G11", "G10", "G9", "G8", "G7"])

    def test_limit_parameter_is_honoured(self):
        payload = _payload(*[_game(f"G{i}", 100 + i) for i in range(12)])
        self.assertEqual(len(parse_recent_games(payload, limit=2)), 2)
        self.assertEqual(len(parse_recent_games(payload, limit=50)), 12)

    def test_fewer_than_limit_is_fine(self):
        self.assertEqual(len(parse_recent_games(_payload(_game("A", 5)))), 1)

    def test_strips_name_whitespace_and_keeps_unicode(self):
        result = parse_recent_games(
            _payload(_game("  Pok\u00e9mon & <Friends> \U0001f525  ", 60))
        )
        self.assertEqual(result[0]["name"], "Pok\u00e9mon & <Friends> \U0001f525")

    def test_float_minutes_are_accepted(self):
        result = parse_recent_games(_payload(_game("A", 90.0)))
        self.assertEqual(result[0]["hours_2weeks"], 1.5)

    def test_skips_unusable_games_but_keeps_good_ones(self):
        payload = _payload(
            _game("Good", 60),
            "not a dict",
            None,
            {"playtime_2weeks": 60},                                  # no name
            {"name": "", "playtime_2weeks": 60},
            {"name": "   ", "playtime_2weeks": 60},
            {"name": 7, "playtime_2weeks": 60},
            {"name": "No playtime"},
            {"name": "Null playtime", "playtime_2weeks": None},
            {"name": "String playtime", "playtime_2weeks": "60"},
            {"name": "Bool playtime", "playtime_2weeks": True},
            {"name": "Negative", "playtime_2weeks": -5},
            {"name": "Just negative", "playtime_2weeks": -1},
            {"name": "NaN", "playtime_2weeks": float("nan")},
            {"name": "Infinite", "playtime_2weeks": float("inf")},
            {"name": "Astronomical", "playtime_2weeks": 10 ** 400},
        )
        self.assertEqual(
            parse_recent_games(payload),
            [{"name": "Good", "hours_2weeks": 1.0}],
        )


class TestPlaytimeRounding(unittest.TestCase):
    def _hours(self, minutes):
        """hours_2weeks for a lone game, or None when it is dropped."""
        result = parse_recent_games(_payload(_game("G", minutes)))
        return result[0]["hours_2weeks"] if result else None

    def _hours_or_zero(self, minutes):
        hours = self._hours(minutes)
        return 0.0 if hours is None else hours

    def test_whole_hours(self):
        self.assertEqual(self._hours(60), 1.0)
        self.assertEqual(self._hours(600), 10.0)
        self.assertEqual(self._hours(1200), 20.0)

    def test_steam_reports_minutes_not_hours(self):
        # 30 minutes must come out as half an hour, not 30 hours.
        self.assertEqual(self._hours(30), 0.5)

    def test_rounds_to_one_decimal(self):
        self.assertEqual(self._hours(1234), 20.6)   # 20.5667
        self.assertEqual(self._hours(59), 1.0)      # 0.9833
        self.assertEqual(self._hours(61), 1.0)      # 1.0167
        self.assertEqual(self._hours(14), 0.2)      # 0.2333
        self.assertEqual(self._hours(8), 0.1)       # 0.1333

    def test_halves_round_up(self):
        # Exact halves of a tenth of an hour (3 min = 0.05 h). Float
        # round() lands on either side of these by accident of binary.
        self.assertEqual(self._hours(3), 0.1)
        self.assertEqual(self._hours(9), 0.2)       # 0.15
        self.assertEqual(self._hours(15), 0.3)      # 0.25
        self.assertEqual(self._hours(21), 0.4)      # 0.35

    def test_just_under_a_half_rounds_down(self):
        self.assertEqual(self._hours(8), 0.1)       # 0.1333, not 0.2
        self.assertEqual(self._hours(2), None)      # 0.0333 -> 0.0 -> dropped

    def test_games_that_round_to_zero_hours_are_dropped(self):
        for minutes in (0, 1, 2, 0.4, 2.9):         # 0.0 up to just under 0.05 h
            with self.subTest(minutes=minutes):
                self.assertEqual(
                    parse_recent_games(_payload(_game("G", minutes))), []
                )

    def test_the_first_playtime_that_survives_is_three_minutes(self):
        # 3 min = 0.05 h, which rounds half up to 0.1.
        self.assertEqual(
            parse_recent_games(_payload(_game("G", 3))),
            [{"name": "G", "hours_2weeks": 0.1}],
        )

    def test_dropped_games_do_not_use_up_the_limit_or_leave_gaps(self):
        payload = _payload(
            _game("Real A", 120), _game("Blip 1", 1), _game("Real B", 60),
            _game("Blip 2", 2), _game("Blip 3", 0),
        )
        self.assertEqual(
            [g["name"] for g in parse_recent_games(payload)], ["Real A", "Real B"]
        )

    def test_a_dropped_game_cannot_hide_a_real_one_below_the_limit(self):
        payload = _payload(
            *[_game(f"Real {i}", 600 - i) for i in range(5)],
            _game("Blip", 1),
        )
        self.assertEqual(len(parse_recent_games(payload)), 5)
        self.assertNotIn("Blip", [g["name"] for g in parse_recent_games(payload)])

    def test_no_returned_game_ever_shows_zero_hours(self):
        payload = _payload(*[_game(f"G{i}", i) for i in range(0, 40)])
        for game in parse_recent_games(payload, limit=100):
            self.assertGreater(game["hours_2weeks"], 0.0)

    def test_result_is_a_float_with_at_most_one_decimal(self):
        for minutes in (3, 7, 30, 59, 61, 1234, 20160):
            with self.subTest(minutes=minutes):
                hours = self._hours(minutes)
                self.assertIsInstance(hours, float)
                self.assertEqual(round(hours, 1), hours)

    def test_matches_an_independent_decimal_oracle_for_every_minute(self):
        # Two full weeks of minutes, checked against exact decimal arithmetic.
        for minutes in range(0, 14 * 24 * 60 + 1):
            expected = float(
                (Decimal(minutes) / Decimal(60)).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
            )
            # A game that rounds to 0.0 hours is dropped, not shown as 0.0.
            self.assertEqual(
                self._hours(minutes), expected or None, msg=minutes
            )

    def test_more_playtime_never_means_fewer_hours(self):
        previous = -1.0
        for minutes in range(0, 600):
            current = self._hours_or_zero(minutes)
            self.assertGreaterEqual(current, previous)
            previous = current

    def test_hours_are_always_within_a_twentieth_of_the_truth(self):
        for minutes in range(0, 2000, 7):
            self.assertLessEqual(
                abs(self._hours_or_zero(minutes) - minutes / 60), 0.05 + 1e-9
            )


class TestParseRecentGamesQuietStretch(unittest.TestCase):
    """A public profile with nothing played lately is valid, not a fault.

    A red run every 4 hours over a quiet stretch would train the owner to
    ignore real failures.
    """

    def test_total_count_zero_and_no_games_key_means_no_games(self):
        # What Steam sends for a public profile with nothing played lately.
        self.assertEqual(
            parse_recent_games({"response": {"total_count": 0}}), []
        )

    def test_an_empty_games_list_means_no_games(self):
        self.assertEqual(parse_recent_games({"response": {"games": []}}), [])

    def test_total_count_zero_with_an_empty_games_list_means_no_games(self):
        self.assertEqual(
            parse_recent_games({"response": {"total_count": 0, "games": []}}), []
        )

    def test_games_that_all_round_to_zero_hours_mean_no_games(self):
        self.assertEqual(
            parse_recent_games(_payload(_game("Blip", 1), _game("Blip 2", 0))), []
        )


class TestParseRecentGamesRejections(unittest.TestCase):
    """Anything that is not a clean "nothing played" or a usable list raises."""

    def test_empty_response_means_a_private_profile(self):
        with self.assertRaises(ValueError) as caught:
            parse_recent_games({"response": {}})
        self.assertIn("private", str(caught.exception))

    def test_a_count_that_is_not_zero_with_no_games_raises(self):
        for count in (1, 3, -1, 0.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                parse_recent_games({"response": {"total_count": count}})

    def test_a_count_that_is_not_the_integer_zero_raises(self):
        # False == 0 in Python, and a string is not a count.
        for count in (False, "0", None, [], 0.0):
            with self.subTest(count=count), self.assertRaises(ValueError):
                parse_recent_games({"response": {"total_count": count}})

    def test_a_response_with_neither_games_nor_a_count_raises(self):
        for response in ({"foo": 1}, {"game_count": 0}, {"games_list": []}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_recent_games({"response": response})

    def test_non_empty_games_with_nothing_usable_raises(self):
        # Steam returned entries but none parse: that smells like a shape
        # change, so it must not be mistaken for a quiet stretch.
        with self.assertRaises(ValueError):
            parse_recent_games(_payload("x", 1, {}, {"name": "No time"}))

    def test_missing_response_key_raises(self):
        with self.assertRaises(ValueError):
            parse_recent_games({})

    def test_response_wrong_type_raises(self):
        for bad in [None, [], "response", 3, True]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recent_games({"response": bad})

    def test_games_wrong_type_raises(self):
        for bad in [None, {}, "Hades", 3, ""]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recent_games({"response": {"games": bad}})
        # ...even when total_count claims zero: a mistyped list is not "none".
        with self.assertRaises(ValueError):
            parse_recent_games({"response": {"total_count": 0, "games": None}})

    def test_non_dict_payload_raises(self):
        for bad in [None, "payload", 42, [], True]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recent_games(bad)


class TestPlayingFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "content" / "playing.json"

    def test_write_produces_the_documented_shape(self):
        games = [{"name": "Hades", "hours_2weeks": 1.5}]
        write_playing(self.path, games)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"fetched_at", "games"})
        self.assertRegex(data["fetched_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(data["games"], games)

    def test_write_creates_the_missing_directory(self):
        write_playing(self.path, [{"name": "A", "hours_2weeks": 1.0}])
        self.assertTrue(self.path.is_file())

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(self):
        write_playing(self.path, [{"name": "Keep me", "hours_2weeks": 1.0}])
        with self.assertRaises(TypeError):
            write_playing(self.path, [object()])             # not serialisable
        self.assertEqual(load_existing_games(self.path)[0]["name"], "Keep me")
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])

    def test_load_round_trips(self):
        games = [{"name": "A", "hours_2weeks": 2.5}]
        write_playing(self.path, games)
        self.assertEqual(load_existing_games(self.path), games)

    def test_load_gives_none_for_anything_unusable(self):
        self.assertIsNone(load_existing_games(self.path))        # missing
        self.path.parent.mkdir(parents=True)
        for raw in ["", "{corrupt", "[]", "42", "{}", '{"games": null}',
                    '{"games": {"a": 1}}', "[" * 200000]:
            with self.subTest(raw=raw[:20]):
                self.path.write_text(raw, encoding="utf-8")
                self.assertIsNone(load_existing_games(self.path))


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "content" / "playing.json"

    def _run(self, env, fetch):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--output", str(self.path)], env=env, fetch=fetch)
        return code, out.getvalue()

    def _seed(self, games, fetched_at="2020-01-01T00:00:00Z"):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"fetched_at": fetched_at, "games": games}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    # -- the secrets are not created yet: that must not break the workflow --

    def test_missing_env_is_a_noop_exit_zero(self):
        code, out = self._run({}, _fetch_forbidden)
        self.assertEqual(code, 0)
        self.assertIn("STEAM_API_KEY", out)         # the notice names the vars
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_either_variable_missing_is_a_noop(self):
        cases = {
            "key only": {"STEAM_API_KEY": API_KEY},
            "id only": {"STEAM_ID": STEAM_ID},
            "empty key": {"STEAM_API_KEY": "", "STEAM_ID": STEAM_ID},
            "empty id": {"STEAM_API_KEY": API_KEY, "STEAM_ID": ""},
            "blank key": {"STEAM_API_KEY": "   ", "STEAM_ID": STEAM_ID},
            "blank id": {"STEAM_API_KEY": API_KEY, "STEAM_ID": "\t\n"},
        }
        for label, env in cases.items():
            with self.subTest(label):
                code, _out = self._run(env, _fetch_forbidden)
                self.assertEqual(code, 0)
                self.assertFalse(self.path.exists())

    def test_missing_env_leaves_an_existing_file_byte_identical(self):
        self._seed([{"name": "Keep me", "hours_2weeks": 3.0}])
        before = self.path.read_bytes()
        code, _out = self._run({}, _fetch_forbidden)
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_the_notice_never_echoes_a_secret(self):
        _code, out = self._run({"STEAM_API_KEY": API_KEY}, _fetch_forbidden)
        self.assertNotIn(API_KEY, out)

    # -- the normal path --

    def test_writes_games_with_the_documented_shape(self):
        code, _out = self._run(
            ENV, _fetch_returning(_payload(_game("Hades", 90), _game("Celeste", 30)))
        )
        self.assertEqual(code, 0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"fetched_at", "games"})
        self.assertRegex(data["fetched_at"], r"Z$")
        self.assertEqual(data["games"], [
            {"name": "Hades", "hours_2weeks": 1.5},
            {"name": "Celeste", "hours_2weeks": 0.5},
        ])

    def test_passes_the_credentials_to_the_fetch(self):
        seen = {}

        def fetch(api_key, steam_id):
            seen.update(key=api_key, id=steam_id)
            return _payload(_game("A", 60))

        self._run({"STEAM_API_KEY": f"  {API_KEY} ", "STEAM_ID": f" {STEAM_ID}\n"},
                  fetch)
        self.assertEqual(seen, {"key": API_KEY, "id": STEAM_ID})

    def test_unchanged_games_leave_the_file_byte_identical(self):
        self._seed([{"name": "Hades", "hours_2weeks": 1.5}])
        before = self.path.read_bytes()
        code, _out = self._run(ENV, _fetch_returning(_payload(_game("Hades", 90))))
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_changed_games_rewrite_the_file_with_a_fresh_stamp(self):
        self._seed([{"name": "Hades", "hours_2weeks": 1.5}])
        self._run(ENV, _fetch_returning(_payload(_game("Hades", 150))))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["games"], [{"name": "Hades", "hours_2weeks": 2.5}])
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_leaves_no_temp_files_behind(self):
        self._run(ENV, _fetch_returning(_payload(_game("A", 60))))
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         [self.path.name])

    # -- failures: loud, and never destructive --

    def test_private_profile_exits_nonzero_and_writes_nothing(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(ENV, _fetch_returning({"response": {}}))
        self.assertNotIn(caught.exception.code, (0, None))
        self.assertFalse(self.path.exists())

    def test_private_profile_does_not_blank_an_existing_file(self):
        self._seed([{"name": "Keep me", "hours_2weeks": 3.0}])
        before = self.path.read_bytes()
        with self.assertRaises(SystemExit):
            self._run(ENV, _fetch_returning({"response": {}}))
        self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_payloads_exit_nonzero_and_write_nothing(self):
        for payload in ({}, None, [], "html error page",
                        {"response": None}, {"response": []},
                        {"response": {"total_count": 4}},
                        {"response": {"games": "Hades"}},
                        {"response": {"games": ["x", 1, {}]}}):
            with self.subTest(payload=payload):
                with self.assertRaises(SystemExit) as caught:
                    self._run(ENV, _fetch_returning(payload))
                self.assertNotIn(caught.exception.code, (0, None))
                self.assertFalse(self.path.exists())

    # -- a quiet stretch is a legitimate state: exit 0 and record it --

    QUIET = ({"response": {"total_count": 0}},
             {"response": {"games": []}},
             {"response": {"total_count": 0, "games": []}})

    def test_a_public_profile_with_nothing_played_writes_an_empty_list(self):
        for payload in self.QUIET:
            with self.subTest(payload=payload):
                if self.path.exists():
                    self.path.unlink()
                code, _out = self._run(ENV, _fetch_returning(payload))
                self.assertEqual(code, 0)
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(set(data), {"fetched_at", "games"})
                self.assertRegex(data["fetched_at"], r"Z$")
                self.assertEqual(data["games"], [])

    def test_a_quiet_stretch_replaces_last_fortnights_games(self):
        self._seed([{"name": "Hades", "hours_2weeks": 1.5}])
        code, _out = self._run(ENV, _fetch_returning(self.QUIET[0]))
        self.assertEqual(code, 0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["games"], [])
        self.assertNotEqual(data["fetched_at"], "2020-01-01T00:00:00Z")

    def test_a_quiet_stretch_already_recorded_leaves_the_file_alone(self):
        self._seed([])
        before = self.path.read_bytes()
        for payload in self.QUIET:
            with self.subTest(payload=payload):
                code, _out = self._run(ENV, _fetch_returning(payload))
                self.assertEqual(code, 0)
                self.assertEqual(self.path.read_bytes(), before)

    def test_games_that_all_round_to_zero_hours_count_as_a_quiet_stretch(self):
        code, _out = self._run(
            ENV, _fetch_returning(_payload(_game("Blip", 1), _game("Blip 2", 2)))
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8"))["games"], []
        )

    def test_the_failure_message_does_not_leak_the_key(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(ENV, _fetch_returning({"response": {}}))
        self.assertNotIn(API_KEY, str(caught.exception.code))

    def test_bad_arguments_are_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["--nonsense"], env=ENV, fetch=_fetch_forbidden)
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
