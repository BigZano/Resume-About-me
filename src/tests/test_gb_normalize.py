"""Normalization is the foundation of the whole content policy.

Every evasion technique the filter defends against is defeated here or
not at all, so this module carries the heaviest hostile battery.

All inputs are benign nonsense words. The real denylist is never needed to
prove this module correct -- folding 'wooord' to 'word' exercises exactly
the same code path as folding a slur would.
"""
import random
import unicodedata
import unittest

from normalize import (
    CONFUSABLES,
    DELEET,
    ZERO_WIDTH,
    candidates,
    normalize,
    strip_nonalnum,
)

# The tables are re-declared here, independently of the module, so that
# dropping or altering a single entry in normalize.py fails a test rather
# than silently opening an evasion route.
EXPECTED_ZERO_WIDTH = {
    "​",  # ZERO WIDTH SPACE
    "‌",  # ZERO WIDTH NON-JOINER
    "‍",  # ZERO WIDTH JOINER
    "﻿",  # ZERO WIDTH NO-BREAK SPACE
    "­",  # SOFT HYPHEN
}

EXPECTED_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "і": "i", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ɡ": "g",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v",
    "τ": "t", "Β": "b", "Κ": "k",
}

EXPECTED_DELEET = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
    "|": "l", "+": "t",
}

# Hostile alphabet for the property batteries: plain text, separators,
# invisibles, homoglyphs, combining marks, fullwidth forms, astral planes.
HOSTILE_ALPHABET = (
    "abcXYZ019 .-_"
    + "".join(EXPECTED_ZERO_WIDTH)
    + "".join(EXPECTED_CONFUSABLES)
    + "".join(EXPECTED_DELEET)
    + "́̈"      # combining acute, combining diaeresis
    + "Ｈｅ"      # fullwidth H, fullwidth e
    + "ßẞ"      # sharp s, capital sharp s
    + "\U0001f600"        # emoji
    + "中"            # CJK
)


def _hostile_strings(count=300, maxlen=12, seed=20260820):
    """Deterministic pseudo-random hostile inputs.

    Seeded so a property failure is reproducible; the seed never changes.
    """
    rng = random.Random(seed)
    out = [""]
    for _ in range(count):
        length = rng.randrange(0, maxlen + 1)
        out.append(
            "".join(rng.choice(HOSTILE_ALPHABET) for _ in range(length))
        )
    return out


class TestNormalize(unittest.TestCase):
    def test_casefolds(self):
        self.assertEqual(normalize("HELLO"), "hello")

    def test_casefolds_rather_than_lowercases(self):
        # str.lower() leaves the sharp s alone; casefold expands it. A
        # lower() implementation would let 'strasse' evasion through.
        self.assertEqual(normalize("ß"), "ss")
        self.assertEqual(normalize("ẞ"), "ss")

    def test_strips_combining_marks(self):
        self.assertEqual(normalize("nïce"), "nice")

    def test_strips_stacked_combining_marks(self):
        self.assertEqual(normalize("á̈̄b"), "ab")

    def test_strips_every_zero_width_char(self):
        for char in sorted(EXPECTED_ZERO_WIDTH):
            with self.subTest(char=hex(ord(char))):
                self.assertEqual(normalize("he" + char + "llo"), "hello")

    def test_strips_zero_width_chars(self):
        self.assertEqual(normalize("he​llo"), "hello")

    def test_strips_soft_hyphen(self):
        self.assertEqual(normalize("he­llo"), "hello")

    def test_maps_cyrillic_confusables(self):
        # Cyrillic a e o and s, visually identical to Latin.
        self.assertEqual(normalize("аеос"), "aeoc")

    def test_maps_greek_confusables(self):
        self.assertEqual(normalize("αο"), "ao")

    def test_maps_every_documented_confusable(self):
        for src, dst in sorted(EXPECTED_CONFUSABLES.items()):
            with self.subTest(src=hex(ord(src))):
                self.assertEqual(normalize(src), dst)

    def test_maps_uppercase_confusables(self):
        # Confusable folding must survive case. Uppercase Cyrillic A/E/O/S
        # are the most obvious homoglyph attack there is; a table applied
        # before casefold would miss every one of them.
        self.assertEqual(normalize("АЕОС"), "aeoc")
        self.assertEqual(normalize("Х"), "x")
        self.assertEqual(normalize("Ρ"), "p")

    def test_maps_lowercase_of_uppercase_table_entries(self):
        # The table lists capital Beta and Kappa; lowercase beta and kappa
        # are the same homoglyph and must fold too.
        self.assertEqual(normalize("β"), "b")
        self.assertEqual(normalize("κ"), "k")

    def test_nfkd_folds_fullwidth(self):
        self.assertEqual(
            normalize("ｈｅｌｌｏ"), "hello"
        )

    def test_nfkd_folds_compatibility_ligature(self):
        self.assertEqual(normalize("ﬁn"), "fin")

    def test_empty_string(self):
        self.assertEqual(normalize(""), "")

    def test_whitespace_preserved_between_words(self):
        self.assertEqual(normalize("a b"), "a b")

    def test_punctuation_preserved(self):
        self.assertEqual(normalize("a.b-c"), "a.b-c")

    def test_is_idempotent(self):
        once = normalize("Ｎö​rа")
        self.assertEqual(normalize(once), once)

    def test_does_not_deleet(self):
        # normalize() is the plain fold. Deleeting belongs to candidates(),
        # or a numeric term would be destroyed before it could be matched.
        self.assertEqual(normalize("l33t"), "l33t")

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            normalize(None)

    def test_lone_surrogate_does_not_crash(self):
        self.assertEqual(normalize("a\ud800b"), "a\ud800b")

    def test_astral_char_survives(self):
        self.assertEqual(normalize("a\U0001f600"), "a\U0001f600")


class TestNormalizeProperties(unittest.TestCase):
    """Invariants that must hold over the whole hostile input domain."""

    def test_is_idempotent_over_hostile_inputs(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                once = normalize(text)
                self.assertEqual(normalize(once), once)

    def test_output_never_contains_a_combining_mark(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                for char in normalize(text):
                    self.assertNotEqual(unicodedata.category(char), "Mn")

    def test_output_never_contains_a_zero_width_char(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                for char in normalize(text):
                    self.assertNotIn(char, EXPECTED_ZERO_WIDTH)

    def test_output_never_contains_a_confusable(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                for char in normalize(text):
                    self.assertNotIn(char, EXPECTED_CONFUSABLES)

    def test_output_is_already_casefolded(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                folded = normalize(text)
                self.assertEqual(folded.casefold(), folded)


class TestStripNonalnum(unittest.TestCase):
    def test_removes_spaces_and_punctuation(self):
        self.assertEqual(strip_nonalnum("a b.c-d_e"), "abcde")

    def test_keeps_digits(self):
        self.assertEqual(strip_nonalnum("a1b2"), "a1b2")

    def test_preserves_order(self):
        self.assertEqual(strip_nonalnum("!c?b.a"), "cba")

    def test_removes_zero_width_chars(self):
        self.assertEqual(strip_nonalnum("a​b"), "ab")

    def test_empty(self):
        self.assertEqual(strip_nonalnum(""), "")

    def test_all_punctuation_yields_empty(self):
        self.assertEqual(strip_nonalnum(" .-_!"), "")

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            strip_nonalnum(None)

    def test_output_is_all_alnum(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertTrue(all(c.isalnum() for c in strip_nonalnum(text)))

    def test_is_idempotent(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                once = strip_nonalnum(text)
                self.assertEqual(strip_nonalnum(once), once)


class TestCandidates(unittest.TestCase):
    def test_always_includes_plain_normalized_form(self):
        self.assertIn("hello", candidates("HELLO"))

    def test_includes_deleet_variant(self):
        self.assertIn("leet", candidates("l33t"))

    def test_deleets_symbol_substitutions(self):
        self.assertIn("bass", candidates("b@$$"))

    def test_includes_separator_stripped_variant(self):
        self.assertIn("banana", candidates("b a n a n a"))

    def test_collapses_long_runs_to_one(self):
        self.assertIn("word", candidates("wooord"))

    def test_collapses_runs_broken_up_by_separators(self):
        # Separators must be stripped BEFORE collapsing, or a run split by
        # spaces never becomes adjacent and is never collapsed.
        self.assertIn("word", candidates("w o o o o r d"))

    def test_preserves_genuine_doubles(self):
        # 'less' must survive separator stripping: a collapse-to-1 rule
        # alone would destroy the doubled s.
        self.assertIn("less", candidates("l e s s"))

    def test_collapse_to_two_variant_exists(self):
        self.assertIn("baall", candidates("baaaall"))

    def test_includes_partially_collapsed_then_stripped_form(self):
        # 'aa aa aa' -> collapse to 1 -> 'a a a' -> strip -> 'aaa'.
        # No other route produces this spelling.
        self.assertIn("aaa", candidates("aa aa aa"))

    def test_deleet_does_not_destroy_the_original(self):
        # Digits must still be checkable as digits, not only as letters.
        self.assertIn("1234", candidates("1234"))

    def test_combined_evasion_deleet_plus_spacing(self):
        self.assertIn("banana", candidates("b @ n 4 n 4"))

    def test_combined_evasion_confusable_plus_repeat(self):
        self.assertIn("banana", candidates("bаnаnаа"))

    def test_empty_input_yields_empty_candidate(self):
        self.assertIn("", candidates(""))

    def test_returns_frozenset(self):
        self.assertIsInstance(candidates("x"), frozenset)

    def test_members_are_strings(self):
        self.assertTrue(all(isinstance(c, str) for c in candidates("a1 b2")))

    def test_rejects_non_string(self):
        with self.assertRaises(TypeError):
            candidates(None)

    def test_large_input_does_not_explode(self):
        # 10KB of text: candidate count is bounded by the number of
        # transforms, never by input length.
        self.assertLessEqual(len(candidates("a b " * 2500)), 16)


class TestCandidatesProperties(unittest.TestCase):
    def test_always_contains_the_plain_normalized_form(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertIn(normalize(text), candidates(text))

    def test_always_contains_the_separator_stripped_form(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertIn(
                    strip_nonalnum(normalize(text)), candidates(text)
                )

    def test_size_is_bounded_by_transform_count(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertLessEqual(len(candidates(text)), 16)

    def test_never_empty(self):
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertGreater(len(candidates(text)), 0)

    def test_contains_a_fully_collapsed_form(self):
        # Some candidate must have no adjacent repeated characters, or the
        # 'wooord' class of evasion is unreachable.
        for text in _hostile_strings():
            with self.subTest(text=repr(text)):
                self.assertTrue(any(
                    all(a != b for a, b in zip(form, form[1:]))
                    for form in candidates(text)
                ))


class TestTables(unittest.TestCase):
    def test_deleet_maps_digits_to_letters(self):
        self.assertEqual(DELEET["3"], "e")
        self.assertEqual(DELEET["@"], "a")

    def test_deleet_is_exactly_the_documented_table(self):
        self.assertEqual(DELEET, EXPECTED_DELEET)

    def test_deleet_entries_are_single_chars(self):
        for src, dst in DELEET.items():
            with self.subTest(src=src):
                self.assertEqual(len(src), 1)
                self.assertEqual(len(dst), 1)
                self.assertTrue(dst.islower())

    def test_confusables_are_single_chars(self):
        for src, dst in CONFUSABLES.items():
            with self.subTest(src=hex(ord(src))):
                self.assertEqual(len(src), 1)
                self.assertEqual(len(dst), 1)

    def test_confusables_is_exactly_the_documented_table(self):
        self.assertEqual(CONFUSABLES, EXPECTED_CONFUSABLES)

    def test_confusable_targets_are_ascii_lowercase(self):
        for dst in CONFUSABLES.values():
            with self.subTest(dst=dst):
                self.assertTrue("a" <= dst <= "z")

    def test_confusable_keys_are_unique_after_casefolding(self):
        # The fold table is keyed on the casefolded source. Two entries
        # that casefold together would silently shadow one another.
        folded = [src.casefold() for src in CONFUSABLES]
        self.assertEqual(len(folded), len(set(folded)))

    def test_zero_width_contains_zwsp(self):
        self.assertIn("​", ZERO_WIDTH)

    def test_zero_width_is_exactly_the_documented_set(self):
        self.assertEqual(set(ZERO_WIDTH), EXPECTED_ZERO_WIDTH)
        self.assertEqual(len(ZERO_WIDTH), len(EXPECTED_ZERO_WIDTH))

    def test_zero_width_chars_are_all_format_or_invisible(self):
        for char in ZERO_WIDTH:
            with self.subTest(char=hex(ord(char))):
                self.assertEqual(unicodedata.category(char), "Cf")


if __name__ == "__main__":
    unittest.main()
