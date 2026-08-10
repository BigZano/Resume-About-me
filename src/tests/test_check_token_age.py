import unittest
from datetime import date

from check_token_age import (
    REFRESH_TOKEN_LIFETIME_DAYS,
    WARN_THRESHOLD_DAYS,
    classify,
    days_until_expiry,
    parse_iso_date,
)


class TestDaysUntilExpiry(unittest.TestCase):
    def test_same_day_gives_full_lifetime(self):
        d = date(2026, 8, 9)
        self.assertEqual(
            days_until_expiry(d, d), REFRESH_TOKEN_LIFETIME_DAYS
        )

    def test_one_day_elapsed(self):
        self.assertEqual(
            days_until_expiry(date(2026, 8, 9), date(2026, 8, 10)),
            REFRESH_TOKEN_LIFETIME_DAYS - 1,
        )

    def test_exact_expiry_is_zero(self):
        auth = date(2026, 8, 9)
        today = date(2027, 2, 5)  # 180 days later
        self.assertEqual((today - auth).days, 180)
        self.assertEqual(days_until_expiry(auth, today), 0)

    def test_past_expiry_is_negative(self):
        self.assertEqual(
            days_until_expiry(date(2026, 8, 9), date(2027, 2, 6)), -1
        )

    def test_spans_a_leap_day(self):
        # 2028 is a leap year; rely on date arithmetic, not 365-day math.
        auth = date(2028, 1, 1)
        today = date(2028, 3, 1)
        self.assertEqual((today - auth).days, 60)
        self.assertEqual(
            days_until_expiry(auth, today), REFRESH_TOKEN_LIFETIME_DAYS - 60
        )

    def test_future_auth_date_raises(self):
        with self.assertRaises(ValueError):
            days_until_expiry(date(2026, 8, 10), date(2026, 8, 9))

    def test_strictly_decreasing_as_today_advances(self):
        from datetime import timedelta
        auth = date(2026, 8, 9)
        previous = None
        for offset in range(0, 200, 7):
            current = days_until_expiry(auth, auth + timedelta(days=offset))
            if previous is not None:
                self.assertLess(current, previous)
            previous = current


class TestClassify(unittest.TestCase):
    def test_well_above_threshold_is_ok(self):
        self.assertEqual(classify(180), "OK")

    def test_one_past_threshold_is_ok(self):
        self.assertEqual(classify(WARN_THRESHOLD_DAYS + 1), "OK")

    def test_exactly_threshold_warns(self):
        self.assertEqual(classify(WARN_THRESHOLD_DAYS), "WARN")

    def test_one_day_left_warns(self):
        self.assertEqual(classify(1), "WARN")

    def test_zero_is_expired(self):
        self.assertEqual(classify(0), "EXPIRED")

    def test_negative_is_expired(self):
        self.assertEqual(classify(-40), "EXPIRED")


class TestParseIsoDate(unittest.TestCase):
    def test_parses_valid(self):
        self.assertEqual(parse_iso_date("2026-08-09"), date(2026, 8, 9))

    def test_tolerates_surrounding_whitespace(self):
        self.assertEqual(parse_iso_date("  2026-08-09 "), date(2026, 8, 9))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_iso_date("")

    def test_rejects_non_iso_format(self):
        with self.assertRaises(ValueError):
            parse_iso_date("08/09/2026")

    def test_rejects_impossible_date(self):
        with self.assertRaises(ValueError):
            parse_iso_date("2026-02-30")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_iso_date("not-a-date")


if __name__ == "__main__":
    unittest.main()
