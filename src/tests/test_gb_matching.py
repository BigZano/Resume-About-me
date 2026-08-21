"""Denylist matching, tested entirely with benign terms.

Two kinds of term appear here, and neither is a slur:

  1. Fake terms ('zqblocked', 'zqhate', 'zqmid', 'zqs'). Hashing a fake
     term proves the algorithm exactly as well as hashing a real one, and
     keeps this file readable. The prefix is 'zq' rather than 'zz' on
     purpose: normalize.candidates() collapses runs of a repeated
     character, so a term that *starts* with a doubled letter can never
     survive the collapse-to-1 pass and the repeat-evasion test would be
     testing nothing.

  2. Canonical trigger fragments ('ass', 'cock', 'anal', 'cum', 'tit')
     in TestScunthorpeCorpus. These are mild profanity, not slurs, and
     they are precisely the fragments that make 'Scunthorpe',
     'Cockburn', 'assassin', 'analysis', 'bass', 'peacock', 'titles' and
     'cumulative' false-positive in naive filters.

worker/data/blocked.txt ships with a header and ZERO digests: the repo
owner supplies the plaintext terms and runs scripts/hash_terms.py
themselves, and the plaintext never enters the repo. An empty blocklist
makes contains_blocked() return False for everything, so a Scunthorpe
test aimed at the real file would pass while proving nothing. The real
corpus test therefore runs against a synthetic blocklist built here, and
carries a non-vacuity control (test_the_trigger_blocklist_actually_fires)
that fails the moment the corpus stops being a real test.
"""
import contextlib
import io
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

import hash_terms
from matching import (
    Blocklist,
    contains_blocked,
    digest,
    load_allow,
    load_blocked,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "worker" / "data"

# Fake terms, one per length class the algorithm cares about:
#   zqblocked (9) -- long, reachable by both passes
#   zqhate    (6) -- long enough for the substring pass
#   zqmid     (5) -- exactly substr_minlen
#   zqs       (3) -- below substr_minlen, word-boundary pass only
BLOCKED_TERMS = ["zqblocked", "zqhate", "zqmid", "zqs"]
MINLEN = 3
MAXLEN = 9

NO_ALLOW = frozenset()


def _blocklist(substr_minlen=5, terms=BLOCKED_TERMS, minlen=MINLEN,
               maxlen=MAXLEN):
    return Blocklist(
        digests=frozenset(digest(t) for t in terms),
        minlen=minlen,
        maxlen=maxlen,
        substr_minlen=substr_minlen,
    )


class TestDigest(unittest.TestCase):
    def test_is_stable(self):
        self.assertEqual(digest("abc"), digest("abc"))

    def test_normalizes_before_hashing(self):
        self.assertEqual(digest("ABC"), digest("abc"))

    def test_folds_confusables_before_hashing(self):
        # Cyrillic 'о' renders as Latin 'o'; normalize() maps it.
        self.assertEqual(digest("cоde"), digest("code"))

    def test_differs_between_terms(self):
        self.assertNotEqual(digest("abc"), digest("abd"))

    def test_is_hex_sha256(self):
        value = digest("abc")
        self.assertEqual(len(value), 64)
        int(value, 16)  # raises if not hex

    def test_is_lowercase_hex(self):
        # load_blocked() lowercases file digests to compare against these.
        self.assertEqual(digest("abc"), digest("abc").lower())

    def test_rejects_non_text(self):
        with self.assertRaises(TypeError):
            digest(None)


class TestContainsBlocked(unittest.TestCase):
    def test_plain_hit(self):
        self.assertTrue(
            contains_blocked("you zqblocked thing", _blocklist(), NO_ALLOW))

    def test_clean_text_passes(self):
        self.assertFalse(
            contains_blocked("hello there friend", _blocklist(), NO_ALLOW))

    def test_case_insensitive(self):
        self.assertTrue(contains_blocked("ZQBLOCKED", _blocklist(), NO_ALLOW))

    def test_catches_leetspeak(self):
        self.assertTrue(contains_blocked("zqbl0cked", _blocklist(), NO_ALLOW))

    def test_catches_spaced_evasion(self):
        self.assertTrue(
            contains_blocked("z q b l o c k e d", _blocklist(), NO_ALLOW))

    def test_catches_punctuation_evasion(self):
        self.assertTrue(
            contains_blocked("z.q.b.l.o.c.k.e.d", _blocklist(), NO_ALLOW))

    def test_catches_repeat_evasion(self):
        self.assertTrue(
            contains_blocked("zqbloooocked", _blocklist(), NO_ALLOW))

    def test_catches_combining_mark_evasion(self):
        self.assertTrue(contains_blocked("zqblöcked", _blocklist(),
                                         NO_ALLOW))

    def test_catches_zero_width_evasion(self):
        self.assertTrue(
            contains_blocked("zq​blo‍cked", _blocklist(), NO_ALLOW))

    def test_catches_homoglyph_evasion(self):
        # Cyrillic 'о' and 'с' inside an otherwise Latin word.
        self.assertTrue(
            contains_blocked("zqblоcked", _blocklist(), NO_ALLOW))

    def test_catches_uppercase_homoglyph_evasion(self):
        # Cyrillic capital 'О'. Folds only because normalize() casefolds
        # BEFORE mapping confusables.
        self.assertTrue(
            contains_blocked("ZQBLОCKED", _blocklist(), NO_ALLOW))

    def test_empty_text_passes(self):
        self.assertFalse(contains_blocked("", _blocklist(), NO_ALLOW))

    def test_whitespace_only_text_passes(self):
        self.assertFalse(contains_blocked("   \t\n", _blocklist(), NO_ALLOW))

    def test_empty_blocklist_passes_everything(self):
        empty = Blocklist(frozenset(), MINLEN, MAXLEN, 5)
        self.assertFalse(contains_blocked("zqblocked", empty, NO_ALLOW))

    def test_matches_a_term_containing_digits(self):
        # The word scanner must accept digits, not letters only.
        digity = _blocklist(terms=["zq42"], minlen=4, maxlen=4)
        self.assertTrue(contains_blocked("hey zq42 there", digity, NO_ALLOW))

    def test_rejects_non_text(self):
        with self.assertRaises(TypeError):
            contains_blocked(None, _blocklist(), NO_ALLOW)


class TestLengthBounds(unittest.TestCase):
    """The word-boundary pass is bounded by minlen/maxlen inclusively."""

    def test_word_of_exactly_minlen_matches(self):
        # 'zqs' is 3 == minlen, and below substr_minlen, so only the
        # word-boundary pass can catch it. An exclusive lower bound here
        # would let every minimum-length term through.
        tight = _blocklist(terms=["zqs"], minlen=3, maxlen=3)
        self.assertTrue(contains_blocked("what a zqs", tight, NO_ALLOW))

    def test_word_shorter_than_minlen_is_ignored(self):
        tight = _blocklist(terms=["zqs"], minlen=4, maxlen=9)
        self.assertFalse(contains_blocked("what a zqs", tight, NO_ALLOW))

    def test_word_longer_than_maxlen_is_ignored_by_the_word_pass(self):
        # maxlen 4 stops the word pass; substr_minlen 5 stops the other.
        tight = _blocklist(terms=["zqhate"], minlen=3, maxlen=4)
        self.assertFalse(contains_blocked("zqhate", tight, NO_ALLOW))

    def test_substring_pass_finds_a_term_at_the_start(self):
        self.assertTrue(
            contains_blocked("zqblockedxx", _blocklist(), NO_ALLOW))

    def test_substring_pass_finds_a_term_at_the_end(self):
        self.assertTrue(
            contains_blocked("xxzqblocked", _blocklist(), NO_ALLOW))

    def test_substring_pass_covers_a_term_of_exactly_maxlen(self):
        self.assertTrue(
            contains_blocked("xxzqblockedxx", _blocklist(), NO_ALLOW))

    def test_substring_pass_covers_a_term_of_exactly_substr_minlen(self):
        self.assertTrue(contains_blocked("xxzqmidxx", _blocklist(), NO_ALLOW))

    def test_both_passes_compare_alphanumeric_runs_only(self):
        # hash_terms.py canonicalizes every term to alphanumerics, so a
        # punctuated digest can only come from a hand-edited file. It must
        # stay inert: matching a chunk that spans a separator would make
        # 'zq-mid' block any hyphenation that happens to bridge it.
        punctuated = Blocklist(frozenset({digest("zq-mid")}), MINLEN,
                               MAXLEN, 5)
        self.assertFalse(
            contains_blocked("hey zq-mid there", punctuated, NO_ALLOW))

    def test_zero_substr_minlen_does_not_match_an_empty_digest(self):
        # A malformed header must not turn every message into a hit.
        weird = Blocklist(frozenset({digest("")}), 1, 5, 0)
        self.assertFalse(contains_blocked("hello", weird, NO_ALLOW))


class TestShortTermsAreWordOnly(unittest.TestCase):
    """The substr_minlen rule. Without it, short terms fire on ordinary text."""

    def test_short_term_matches_as_a_whole_word(self):
        self.assertTrue(contains_blocked("what a zqs", _blocklist(), NO_ALLOW))

    def test_short_term_does_not_match_inside_a_longer_word(self):
        # 'zqs' is 3 chars, below substr_minlen, so the stripped pass skips it.
        self.assertFalse(
            contains_blocked("puzqsolver", _blocklist(), NO_ALLOW))

    def test_lowering_substr_minlen_would_catch_it(self):
        # Proves the guard is load-bearing, not incidental.
        self.assertTrue(
            contains_blocked("puzqsolver", _blocklist(substr_minlen=3),
                             NO_ALLOW))

    def test_long_term_still_matches_inside_a_longer_word(self):
        self.assertTrue(
            contains_blocked("puzqblockedsolver", _blocklist(), NO_ALLOW))

    def test_a_short_term_alone_survives_separator_evasion(self):
        self.assertTrue(contains_blocked("z.q.s", _blocklist(), NO_ALLOW))

    def test_a_short_term_in_a_sentence_does_not(self):
        """Accepted limitation of the substr_minlen rule, not a bug.

        Stripping separators out of a sentence yields one long word, and a
        term below substr_minlen is never looked for inside a word. The
        alternative -- substring-scanning for 3-character terms -- blocks
        'bass', 'classic' and 'peacock', which is worse.
        """
        self.assertFalse(
            contains_blocked("hey z.q.s there", _blocklist(), NO_ALLOW))


class TestAllowlist(unittest.TestCase):
    """The Scunthorpe class. These must pass clean."""

    ALLOW = frozenset({"zqblockedford"})

    def test_allowlisted_word_containing_a_term_passes(self):
        self.assertFalse(
            contains_blocked("greetings from zqblockedford", _blocklist(),
                             self.ALLOW))

    def test_allowlist_is_subtracted_before_the_stripped_pass(self):
        # If subtraction happened after candidate generation, stripping
        # separators would re-expose the term inside the safe word.
        self.assertFalse(
            contains_blocked("zqblockedford, england", _blocklist(),
                             self.ALLOW))

    def test_allowlist_does_not_hide_a_genuine_hit_elsewhere(self):
        self.assertTrue(
            contains_blocked("zqblockedford and zqhate", _blocklist(),
                             self.ALLOW))

    def test_allowlist_only_subtracts_whole_words(self):
        # Without word boundaries the allow entry would eat its own prefix
        # out of a longer hostile word and hide the term that follows.
        self.assertTrue(
            contains_blocked("zqblockedfordzqhate", _blocklist(), self.ALLOW))

    def test_allowlist_does_not_eat_a_fragment_of_a_blocked_word(self):
        # 'hate' sits inside 'zqhate'. Without word boundaries the allow
        # entry would delete the middle of a blocked term and clear the
        # message -- allow.txt carries common words like 'pass' and
        # 'class', so this is how an allowlist entry turns into a bypass.
        self.assertTrue(
            contains_blocked("zqhate", _blocklist(), frozenset({"hate"})))

    def test_allowlist_matching_is_case_insensitive(self):
        self.assertFalse(
            contains_blocked("ZQBLOCKEDFORD", _blocklist(), self.ALLOW))

    def test_allowlist_entries_are_literal_not_patterns(self):
        # An unescaped '.' would match any character and silently delete
        # the real term from the message.
        self.assertTrue(
            contains_blocked("zqblocked", _blocklist(),
                             frozenset({"zq.locked"})))

    def test_allowlist_entry_with_regex_metacharacters_does_not_explode(self):
        self.assertFalse(
            contains_blocked("hello there", _blocklist(),
                             frozenset({"zq++ford", "a(b"})))

    def test_empty_allowlist_changes_nothing(self):
        self.assertTrue(
            contains_blocked("z q b l o c k e d", _blocklist(), frozenset()))


class TestLoaders(unittest.TestCase):
    def _write(self, body):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_load_blocked_parses_header_and_digests(self):
        # Deliberately NOT the loader's defaults: a header test using the
        # default values passes even when header parsing is dead code.
        path = self._write(
            "# minlen=4 maxlen=12 substr_minlen=7\n"
            + digest("zqblocked") + "\n"
        )
        result = load_blocked(path)
        self.assertEqual(result.minlen, 4)
        self.assertEqual(result.maxlen, 12)
        self.assertEqual(result.substr_minlen, 7)
        self.assertEqual(result.digests, frozenset({digest("zqblocked")}))

    def test_load_blocked_reads_header_keys_whole(self):
        # 'substr_minlen' ends in 'minlen'. Written in this order, a
        # boundary-less search for 'minlen' picks up the wrong number.
        path = self._write("# substr_minlen=7 maxlen=12 minlen=4\n")
        result = load_blocked(path)
        self.assertEqual(result.minlen, 4)
        self.assertEqual(result.substr_minlen, 7)

    def test_load_blocked_ignores_blank_lines(self):
        path = self._write(
            "# minlen=4 maxlen=12 substr_minlen=7\n\n" + digest("x") + "\n\n"
        )
        self.assertEqual(load_blocked(path).digests, frozenset({digest("x")}))

    def test_load_blocked_ignores_trailing_comments(self):
        path = self._write(
            "# minlen=4 maxlen=12 substr_minlen=7\n"
            "# Generated by scripts/hash_terms.py. Do not edit by hand.\n"
            + digest("x") + "\n"
        )
        self.assertEqual(load_blocked(path).digests, frozenset({digest("x")}))

    def test_load_blocked_folds_digest_case(self):
        path = self._write(
            "# minlen=4 maxlen=12 substr_minlen=7\n"
            + digest("zqblocked").upper() + "\n"
        )
        self.assertIn(digest("zqblocked"), load_blocked(path).digests)

    def test_load_blocked_tolerates_a_byte_order_mark(self):
        path = self._write(
            "﻿# minlen=4 maxlen=12 substr_minlen=7\n"
            + digest("x") + "\n"
        )
        result = load_blocked(path)
        self.assertEqual(result.minlen, 4)
        self.assertEqual(result.digests, frozenset({digest("x")}))

    def test_load_blocked_tolerates_a_header_only_file(self):
        path = self._write("# minlen=4 maxlen=12 substr_minlen=7\n")
        result = load_blocked(path)
        self.assertEqual(result.digests, frozenset())
        self.assertEqual(result.maxlen, 12)

    def test_load_blocked_uses_documented_defaults_without_a_header(self):
        path = self._write(digest("x") + "\n")
        result = load_blocked(path)
        self.assertEqual((result.minlen, result.maxlen, result.substr_minlen),
                         (3, 14, 5))

    def test_load_blocked_tolerates_missing_file(self):
        result = load_blocked("/nonexistent/blocked.txt")
        self.assertEqual(result.digests, frozenset())
        self.assertEqual((result.minlen, result.maxlen, result.substr_minlen),
                         (3, 14, 5))

    def test_load_blocked_tolerates_a_directory(self):
        result = load_blocked(str(DATA))
        self.assertEqual(result.digests, frozenset())

    def test_load_allow_lowercases_and_strips(self):
        path = self._write("# comment\n  Scunthorpe  \n\nAssassin\n")
        self.assertEqual(load_allow(path), frozenset({"scunthorpe",
                                                      "assassin"}))

    def test_load_allow_normalizes_accents(self):
        # Names arrive accented; the text they must match is folded.
        path = self._write("Björn\n")
        self.assertEqual(load_allow(path), frozenset({"bjorn"}))

    def test_load_allow_tolerates_a_byte_order_mark(self):
        path = self._write("﻿# comment\nScunthorpe\n")
        self.assertEqual(load_allow(path), frozenset({"scunthorpe"}))

    def test_load_allow_tolerates_missing_file(self):
        self.assertEqual(load_allow("/nonexistent/allow.txt"), frozenset())

    def test_real_allow_file_parses(self):
        allow = load_allow(str(DATA / "allow.txt"))
        self.assertGreater(len(allow), 0)
        self.assertNotIn("", allow)
        for word in allow:
            self.assertEqual(word, word.strip())
            self.assertFalse(word.startswith("#"))

    def test_real_blocked_file_has_a_valid_header(self):
        # Deliberately weak: the shipped file carries a header and zero
        # digests, because the plaintext terms never enter this repo. The
        # algorithm is proved by TestScunthorpeCorpus against a synthetic
        # blocklist, not here.
        result = load_blocked(str(DATA / "blocked.txt"))
        self.assertGreaterEqual(result.substr_minlen, 5)
        self.assertGreaterEqual(result.minlen, 1)
        self.assertGreaterEqual(result.maxlen, result.minlen)

    def test_real_blocked_file_carries_no_plaintext(self):
        # Every non-comment line must be a bare sha-256 hex digest.
        text = (DATA / "blocked.txt").read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.assertRegex(stripped, r"^[0-9a-fA-F]{64}$")


class TestScunthorpeCorpus(unittest.TestCase):
    """Real words that trip naive filters, against a real trigger list.

    The shipped blocked.txt is empty by design, so aiming this corpus at
    it would assert nothing. The blocklist here is built from the actual
    fragments that cause the Scunthorpe problem, and
    test_the_trigger_blocklist_actually_fires keeps the whole class
    honest.
    """

    TRIGGERS = ["ass", "cock", "anal", "cum", "tit"]

    CORPUS = [
        "Scunthorpe", "Cockburn", "assassin", "analysis", "classic",
        "shiitake", "Lipschitz", "Sussex", "Uranus", "bass", "pass",
        "grass", "Weiner", "Kuntz", "Dickinson", "Hoare", "Bumgarner",
        "therapist", "Matsushita", "Penistone", "cumulative", "titles",
        "peacock", "Hancock", "Babcock", "Cummings", "assessment",
        "canalise", "constitution", "Titan", "document", "circumstance",
    ]

    def setUp(self):
        self.blocklist = Blocklist(
            digests=frozenset(digest(t) for t in self.TRIGGERS),
            minlen=min(len(t) for t in self.TRIGGERS),
            maxlen=max(len(t) for t in self.TRIGGERS),
            substr_minlen=5,
        )
        self.allow = load_allow(str(DATA / "allow.txt"))

    def test_the_trigger_blocklist_actually_fires(self):
        # Non-vacuity control. If this ever fails, every assertFalse in
        # this class has quietly stopped testing anything.
        for term in self.TRIGGERS:
            with self.subTest(term=term):
                self.assertTrue(
                    contains_blocked(f"you are a {term} imo", self.blocklist,
                                     self.allow))

    def test_no_real_word_is_blocked(self):
        for word in self.CORPUS:
            with self.subTest(word=word):
                self.assertFalse(
                    contains_blocked(word, self.blocklist, self.allow),
                    f"{word!r} was blocked -- this is the Scunthorpe bug",
                )

    def test_corpus_words_pass_inside_sentences(self):
        for word in self.CORPUS:
            with self.subTest(word=word):
                self.assertFalse(
                    contains_blocked(
                        f"hello, my name is {word} and I like your site",
                        self.blocklist,
                        self.allow,
                    )
                )

    def test_corpus_survives_without_the_allowlist_too(self):
        # These words are protected by the substr_minlen rule, not by
        # allow.txt. Proving that keeps the allowlist from masking a
        # broken length guard.
        for word in self.CORPUS:
            with self.subTest(word=word):
                self.assertFalse(
                    contains_blocked(word, self.blocklist, NO_ALLOW))


class TestProperties(unittest.TestCase):
    """Invariants over generated input, not hand-picked examples."""

    # No 'z' and no 'q', so generated filler can never spell a fake term.
    ALPHABET = "abcdefghijklmnoprstuvwxy"
    SEPARATORS = " .-_*'​·"

    def _rng(self):
        return random.Random(20260820)

    def _filler(self, rng, words=4):
        return " ".join(
            "".join(rng.choice(self.ALPHABET)
                    for _ in range(rng.randint(1, 12)))
            for _ in range(words)
        )

    def test_generated_clean_text_is_never_blocked(self):
        rng = self._rng()
        blocklist = _blocklist()
        for _ in range(400):
            text = self._filler(rng)
            with self.subTest(text=text):
                self.assertFalse(contains_blocked(text, blocklist, NO_ALLOW))

    def test_a_term_dropped_into_generated_text_is_always_blocked(self):
        rng = self._rng()
        blocklist = _blocklist()
        for _ in range(400):
            term = rng.choice(BLOCKED_TERMS)
            text = f"{self._filler(rng, 2)} {term} {self._filler(rng, 2)}"
            with self.subTest(text=text):
                self.assertTrue(contains_blocked(text, blocklist, NO_ALLOW))

    def test_separator_evasion_never_works_for_substring_length_terms(self):
        rng = self._rng()
        blocklist = _blocklist()
        long_terms = [t for t in BLOCKED_TERMS if len(t) >= 5]
        for _ in range(400):
            term = rng.choice(long_terms)
            broken = "".join(
                char + rng.choice(self.SEPARATORS) for char in term)
            text = f"{self._filler(rng, 2)} {broken} done"
            with self.subTest(text=text):
                self.assertTrue(contains_blocked(text, blocklist, NO_ALLOW))

    def test_more_digests_can_only_block_more(self):
        rng = self._rng()
        full = _blocklist()
        for _ in range(200):
            subset = frozenset(
                digest(t) for t in BLOCKED_TERMS if rng.random() < 0.5)
            partial = Blocklist(subset, MINLEN, MAXLEN, 5)
            term = rng.choice(BLOCKED_TERMS)
            text = f"{self._filler(rng, 2)} {term} tail"
            with self.subTest(text=text):
                if contains_blocked(text, partial, NO_ALLOW):
                    self.assertTrue(
                        contains_blocked(text, full, NO_ALLOW))

    def test_allowlisting_the_only_word_always_clears_it(self):
        rng = self._rng()
        blocklist = _blocklist()
        for _ in range(200):
            term = rng.choice(BLOCKED_TERMS)
            safe = term + "".join(
                rng.choice(self.ALPHABET) for _ in range(rng.randint(1, 6)))
            allow = frozenset({safe})
            with self.subTest(safe=safe):
                self.assertFalse(
                    contains_blocked(f"hello {safe} there", blocklist, allow))


class TestHashTermsScript(unittest.TestCase):
    """scripts/hash_terms.py. The owner runs it once; it has to be right."""

    def _tmpdir(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return Path(holder.name)

    def _run(self, *argv):
        original = sys.argv
        sys.argv = ["hash_terms.py", *argv]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return hash_terms.main()
        finally:
            sys.argv = original

    def test_writes_digests_and_a_header(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("# a comment\nzqs\n\nZQBLOCKED\nzqhate\n",
                          encoding="utf-8")
        dest = tmp / "blocked.txt"

        self.assertEqual(self._run(str(source), str(dest)), 0)

        result = load_blocked(str(dest))
        self.assertEqual(result.minlen, 3)
        self.assertEqual(result.maxlen, 9)
        self.assertEqual(result.substr_minlen, 5)
        self.assertEqual(
            result.digests,
            frozenset(digest(t) for t in ("zqs", "zqblocked", "zqhate")),
        )

    def test_output_round_trips_through_the_matcher(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("zqblocked\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))

        blocklist = load_blocked(str(dest))
        self.assertTrue(
            contains_blocked("z q b l o c k e d", blocklist, NO_ALLOW))
        self.assertFalse(
            contains_blocked("hello there", blocklist, NO_ALLOW))

    def test_output_carries_no_plaintext(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("zqblocked\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        self.assertNotIn("zqblocked", dest.read_text(encoding="utf-8"))

    def test_deduplicates_terms_that_normalize_together(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("zqhate\nZQHATE\nzqhàte\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        self.assertEqual(load_blocked(str(dest)).digests,
                         frozenset({digest("zqhate")}))

    def test_refuses_a_source_inside_the_repo(self):
        # A real, readable in-repo file: if the guard were gone this would
        # succeed and write digests, which is exactly the accident the
        # guard exists to prevent.
        dest = self._tmpdir() / "blocked.txt"
        self.assertEqual(self._run(str(DATA / "allow.txt"), str(dest)), 1)
        self.assertFalse(dest.exists())

    def test_refuses_a_source_inside_the_repo_before_touching_disk(self):
        dest = self._tmpdir() / "blocked.txt"
        inside = REPO_ROOT / "definitely-not-committed-terms.txt"
        self.assertEqual(self._run(str(inside), str(dest)), 1)
        self.assertFalse(dest.exists())
        self.assertFalse(inside.exists())

    def test_refuses_an_unreadable_source(self):
        tmp = self._tmpdir()
        dest = tmp / "blocked.txt"
        self.assertEqual(self._run(str(tmp / "missing.txt"), str(dest)), 1)
        self.assertFalse(dest.exists())

    def test_refuses_a_source_that_is_a_directory(self):
        tmp = self._tmpdir()
        dest = tmp / "blocked.txt"
        self.assertEqual(self._run(str(tmp), str(dest)), 1)
        self.assertFalse(dest.exists())

    def test_refuses_an_empty_source(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("# only comments\n\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self.assertEqual(self._run(str(source), str(dest)), 1)
        self.assertFalse(dest.exists())

    def test_refuses_the_wrong_argument_count(self):
        self.assertEqual(self._run("only-one"), 2)
        self.assertEqual(self._run("a", "b", "c"), 2)

    def test_header_lengths_describe_the_canonical_term(self):
        # The 'fi' ligature is one character on disk and two once folded,
        # so 'zq<fi>le' is 5 raw and 6 canonical. A header measured off
        # the raw term would say maxlen=5, and the substring pass would
        # never scan the six characters the digest actually covers -- the
        # term would be in the file and unmatchable.
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("zq\ufb01le\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        result = load_blocked(str(dest))
        self.assertEqual((result.minlen, result.maxlen), (6, 6))
        self.assertEqual(result.digests, frozenset({digest("zqfile")}))
        self.assertTrue(contains_blocked("xxzqfilexx", result, NO_ALLOW))

    def test_canonicalizes_a_multi_word_term(self):
        # Stored punctuated, a two-word term is a digest nothing can
        # match: the matcher compares alphanumeric runs on both sides.
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("go-away now\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))

        blocklist = load_blocked(str(dest))
        self.assertEqual(blocklist.digests, frozenset({digest("goawaynow")}))
        self.assertTrue(
            contains_blocked("please go away now", blocklist, NO_ALLOW))

    def test_drops_a_term_that_canonicalizes_to_nothing(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("---\nzqhate\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        result = load_blocked(str(dest))
        self.assertEqual(result.digests, frozenset({digest("zqhate")}))
        self.assertEqual(result.minlen, 6)

    def test_tolerates_a_byte_order_mark_in_the_source(self):
        # A BOM would otherwise hide the leading '#' and turn the comment
        # itself into a term.
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("﻿# terms, one per line\nzqhate\n",
                          encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        self.assertEqual(load_blocked(str(dest)).digests,
                         frozenset({digest("zqhate")}))

    def test_header_matches_the_real_term_lengths(self):
        tmp = self._tmpdir()
        source = tmp / "terms.txt"
        source.write_text("abcd\nabcdefghijkl\n", encoding="utf-8")
        dest = tmp / "blocked.txt"
        self._run(str(source), str(dest))
        header = dest.read_text(encoding="utf-8").splitlines()[0]
        self.assertRegex(header, r"^# minlen=4 maxlen=12 substr_minlen=5$")

    def test_shipped_blocked_file_matches_the_tool_format(self):
        lines = (DATA / "blocked.txt").read_text(
            encoding="utf-8").splitlines()
        self.assertRegex(
            lines[0], r"^# minlen=\d+ maxlen=\d+ substr_minlen=\d+$")
        self.assertTrue(
            any(re.search(r"hash_terms\.py", line) for line in lines[:3]))


if __name__ == "__main__":
    unittest.main()
