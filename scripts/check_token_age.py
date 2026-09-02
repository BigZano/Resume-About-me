#!/usr/bin/env python3
"""Report how much life the Spotify refresh token has left.

Pure date arithmetic — no network. Spotify refresh tokens live 6 months
from authorization, and refreshing does not extend that clock, so this is
the one failure mode the pipeline cannot heal on its own.

Reads SPOTIFY_AUTH_DATE (YYYY-MM-DD). Writes `status` and `days` to
$GITHUB_OUTPUT for the workflow to act on. Always exits 0 — deciding
whether to fail the job belongs to the workflow, not here.
"""
import os
import sys
from datetime import UTC, date, datetime

REFRESH_TOKEN_LIFETIME_DAYS = 180
WARN_THRESHOLD_DAYS = 30


def parse_iso_date(value):
    """Parse a YYYY-MM-DD string into a date.

    Raises ValueError with an actionable message on anything else.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SPOTIFY_AUTH_DATE is empty or unset")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"SPOTIFY_AUTH_DATE must be YYYY-MM-DD, got {value!r}"
        ) from exc


def days_until_expiry(auth_date, today):
    """Days remaining before the refresh token expires.

    Zero means it expires today; negative means it already has. `today` is
    a parameter so this stays testable without mocking the clock.
    """
    if auth_date > today:
        raise ValueError(
            f"auth_date {auth_date} is in the future relative to {today}"
        )
    return REFRESH_TOKEN_LIFETIME_DAYS - (today - auth_date).days


def classify(days):
    """Bucket a remaining-days count into OK / WARN / EXPIRED."""
    if days <= 0:
        return "EXPIRED"
    if days <= WARN_THRESHOLD_DAYS:
        return "WARN"
    return "OK"


def main():
    try:
        auth_date = parse_iso_date(os.environ.get("SPOTIFY_AUTH_DATE", ""))
        # date.today() reads the system's local clock; pin to UTC explicitly
        # so this agrees with the GitHub Actions runner regardless of where
        # it's invoked from.
        days = days_until_expiry(auth_date, datetime.now(UTC).date())
    except ValueError as exc:
        # A missing or broken date is itself a maintenance problem, so
        # surface it through the same channel as a real expiry.
        print(f"check_token_age: {exc}", file=sys.stderr)
        status, days = "EXPIRED", 0
    else:
        status = classify(days)
        print(f"check_token_age: {days} days remaining ({status})")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"status={status}\n")
            handle.write(f"days={days}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
