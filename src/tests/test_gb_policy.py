"""Policy orchestration: the order of checks and the codes they return.

The blocked term is the fake 'zqblocked' — a fake proves the wiring as
well as a real slur and keeps the file readable. Rejections are asserted
as the WHOLE verdict, never just `.code`, or a mutant that flips `ok`,
`display`, or `has_swap` alone survives every test in the file.
"""
import random
import unittest
from dataclasses import FrozenInstanceError

from matching import Blocklist, contains_blocked, digest
from policy import (
    MAX_MESSAGE,
    MAX_NAME,
    Verdict,
    check_message,
    check_name,
    contains_url,
)
from swaps import apply_swaps

BLOCKED_TERM = "zqblocked"
BLOCKLIST = Blocklist(
    digests=frozenset({digest(BLOCKED_TERM)}),
    minlen=3,
    maxlen=9,
    substr_minlen=5,
)
ALLOW: frozenset[str] = frozenset()
SWAPS = {"fuck": "flip"}

# Zero-width and invisible characters, kept in step with
# normalize.ZERO_WIDTH. A submission built only from these is blank on
# screen but not blank to str.strip().
INVISIBLES = ("​", "‌", "‍", "﻿", "­")


class _ExplodingBlocklist:
    """A blocklist that fails the test if the matcher ever consults it —
    the only way to observe check ORDER from outside."""

    def __getattr__(self, name):
        raise AssertionError(
            "contains_blocked ran before the length cap -- the cap is "
            "what bounds its cost"
        )


class VerdictAssertions:
    """Full-verdict assertions, so no field goes unpinned."""

    def assertRejected(self, verdict, code):
        self.assertEqual(
            (verdict.ok, verdict.code, verdict.display, verdict.has_swap),
            (False, code, None, False),
        )

    def assertAccepted(self, verdict, display, has_swap=False):
        self.assertEqual(
            (verdict.ok, verdict.code, verdict.display, verdict.has_swap),
            (True, None, display, has_swap),
        )


class TestFixturesActuallyFire(unittest.TestCase):
    """Non-vacuity controls: fail first if the fixtures below silently
    stop matching, instead of the whole file passing while proving nothing."""

    def test_the_fixture_blocklist_matches_its_term(self):
        self.assertTrue(contains_blocked(BLOCKED_TERM, BLOCKLIST, ALLOW))

    def test_the_fixture_blocklist_ignores_clean_text(self):
        self.assertFalse(contains_blocked("nice site", BLOCKLIST, ALLOW))

    def test_the_fixture_swap_map_is_not_empty(self):
        self.assertEqual(SWAPS, {"fuck": "flip"})


class TestContainsUrl(unittest.TestCase):
    def test_detects_http(self):
        self.assertTrue(contains_url("see http://x.com"))

    def test_detects_https(self):
        self.assertTrue(contains_url("see https://x.com"))

    def test_detects_a_plain_http_scheme_with_no_dotted_host(self):
        # The scheme alone is enough; there is no domain here to fall
        # back on, so this is what proves the 's' is optional.
        self.assertTrue(contains_url("go to http://localhost"))

    def test_detects_an_https_scheme_with_no_dotted_host(self):
        # ... and this is what proves the scheme is not spelled 'http'.
        self.assertTrue(contains_url("go to https://localhost"))

    def test_detects_scheme_case_insensitively(self):
        self.assertTrue(contains_url("HTTP://X.COM"))

    def test_detects_www(self):
        self.assertTrue(contains_url("see www.example.com"))

    def test_detects_a_www_host_no_bare_domain_rule_would_catch(self):
        # 'x' is a single character, so the bare-domain alternative
        # cannot fire. Only the www. rule can.
        self.assertTrue(contains_url("www.x"))

    def test_detects_bare_domain(self):
        self.assertTrue(contains_url("visit example.com today"))

    def test_detects_a_two_letter_tld(self):
        # Country codes are the short end of the range, and .io/.co are
        # where link spam actually lives.
        self.assertTrue(contains_url("buy at spam.io"))

    def test_detects_a_bare_domain_in_capitals(self):
        self.assertTrue(contains_url("EXAMPLE.COM is up"))

    def test_detects_a_domain_at_the_end_of_a_sentence(self):
        # A trailing full stop must not hide a link. See policy.py.
        self.assertTrue(contains_url("visit spam.com."))

    def test_detects_an_all_digit_label(self):
        self.assertTrue(contains_url("go to 123.com"))

    def test_detects_a_label_ending_in_a_hyphen(self):
        # '-' is a label character; a trailing one must not hide the dot.
        self.assertTrue(contains_url("go to foo-.com"))

    def test_detects_a_domain_glued_to_a_word_character(self):
        # No word-boundary anchor on the left: '_spam.com' is still a
        # link, and requiring a boundary there is a free evasion.
        self.assertTrue(contains_url("_spam.com"))

    def test_detects_the_longest_legal_tld(self):
        self.assertTrue(contains_url("a." + "b" * 63))

    def test_detects_a_scheme_prefixed_ip_address(self):
        self.assertTrue(contains_url("http://1.2.3.4"))

    def test_flags_a_run_on_sentence_as_the_cost_of_being_broad(self):
        # Documented false positive: a missing space after a full stop
        # reads as a domain. The visitor rephrases; a spammer does not
        # get a free pass. See the bias note in policy.py.
        self.assertTrue(contains_url("Cool site.Thanks!"))

    def test_allows_ordinary_prose(self):
        self.assertFalse(contains_url("hello there, nice site"))

    def test_allows_a_sentence_ending_in_a_period(self):
        self.assertFalse(contains_url("I like it. A lot."))

    def test_allows_decimals(self):
        self.assertFalse(contains_url("version 3.12 is good"))

    def test_allows_an_ellipsis(self):
        self.assertFalse(contains_url("well...maybe"))

    def test_allows_a_single_letter_extension(self):
        # No TLD is one character, and 'main.c' is a filename.
        self.assertFalse(contains_url("see main.c for details"))

    def test_allows_a_numeric_file_extension(self):
        # 'mp3' ends in a digit, so it is not a TLD-shaped word.
        self.assertFalse(contains_url("i uploaded song.mp3"))

    def test_allows_a_word_longer_than_the_tld_cap(self):
        self.assertFalse(contains_url("a." + "b" * 64))

    def test_allows_an_empty_string(self):
        self.assertFalse(contains_url(""))

    def test_allows_a_bare_ip_address(self):
        # Known and accepted miss: a dotted-quad has no letters, and
        # broadening to catch it would flag every version number. A
        # scheme-prefixed IP is still caught -- see the test above.
        self.assertFalse(contains_url("build 1.2.3.4 is out"))


class TestCheckName(VerdictAssertions, unittest.TestCase):
    def _check(self, name):
        return check_name(name, blocklist=BLOCKLIST, allow=ALLOW)

    def test_accepts_an_ordinary_name(self):
        self.assertAccepted(self._check("Bret"), "Bret")

    def test_rejects_empty(self):
        self.assertRejected(self._check(""), "empty")

    def test_rejects_whitespace_only(self):
        self.assertRejected(self._check("   "), "empty")

    def test_rejects_invisible_characters_as_empty(self):
        # A zero-width name renders as a blank card. str.strip() alone
        # does not remove these, so each one is checked.
        for char in INVISIBLES:
            with self.subTest(char=hex(ord(char))):
                self.assertRejected(self._check(" " + char + " "), "empty")

    def test_accepts_forty_characters(self):
        self.assertAccepted(self._check("a" * 40), "a" * 40)

    def test_rejects_forty_one_characters(self):
        self.assertRejected(self._check("a" * 41), "name_too_long")

    def test_publishes_its_cap_as_forty(self):
        # The frontend counter and Task 8 both read this constant; a
        # literal is what stops the two boundary tests above from moving
        # with it.
        self.assertEqual(MAX_NAME, 40)

    def test_rejects_a_url(self):
        self.assertRejected(self._check("www.spam.com"), "url_not_allowed")

    def test_rejects_a_slur(self):
        self.assertRejected(self._check(BLOCKED_TERM), "blocked")

    def test_accepts_a_real_unfortunate_surname(self):
        # The whole point of names being slur-checked only.
        self.assertAccepted(self._check("James Cockburn"), "James Cockburn")

    def test_accepts_a_joke_name(self):
        # Joke names are permitted by design. See spec 6.4.
        self.assertAccepted(self._check("Mike Hawk"), "Mike Hawk")

    def test_accepts_another_joke_name(self):
        self.assertAccepted(self._check("Dixie Normus"), "Dixie Normus")

    def test_accepts_profanity_in_a_name(self):
        # Names are NOT profanity-checked.
        self.assertAccepted(self._check("Fuckface McGee"), "Fuckface McGee")

    def test_never_swaps_profanity_in_a_name(self):
        # 'Fuck' here is a whole word, so it is exactly what the swap map
        # would rewrite. The name must come back untouched, and
        # has_swap must stay False: wiring swaps into check_name is the
        # mutation this test exists to kill.
        self.assertAccepted(self._check("Fuck McGee"), "Fuck McGee")

    def test_strips_surrounding_whitespace(self):
        self.assertAccepted(self._check("  Bret  "), "Bret")

    def test_length_is_measured_after_stripping(self):
        padded = "  " + "a" * 40 + "  "
        self.assertAccepted(self._check(padded), "a" * 40)

    def test_preserves_non_ascii_letters_in_the_display_form(self):
        # Normalization is a matching concern; it must never reach the
        # text that gets rendered.
        self.assertAccepted(self._check("Zoë Ölaf"), "Zoë Ölaf")

    def test_rejects_a_non_string(self):
        for value in (None, 12, b"Bret", ["Bret"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "name"):
                    self._check(value)


class TestNamePrecedence(VerdictAssertions, unittest.TestCase):
    """Order matters: the visitor should see the most actionable error."""

    def _check(self, name):
        return check_name(name, blocklist=BLOCKLIST, allow=ALLOW)

    def test_too_long_beats_url(self):
        self.assertRejected(
            self._check("www.spam.com" + "a" * 40), "name_too_long"
        )

    def test_too_long_beats_blocked(self):
        self.assertRejected(
            self._check(BLOCKED_TERM + " " + "a" * 40), "name_too_long"
        )

    def test_url_beats_blocked(self):
        self.assertRejected(
            self._check(BLOCKED_TERM + " spam.com"), "url_not_allowed"
        )

    def test_the_length_cap_runs_before_the_matcher(self):
        # Load-bearing beyond tidiness: contains_blocked hashes every
        # bounded substring of the text, which the cap is what bounds.
        self.assertRejected(
            check_name(
                "a" * 41, blocklist=_ExplodingBlocklist(), allow=ALLOW
            ),
            "name_too_long",
        )


class TestCheckMessage(VerdictAssertions, unittest.TestCase):
    def _check(self, message):
        return check_message(
            message, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
        )

    def test_accepts_an_ordinary_message(self):
        self.assertAccepted(self._check("nice site"), "nice site")

    def test_rejects_empty(self):
        self.assertRejected(self._check(""), "empty")

    def test_rejects_whitespace_only(self):
        self.assertRejected(self._check(" \t\n "), "empty")

    def test_rejects_invisible_characters_as_empty(self):
        for char in INVISIBLES:
            with self.subTest(char=hex(ord(char))):
                self.assertRejected(self._check(char * 3), "empty")

    def test_accepts_five_hundred_characters(self):
        self.assertAccepted(self._check("a" * 500), "a" * 500)

    def test_rejects_five_hundred_and_one_characters(self):
        self.assertRejected(self._check("a" * 501), "message_too_long")

    def test_publishes_its_cap_as_five_hundred(self):
        self.assertEqual(MAX_MESSAGE, 500)

    def test_rejects_a_url(self):
        self.assertRejected(self._check("buy at spam.com"), "url_not_allowed")

    def test_rejects_a_slur(self):
        self.assertRejected(self._check("you " + BLOCKED_TERM), "blocked")

    def test_swaps_profanity_and_flags_it(self):
        self.assertAccepted(
            self._check("hey fuck you"), "hey flip you", has_swap=True
        )

    def test_the_swap_keeps_the_case_pattern(self):
        self.assertAccepted(
            self._check("HEY FUCK YOU"), "HEY FLIP YOU", has_swap=True
        )

    def test_clean_message_reports_no_swap(self):
        self.assertAccepted(self._check("hey there"), "hey there")

    def test_strips_surrounding_whitespace_before_swapping(self):
        # Proves the swap runs on the trimmed text, not the raw input.
        self.assertAccepted(
            self._check("  hey fuck you  "), "hey flip you", has_swap=True
        )

    def test_length_is_measured_after_stripping(self):
        padded = "  " + "a" * 500 + "  "
        self.assertAccepted(self._check(padded), "a" * 500)

    def test_preserves_non_ascii_letters_in_the_display_form(self):
        self.assertAccepted(self._check("Café Zoë"), "Café Zoë")

    def test_rejects_a_non_string(self):
        for value in (None, 12, b"hi", ["hi"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "message"):
                    self._check(value)


class TestMessagePrecedence(VerdictAssertions, unittest.TestCase):
    """Order matters: the visitor should see the most actionable error."""

    def _check(self, message):
        return check_message(
            message, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
        )

    def test_too_long_beats_url(self):
        self.assertRejected(
            self._check("spam.com " + "a" * 500), "message_too_long"
        )

    def test_too_long_beats_blocked(self):
        self.assertRejected(
            self._check(BLOCKED_TERM + " " + "a" * 500), "message_too_long"
        )

    def test_url_beats_blocked(self):
        self.assertRejected(
            self._check(BLOCKED_TERM + " spam.com"), "url_not_allowed"
        )

    def test_empty_beats_everything(self):
        self.assertRejected(self._check("   "), "empty")

    def test_a_rejected_message_is_never_swapped(self):
        # display stays None and has_swap stays False even though the
        # text carries a swappable term: the swap runs after the checks.
        self.assertRejected(
            self._check("fuck off to spam.com"), "url_not_allowed"
        )

    def test_the_length_cap_runs_before_the_matcher(self):
        # Load-bearing beyond tidiness: contains_blocked hashes every
        # bounded substring of the text, and the cap is what bounds it.
        self.assertRejected(
            check_message(
                "a" * 501,
                blocklist=_ExplodingBlocklist(),
                allow=ALLOW,
                swaps=SWAPS,
            ),
            "message_too_long",
        )


class TestProperties(unittest.TestCase):
    """Invariants over generated input, not hand-picked examples."""

    CODES = frozenset(
        {"empty", "name_too_long", "message_too_long", "url_not_allowed",
         "blocked"}
    )
    PIECES = (
        "a", "z", "Bret", "hello", "fuck", "FUCK", BLOCKED_TERM, "www",
        "http://", "https://", ".", "..", "-", "_", "/", ":", " ", "  ",
        "\t", "\n", "com", "3.12", "é", "Ö", "а", "о", "​", "­",
        "﻿", "🙂", "0", "9", "!", "spam.com",
    )

    def _texts(self, count, pieces):
        rng = random.Random(20260820)
        for _ in range(count):
            yield "".join(
                rng.choice(self.PIECES) for _ in range(rng.randrange(pieces))
            )

    def test_name_verdicts_are_internally_consistent(self):
        for text in self._texts(400, 24):
            with self.subTest(text=text):
                verdict = check_name(
                    text, blocklist=BLOCKLIST, allow=ALLOW
                )
                self.assertIs(verdict.ok, verdict.code is None)
                self.assertIs(verdict.ok, verdict.display is not None)
                self.assertFalse(verdict.has_swap)
                if not verdict.ok:
                    self.assertIn(verdict.code, self.CODES)

    def test_an_accepted_name_is_the_trimmed_input_and_fits_the_cap(self):
        for text in self._texts(400, 24):
            with self.subTest(text=text):
                verdict = check_name(
                    text, blocklist=BLOCKLIST, allow=ALLOW
                )
                if verdict.ok:
                    self.assertIn(verdict.display, text)
                    self.assertEqual(verdict.display, verdict.display.strip())
                    self.assertTrue(0 < len(verdict.display) <= MAX_NAME)

    def test_an_accepted_name_is_accepted_again_unchanged(self):
        for text in self._texts(400, 24):
            with self.subTest(text=text):
                verdict = check_name(
                    text, blocklist=BLOCKLIST, allow=ALLOW
                )
                if verdict.ok:
                    self.assertEqual(
                        check_name(
                            verdict.display, blocklist=BLOCKLIST, allow=ALLOW
                        ),
                        verdict,
                    )

    def test_message_verdicts_are_internally_consistent(self):
        for text in self._texts(200, 60):
            with self.subTest(text=text):
                verdict = check_message(
                    text, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
                )
                self.assertIs(verdict.ok, verdict.code is None)
                self.assertIs(verdict.ok, verdict.display is not None)
                if not verdict.ok:
                    self.assertIn(verdict.code, self.CODES)
                    self.assertFalse(verdict.has_swap)

    def test_a_valid_name_is_a_valid_message_with_the_swaps_applied(self):
        # Cross-checks the two functions against each other rather than
        # re-implementing the trimming rule in the test. The name cap is
        # the tighter one, so a name that passes must pass as a message,
        # and its display form is the name's with swaps applied.
        for text in self._texts(400, 24):
            with self.subTest(text=text):
                name = check_name(text, blocklist=BLOCKLIST, allow=ALLOW)
                if not name.ok:
                    continue
                message = check_message(
                    text, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
                )
                expected, swapped = apply_swaps(name.display, SWAPS)
                self.assertTrue(message.ok)
                self.assertEqual(message.display, expected)
                self.assertIs(message.has_swap, swapped)

    def test_the_generator_reaches_every_name_rejection_code(self):
        # Non-vacuity control. If the generator stops producing blocked
        # or over-length names, the properties above go quiet instead of
        # failing, and this is what notices.
        seen = {
            check_name(text, blocklist=BLOCKLIST, allow=ALLOW).code
            for text in self._texts(400, 24)
        }
        self.assertEqual(
            seen - {None},
            {"empty", "name_too_long", "url_not_allowed", "blocked"},
        )


class TestVerdict(unittest.TestCase):
    def test_is_immutable(self):
        verdict = Verdict(ok=True, code=None, display="x", has_swap=False)
        with self.assertRaises(FrozenInstanceError):
            verdict.ok = False

    def test_compares_by_value(self):
        self.assertEqual(
            Verdict(ok=True, code=None, display="x", has_swap=False),
            Verdict(ok=True, code=None, display="x", has_swap=False),
        )
