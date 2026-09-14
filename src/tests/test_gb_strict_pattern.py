"""Guards the strict-by-pattern rule that keeps parallel tasks conflict-free.

If this breaks, every guestbook module silently loses its gate.
"""
import unittest

from scripts.run_tests import STRICT_PREFIX, is_strict_module


class TestStrictPattern(unittest.TestCase):
    def test_gb_prefix_is_strict(self):
        self.assertTrue(is_strict_module("test_gb_normalize"))

    def test_legacy_named_module_is_not_strict_by_pattern(self):
        self.assertFalse(is_strict_module("test_textnode"))

    def test_prefix_constant_is_the_documented_one(self):
        self.assertEqual(STRICT_PREFIX, "test_gb_")

    def test_partial_prefix_does_not_match(self):
        self.assertFalse(is_strict_module("test_gb"))

    def test_prefix_must_be_at_the_start(self):
        self.assertFalse(is_strict_module("legacy_test_gb_thing"))
