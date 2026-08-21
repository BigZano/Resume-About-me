"""Profanity is permitted and stored raw; only the rendering is softened.

The swap must never alter anything it did not match — this is the user's
message, not ours.
"""
import tempfile
import unittest
from pathlib import Path

from swaps import apply_swaps, load_swaps

SWAPS = {"fuck": "flip", "shit": "shoot", "damn": "dang"}


class TestApplySwaps(unittest.TestCase):
    def test_swaps_lowercase(self):
        self.assertEqual(apply_swaps("oh fuck", SWAPS), ("oh flip", True))

    def test_preserves_all_caps(self):
        self.assertEqual(apply_swaps("OH FUCK", SWAPS), ("OH FLIP", True))

    def test_preserves_title_case(self):
        self.assertEqual(apply_swaps("Fuck off", SWAPS), ("Flip off", True))

    def test_mixed_case_falls_back_to_replacement_as_written(self):
        result, _ = apply_swaps("FuCk", SWAPS)
        self.assertEqual(result.lower(), "flip")

    def test_reports_false_when_nothing_matched(self):
        self.assertEqual(apply_swaps("hello there", SWAPS), ("hello there", False))

    def test_leaves_unmatched_text_byte_identical(self):
        original = "Hello,   World! — café naïve  "
        self.assertEqual(apply_swaps(original, SWAPS), (original, False))

    def test_swaps_multiple_occurrences(self):
        self.assertEqual(
            apply_swaps("fuck fuck", SWAPS), ("flip flip", True)
        )

    def test_swaps_multiple_distinct_terms(self):
        result, swapped = apply_swaps("fuck this shit", SWAPS)
        self.assertEqual(result, "flip this shoot")
        self.assertTrue(swapped)

    def test_respects_word_boundaries(self):
        # Scunthorpe class: a term inside a longer word is not a match.
        self.assertEqual(
            apply_swaps("shitake mushrooms", SWAPS),
            ("shitake mushrooms", False),
        )

    def test_matches_term_adjacent_to_punctuation(self):
        self.assertEqual(apply_swaps("fuck!", SWAPS), ("flip!", True))

    def test_empty_text(self):
        self.assertEqual(apply_swaps("", SWAPS), ("", False))

    def test_empty_swap_map(self):
        self.assertEqual(apply_swaps("fuck", {}), ("fuck", False))

    def test_does_not_rewrite_case_of_untouched_words(self):
        result, _ = apply_swaps("HELLO fuck WORLD", SWAPS)
        self.assertEqual(result, "HELLO flip WORLD")

    def test_token_count_is_preserved(self):
        text = "one fuck three"
        result, _ = apply_swaps(text, SWAPS)
        self.assertEqual(len(result.split()), len(text.split()))

    def test_longest_term_wins_when_one_contains_another(self):
        # 'cat' is a strict prefix of 'cat-nap'. The hyphen is a non-word
        # character, so \b alone is satisfied by BOTH 'cat' (boundary at
        # the hyphen) and 'cat-nap' (boundary at the following space) --
        # unlike plain alphabetic overlaps such as 'ass'/'asshole', where
        # \b already rules out the short match on its own. Sorting terms
        # longest-first is what decides this case, not \b.
        overlapping = {"cat": "feline", "cat-nap": "snooze"}
        result, swapped = apply_swaps("time for a cat-nap", overlapping)
        self.assertEqual(result, "time for a snooze")
        self.assertTrue(swapped)


class TestLoadSwaps(unittest.TestCase):
    def _write(self, body: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        return handle.name

    def test_parses_arrow_pairs(self):
        path = self._write("fuck = flip\nshit = shoot\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip", "shit": "shoot"})

    def test_ignores_comments_and_blanks(self):
        path = self._write("# a comment\n\nfuck = flip\n\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_lowercases_keys(self):
        path = self._write("FUCK = flip\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_tolerates_missing_file(self):
        self.assertEqual(load_swaps("/nonexistent/swaps.txt"), {})

    def test_skips_malformed_lines_without_raising(self):
        path = self._write("fuck = flip\ngarbage line\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_skips_lines_with_an_empty_term(self):
        path = self._write(" = flip\nfuck = flip\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_skips_lines_with_an_empty_replacement(self):
        path = self._write("fuck = \nshit = shoot\n")
        self.assertEqual(load_swaps(path), {"shit": "shoot"})

    def test_ignores_a_comment_that_itself_contains_the_separator(self):
        # A comment can describe the file format ("# term = replacement")
        # and must never be parsed as a real entry.
        path = self._write("# term = replacement\nfuck = flip\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_real_swaps_file_parses(self):
        real = Path(__file__).resolve().parents[2] / "worker" / "data" / "swaps.txt"
        self.assertGreater(len(load_swaps(str(real))), 0)
