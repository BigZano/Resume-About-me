# Spotify Listening Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `Listening` placeholders on the landing page with the user's real top-10 Spotify tracks, refreshed weekly by a GitHub Action.

**Architecture:** A weekly Action refreshes an OAuth access token, fetches top tracks, and writes `content/listening.json`. That committed JSON file is the only seam between "talks to Spotify" and "makes HTML" — the build reads it and renders markup, and a fresh clone builds fine without any secrets. A separate pure-date-math script opens a GitHub issue 30 days before the refresh token's hard 6-month expiry.

**Tech Stack:** Python 3.12+ standard library only (`urllib`, `json`, `html`, `base64`, `http.server`, `unittest`). GitHub Actions with preinstalled `gh`. No third-party packages anywhere.

**Spec:** `specs/2026-08-09-spotify-listening-design.md` — read it before starting.

## Global Constraints

- **Python 3.12+, standard library only.** Adding any runtime dependency is a plan violation. `pyproject.toml` declares `dependencies = []` and this must stay true.
- **Never hand-edit `docs/`.** `src/main.py:49` runs `shutil.rmtree(docs_path)` every build. Anything written there is destroyed silently.
- **The build must never fail because of Listening data.** A fresh clone with no `content/listening.json` must still produce a working page.
- **All external strings pass through `html.escape()`** before entering markup.
- **Never overwrite good data with worse data.** A zero-track or malformed response must not blank the page.
- **Plans and specs live in `plans/` and `specs/` at repo root**, never under `docs/`.
- Redirect URI is exactly `http://127.0.0.1:7777/callback` (registered). Port 7777, not 8888 — `scripts/main.sh` uses 8888.
- Scopes are exactly: `user-top-read user-read-currently-playing user-read-recently-played`.
- Secret names: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`. Variable name: `SPOTIFY_AUTH_DATE`.
- Commit after every task. Small commits.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `scripts/run_tests.py` | Create (T1) | Discover + run suite, gate on baseline, enforce strict-green modules |
| `test.sh` | Modify (T1) | Thin wrapper with interpreter detection |
| `scripts/spotify_auth.py` | Create (T2) | One-time OAuth. Standalone — stdlib, no `src/` imports |
| `scripts/check_token_age.py` | Create (T3) | Pure date math + GitHub output. No network |
| `src/Gen_Content/render_listening.py` | Create (T4) | JSON → markup. No network, no Spotify knowledge |
| `titlepage.html` | Modify (T5) | Add `{{ ListeningTracks }}` / `{{ ListeningStamp }}` |
| `static/landing.css` | Modify (T5) | Bound sticky card height so 10 tracks don't overflow |
| `src/Gen_Content/generate_landing_page.py` | Modify (T5) | Two `.replace()` calls in the existing chain |
| `scripts/fetch_listening.py` | Create (T6, T7) | Spotify → validated JSON. Never sees HTML |
| `.github/workflows/listening.yml` | Create (T8) | Weekly cron orchestration |

**Test files:** `src/tests/test_check_token_age.py`, `src/tests/test_render_listening.py`, `src/tests/test_fetch_listening.py`

---

## Task 1: Repair the test harness and record the baseline

The runner is broken two ways: `test.sh` calls `python` (this host has only `python3`, exit 127), and `unittest discover -s src` finds zero tests because `src/tests/` is not an importable package. The 9 existing test files are stale and half-failing — **do not fix them**, that is explicitly out of scope. Instead, record their current state so "no new failures" becomes checkable.

**Files:**
- Create: `scripts/run_tests.py`
- Modify: `test.sh`

**Interfaces:**
- Consumes: nothing
- Produces: `./test.sh` exits 0 when the suite matches baseline, non-zero when it regresses. Later tasks append their module name to `STRICT` in `scripts/run_tests.py`.

- [ ] **Step 1: Confirm the baseline yourself**

Run:
```bash
PYTHONPATH=src python3 -m unittest discover -s src/tests -t src/tests 2>&1 | tail -3
```
Expected: `Ran 39 tests` … `FAILED (failures=11, errors=9)`

If those numbers differ, use *your* measured numbers in Step 2 and note the discrepancy in the commit message. Do not "fix" the stale tests to make them match.

- [ ] **Step 2: Write the runner**

Create `scripts/run_tests.py`:

```python
#!/usr/bin/env python3
"""Run the unittest suite and gate on a recorded baseline.

The suite carries pre-existing failures unrelated to current work (see
specs/2026-08-09-spotify-listening-design.md section 12). Fixing them is a
separate cleanup. This runner therefore enforces two independent rules:

  1. No NEW failures: total failures/errors must not exceed BASELINE.
  2. Modules listed in STRICT must be 100% green, no baseline forgiveness.

New work always goes in STRICT. Only the stale legacy tests get baseline
forgiveness.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "src" / "tests"

# Measured 2026-08-09 against the stale pre-existing suite.
BASELINE_FAILURES = 11
BASELINE_ERRORS = 9

# Modules that must be fully green. Each new task appends its module here.
STRICT: tuple[str, ...] = ()


def _discover(pattern="test*.py"):
    return unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR),
        top_level_dir=str(TESTS_DIR),
        pattern=pattern,
    )


def main():
    # src/ for Gen_Content.*, scripts/ for the fetch and token modules.
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

    runner = unittest.TextTestRunner(verbosity=2)
    strict_ok = True

    for name in STRICT:
        suite = _discover(f"{name}.py")
        if suite.countTestCases() == 0:
            print(f"ERROR: strict module {name!r} contributed zero tests")
            strict_ok = False
            continue
        if not runner.run(suite).wasSuccessful():
            strict_ok = False

    full = runner.run(_discover())
    failures, errors = len(full.failures), len(full.errors)

    print(f"\nfull suite: {full.testsRun} run, "
          f"{failures} failures, {errors} errors")
    print(f"baseline:   {BASELINE_FAILURES} failures, "
          f"{BASELINE_ERRORS} errors")

    regressed = failures > BASELINE_FAILURES or errors > BASELINE_ERRORS
    if regressed:
        print("FAIL: new failures relative to recorded baseline")
    if not strict_ok:
        print("FAIL: strict modules must be fully green")

    return 1 if (regressed or not strict_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Rewrite `test.sh`**

Replace the entire contents of `test.sh`. Interpreter detection mirrors `build.sh` exactly:

```bash
#!/usr/bin/env bash

set -euo pipefail

# Always run from the repository root, regardless of caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer python3, but fall back to python for environments that only ship one name.
if command -v python3 >/dev/null 2>&1; then
	PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
	PYTHON_BIN="python"
else
	echo "ERROR: Could not find python3 or python in PATH." >&2
	exit 1
fi

exec "$PYTHON_BIN" scripts/run_tests.py "$@"
```

- [ ] **Step 4: Verify it passes at baseline**

Run: `./test.sh; echo "exit=$?"`
Expected: the stale failures still print, then `exit=0` — because the counts match baseline exactly.

- [ ] **Step 5: Verify the gate actually catches regressions**

Temporarily lower the baseline to prove the gate isn't vacuous:

```bash
sed -i 's/BASELINE_FAILURES = 11/BASELINE_FAILURES = 10/' scripts/run_tests.py
./test.sh; echo "exit=$?"
```
Expected: `FAIL: new failures relative to recorded baseline`, `exit=1`

Then restore it:
```bash
sed -i 's/BASELINE_FAILURES = 10/BASELINE_FAILURES = 11/' scripts/run_tests.py
./test.sh; echo "exit=$?"
```
Expected: `exit=0`

A gate you never watched fail is not a gate.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_tests.py test.sh
git commit -m "Repair test runner and record the stale-suite baseline

test.sh called python (this host has only python3) and discovery found
zero tests because src/tests is not an importable package. Both fixed.

The 9 pre-existing test files remain stale and half-failing; that cleanup
is out of scope. Their current state (39 run / 11 failures / 9 errors) is
recorded as a baseline so new failures are detectable, while new modules
listed in STRICT must be fully green."
```

---

## Task 2: One-time authorization script

Standalone by design: stdlib only, **no imports from `src/`**, so it can be copied to any machine with a browser and run without a checkout. Do this task early — the user needs the refresh token before anything downstream can be verified end to end.

**Files:**
- Create: `scripts/spotify_auth.py`

**Interfaces:**
- Consumes: nothing
- Produces: a refresh token printed to stdout, pasted by hand into the `SPOTIFY_REFRESH_TOKEN` secret. Defines `SCOPES` and `REDIRECT_URI` constants that `fetch_listening.py` must stay consistent with.

- [ ] **Step 1: Write the script**

Create `scripts/spotify_auth.py`:

```python
#!/usr/bin/env python3
"""One-time Spotify authorization. Prints a refresh token.

Standalone on purpose: standard library only, no imports from src/, so it
can be copied to any machine and run without a repository checkout.

Two supported ways to run, both the same code path:

  * On a machine with a browser (e.g. the Windows box) — the browser opens
    automatically and the callback is caught locally.

  * On a headless host, under an SSH tunnel:
        ssh -L 7777:localhost:7777 you@host
        python3 scripts/spotify_auth.py
    The tunnel makes the local browser's 127.0.0.1:7777 reach this
    listener; the socket is indistinguishable. webbrowser.open() silently
    no-ops, so use the URL printed below.

Credentials are read from the environment or prompted for interactively.
They are never written to disk.

Afterwards:
  1. Paste the refresh token into the repository secret SPOTIFY_REFRESH_TOKEN
  2. Set the repository variable SPOTIFY_AUTH_DATE to today (YYYY-MM-DD)

The refresh token expires 6 months from today. That clock cannot be
extended by refreshing.
"""
import base64
import getpass
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PORT = 7777
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-top-read user-read-currently-playing user-read-recently-played"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

_result = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (params.get("code") or [None])[0]
        _result["state"] = (params.get("state") or [None])[0]
        _result["error"] = (params.get("error") or [None])[0]

        body = b"Authorization received. You can close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal clean


def _credential(name, prompt, secret=False):
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        value = getpass.getpass(prompt) if secret else input(prompt)
    except EOFError:
        return ""  # non-interactive stdin; caller reports it cleanly
    return value.strip()


def _serve_until_answered(server):
    """Handle requests until the callback lands.

    Browsers often request /favicon.ico first. A single handle_request()
    would be consumed by that and never see the real callback, so loop
    until the handler actually records a code or an error.
    """
    while not ("code" in _result or "error" in _result):
        server.handle_request()


def build_auth_url(client_id, state):
    """Assemble the Spotify authorize URL. Pure — used by tests."""
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    return f"{AUTH_URL}?{query}"


def exchange_code(client_id, client_secret, code):
    """Trade an authorization code for tokens. Returns the parsed payload."""
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"Token exchange failed ({exc.code}): {detail}\n"
            "The most common causes are a redirect URI that does not exactly "
            "match the dashboard, or an authorization code that expired "
            "while it sat unused."
        ) from exc


def main():
    client_id = _credential("SPOTIFY_CLIENT_ID", "Client ID: ")
    client_secret = _credential(
        "SPOTIFY_CLIENT_SECRET", "Client secret (hidden): ", secret=True
    )
    if not client_id or not client_secret:
        raise SystemExit("Both a client ID and a client secret are required.")

    state = secrets.token_urlsafe(16)
    url = build_auth_url(client_id, state)

    server = http.server.HTTPServer(("127.0.0.1", PORT), _CallbackHandler)
    threading.Thread(
        target=_serve_until_answered, args=(server,), daemon=True
    ).start()

    print("\nOpen this URL in a browser and approve access:\n")
    print(f"  {url}\n")
    print(f"Waiting for the redirect to {REDIRECT_URI} ...")
    webbrowser.open(url)  # no-ops harmlessly on a headless host

    deadline = time.monotonic() + 300
    while not _result and time.monotonic() < deadline:
        time.sleep(1)

    if not _result:
        raise SystemExit(
            "Timed out waiting for the callback. Authorization codes are "
            "short-lived, so just rerun the script."
        )
    if _result.get("error"):
        raise SystemExit(f"Spotify returned an error: {_result['error']}")
    if _result.get("state") != state:
        raise SystemExit(
            "State mismatch — the response did not come from the request "
            "this script started. Aborting."
        )
    code = _result.get("code")
    if not code:
        raise SystemExit("Callback carried no authorization code.")

    payload = exchange_code(client_id, client_secret, code)
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise SystemExit(f"No refresh_token in the response: {payload}")

    granted = payload.get("scope", "")
    print("\n" + "=" * 68)
    print("REFRESH TOKEN (paste into the SPOTIFY_REFRESH_TOKEN secret):\n")
    print(refresh_token)
    print("\nGranted scopes:", granted or "(none reported)")
    print("\nAlso set the repository variable SPOTIFY_AUTH_DATE to today.")
    print("This token expires 6 months from today; refreshing does not "
          "extend that.")
    print("=" * 68)

    for required in SCOPES.split():
        if required not in granted.split():
            print(f"WARNING: scope {required!r} was not granted.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it fails cleanly with no credentials**

Run: `SPOTIFY_CLIENT_ID= SPOTIFY_CLIENT_SECRET= python3 scripts/spotify_auth.py < /dev/null; echo "exit=$?"`
Expected: `Both a client ID and a client secret are required.` and `exit=1`.

Specifically **not** an `EOFError` traceback — with empty env vars the script
falls through to prompting, and prompting against `/dev/null` raises EOF. That
is why `_credential` catches it and returns an empty string.

- [ ] **Step 3: Verify the auth URL is well-formed**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from spotify_auth import build_auth_url, REDIRECT_URI, SCOPES
u = build_auth_url('abc123', 'st4te')
assert 'response_type=code' in u, u
assert 'client_id=abc123' in u, u
assert '127.0.0.1%3A7777%2Fcallback' in u, u
assert 'user-top-read' in u, u
assert 'state=st4te' in u, u
print('OK'); print(u)
"
```
Expected: `OK`, then the full URL. Confirm by eye that the redirect URI is the 7777 one.

- [ ] **Step 4: Commit**

```bash
git add scripts/spotify_auth.py
git commit -m "Add one-time Spotify authorization script

Standalone: stdlib only, no src/ imports, so it runs on any machine with
a browser or on the headless host under ssh -L 7777:localhost:7777.

Uses Authorization Code with a client secret rather than PKCE, because
PKCE rotates the refresh token and would invalidate the stored secret.
Validates the state parameter and warns if any requested scope was not
granted."
```

- [ ] **Step 5: HUMAN STEP — run it and store the results**

This step is the user's, not the agent's. Stop and hand off:

1. Run `python3 scripts/spotify_auth.py` (on the Windows box, or here under `ssh -L 7777:localhost:7777`).
2. Approve in the browser. Federated Facebook login is fine and changes nothing.
3. Paste the printed token into repository secret `SPOTIFY_REFRESH_TOKEN`.
4. Set repository variable `SPOTIFY_AUTH_DATE` to today's date, `YYYY-MM-DD`.

Tasks 3–7 do not depend on this and can proceed in parallel. Only Task 8's live run needs it.

---

## Task 3: Token age check

Pure date arithmetic. `today` is a parameter, never `datetime.date.today()` inside the function under test — that is what makes this testable without clock mocking.

**Files:**
- Create: `scripts/check_token_age.py`
- Test: `src/tests/test_check_token_age.py`
- Modify: `scripts/run_tests.py` (add to `STRICT`)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `days_until_expiry(auth_date: date, today: date) -> int`
  - `classify(days: int) -> str` returning `"OK"` / `"WARN"` / `"EXPIRED"`
  - `parse_iso_date(value: str) -> date`
  - Constants `REFRESH_TOKEN_LIFETIME_DAYS = 180`, `WARN_THRESHOLD_DAYS = 30`
  - CLI writes `status=` and `days=` to `$GITHUB_OUTPUT`; always exits 0

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_check_token_age.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_check_token_age.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_token_age'`

- [ ] **Step 3: Write the implementation**

Create `scripts/check_token_age.py`:

```python
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
from datetime import date

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
        days = days_until_expiry(auth_date, date.today())
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_check_token_age.py" -v`
Expected: PASS, 19 tests

- [ ] **Step 5: Add the module to the strict list**

In `scripts/run_tests.py`, change:
```python
STRICT: tuple[str, ...] = ()
```
to:
```python
STRICT: tuple[str, ...] = ("test_check_token_age",)
```

- [ ] **Step 6: Verify the whole gate is still green**

Run: `./test.sh; echo "exit=$?"`
Expected: `exit=0`, with `test_check_token_age` reported fully green and the full suite still at baseline.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_token_age.py src/tests/test_check_token_age.py scripts/run_tests.py
git commit -m "Add refresh-token expiry check

Spotify refresh tokens live 6 months from authorization and refreshing
does not extend that, so expiry needs proactive warning rather than
discovery-by-breakage.

days_until_expiry takes today as a parameter, so the boundary cases
(day 30 vs 31, exact expiry, already expired, leap-year spans) are
testable without mocking a clock. Always exits 0; the workflow decides
what to do with the status."
```

---

## Task 4: Render tracks to markup

Pure transformation. No file I/O in the function under test, no network, no Spotify knowledge — this module only understands a dict shape and HTML.

**Files:**
- Create: `src/Gen_Content/render_listening.py`
- Test: `src/tests/test_render_listening.py`
- Modify: `scripts/run_tests.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `render_listening(data: dict | None) -> tuple[str, str]` returning `(tracks_html, stamp)`
  - `load_listening(path) -> tuple[dict | None, str | None]` returning `(data, warning)`
  - Constants `STAMP_LIVE = "on repeat this month"`, `STAMP_EMPTY = "not yet live"`
  - Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_render_listening.py`:

```python
import json
import os
import tempfile
import unittest

from Gen_Content.render_listening import (
    STAMP_EMPTY,
    STAMP_LIVE,
    load_listening,
    render_listening,
)


def _data(*pairs):
    return {"tracks": [{"artist": a, "title": t} for a, t in pairs]}


class TestRenderListening(unittest.TestCase):
    def test_renders_one_track(self):
        html, stamp = render_listening(_data(("Tech N9ne", "Speedom")))
        self.assertIn("<span>Tech N9ne</span> Speedom", html)
        self.assertEqual(stamp, STAMP_LIVE)

    def test_renders_every_track_in_order(self):
        html, _ = render_listening(
            _data(("A", "One"), ("B", "Two"), ("C", "Three"))
        )
        self.assertEqual(html.count("<li>"), 3)
        self.assertLess(html.index("One"), html.index("Two"))
        self.assertLess(html.index("Two"), html.index("Three"))

    def test_none_gives_empty_state(self):
        html, stamp = render_listening(None)
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_empty_track_list_gives_empty_state(self):
        html, stamp = render_listening({"tracks": []})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_missing_tracks_key_gives_empty_state(self):
        html, stamp = render_listening({"fetched_at": "2026-08-09T00:00:00Z"})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_tracks_not_a_list_gives_empty_state(self):
        html, stamp = render_listening({"tracks": "Speedom"})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)

    def test_non_dict_input_gives_empty_state(self):
        for bad in ["string", 42, [], True]:
            with self.subTest(bad=bad):
                html, stamp = render_listening(bad)
                self.assertIn("Nothing logged yet", html)
                self.assertEqual(stamp, STAMP_EMPTY)

    def test_skips_malformed_entries_but_keeps_good_ones(self):
        data = {"tracks": [
            {"artist": "Good", "title": "Song"},
            "not a dict",
            {"artist": "", "title": ""},
            {"no": "keys"},
        ]}
        html, stamp = render_listening(data)
        self.assertEqual(html.count("<li>"), 1)
        self.assertIn("Good", html)
        self.assertEqual(stamp, STAMP_LIVE)

    def test_all_entries_malformed_gives_empty_state(self):
        html, stamp = render_listening({"tracks": ["x", 1, {}]})
        self.assertIn("Nothing logged yet", html)
        self.assertEqual(stamp, STAMP_EMPTY)


class TestEscaping(unittest.TestCase):
    def test_ampersand_is_escaped(self):
        html, _ = render_listening(_data(("Simon & Garfunkel", "The Boxer")))
        self.assertIn("Simon &amp; Garfunkel", html)
        self.assertNotIn("Simon & Garfunkel", html)

    def test_angle_brackets_are_escaped(self):
        html, _ = render_listening(_data(("<script>", "</script>")))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_input_can_inject_a_raw_tag(self):
        """Property: no supplied text ever reaches output as live markup."""
        hostile = [
            '<img src=x onerror=alert(1)>',
            '"><script>alert(1)</script>',
            "' onmouseover='alert(1)",
            "</span></li><li>injected",
            "&<>\"'",
        ]
        for payload in hostile:
            with self.subTest(payload=payload):
                html, _ = render_listening(_data((payload, payload)))
                # Strip the markup this module legitimately emits, then
                # assert nothing tag-like survives from the input.
                residue = (
                    html.replace("<li>", "")
                    .replace("</li>", "")
                    .replace("<span>", "")
                    .replace("</span>", "")
                )
                self.assertNotIn("<", residue)
                self.assertNotIn(">", residue)

    def test_unicode_and_emoji_survive_intact(self):
        html, _ = render_listening(_data(("Sigur Rós", "Hoppípolla 🎵")))
        self.assertIn("Sigur Rós", html)
        self.assertIn("Hoppípolla 🎵", html)

    def test_whitespace_is_trimmed(self):
        html, _ = render_listening(_data(("  Spaced  ", "  Out  ")))
        self.assertIn("<span>Spaced</span> Out", html)


class TestLoadListening(unittest.TestCase):
    def test_missing_file_is_silent(self):
        data, warning = load_listening("/nonexistent/listening.json")
        self.assertIsNone(data)
        self.assertIsNone(warning)

    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "listening.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(_data(("A", "B")), handle)
            data, warning = load_listening(path)
            self.assertIsNone(warning)
            self.assertEqual(data["tracks"][0]["artist"], "A")

    def test_malformed_json_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "listening.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            data, warning = load_listening(path)
            self.assertIsNone(data)
            self.assertIsNotNone(warning)
            self.assertIn("Warning", warning)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_render_listening.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Gen_Content.render_listening'`

- [ ] **Step 3: Write the implementation**

Create `src/Gen_Content/render_listening.py`:

```python
"""Render Spotify listening data into landing-page markup.

Deliberately knows nothing about Spotify or the network — it reads a dict
with a known shape and emits HTML. content/listening.json is the only
contract between this module and the fetcher.
"""
import html
import json

# Matches the indentation of the surrounding <li> items in titlepage.html.
_INDENT = " " * 16

STAMP_LIVE = "on repeat this month"
STAMP_EMPTY = "not yet live"
EMPTY_TRACKS_HTML = f"{_INDENT}<li>Nothing logged yet</li>"


def _render_track(track):
    """One <li>, or None when the entry has nothing usable in it."""
    if not isinstance(track, dict):
        return None
    artist = str(track.get("artist") or "").strip()
    title = str(track.get("title") or "").strip()
    if not artist and not title:
        return None
    return (
        f"{_INDENT}<li><span>{html.escape(artist)}</span> "
        f"{html.escape(title)}</li>"
    )


def render_listening(data):
    """Return (tracks_html, stamp) for the Listening block.

    Falls back to the empty state for anything unusable, so the build can
    never fail because of listening data.
    """
    if not isinstance(data, dict):
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    rendered = [line for line in (_render_track(t) for t in tracks) if line]
    if not rendered:
        return EMPTY_TRACKS_HTML, STAMP_EMPTY

    return "\n".join(rendered), STAMP_LIVE


def load_listening(path):
    """Read listening.json. Returns (data, warning).

    A missing file is a legitimate state — a fresh clone that has never
    fetched — so it returns (None, None) silently. Malformed content is a
    bug, so it returns a warning for the caller to print.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, f"Warning: could not read {path}: {exc}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_render_listening.py" -v`
Expected: PASS, 20 tests

- [ ] **Step 5: Add to the strict list and verify the gate**

In `scripts/run_tests.py`:
```python
STRICT: tuple[str, ...] = ("test_check_token_age", "test_render_listening")
```

Run: `./test.sh; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 6: Commit**

```bash
git add src/Gen_Content/render_listening.py src/tests/test_render_listening.py scripts/run_tests.py
git commit -m "Add listening data renderer

Pure transformation from the listening.json shape to markup. Knows
nothing about Spotify or the network, which is what lets it be tested
with hand-written dicts and no mocks.

Everything external passes through html.escape() — the realistic threat
is not injection but band names containing & and <, which render wrong
when written raw. Any unusable input degrades to the empty state so the
build can never fail because of listening data."
```

---

## Task 5: Wire the renderer into the build

**Files:**
- Modify: `titlepage.html:109-120`
- Modify: `static/landing.css` (the `body.landing .now` rule at ~line 193)
- Modify: `src/Gen_Content/generate_landing_page.py`

**Interfaces:**
- Consumes: `render_listening`, `load_listening`, `STAMP_EMPTY` from Task 4
- Produces: a landing page whose Listening block comes from `content/listening.json`

- [ ] **Step 1: Update the template**

In `titlepage.html`, replace the placeholder block (the comment plus the hardcoded `<ul>` and stamp) with:

```html
            <section class="now-block">
              <h4>Listening</h4>
              <ul class="now-list now-tracks">
{{ ListeningTracks }}
              </ul>
              <p class="now-stamp">{{ ListeningStamp }}</p>
            </section>
```

The `{{ ListeningTracks }}` placeholder sits at column 0 on its own line; the renderer supplies its own 16-space indentation. Delete the `Listening gets filled by the build once the Spotify pipeline lands` comment — it has landed.

- [ ] **Step 2: Bound the sticky card height**

In `static/landing.css`, the `body.landing .now` rule currently reads:

```css
body.landing .now{
  border:1px solid var(--iron);
  background:var(--soot);
  position:sticky;
  top:2rem;
}
```

Replace it with:

```css
/* 10 tracks at two lines each overflow a sticky card on a laptop
   viewport, which would strand Building and Reading below the fold with
   no way to reach them. Bound the height and let the card scroll. */
body.landing .now{
  border:1px solid var(--iron);
  background:var(--soot);
  position:sticky;
  top:2rem;
  max-height:calc(100vh - 4rem);
  overflow-y:auto;
}
```

Leave `.now-tracks li span{display:block}` alone — the two-line artist-above-track layout and the text-only decision are deliberate and documented in the existing CSS comment.

- [ ] **Step 3: Wire it into the generator**

In `src/Gen_Content/generate_landing_page.py`, add to the imports at the top of the file (after `from pathlib import Path`):

```python
from Gen_Content.render_listening import load_listening, render_listening
```

Then, immediately before the `# Read template` comment (currently line 104), insert:

```python
    # Listening data is optional: a fresh clone has never fetched, and the
    # build must still succeed. See specs/2026-08-09-spotify-listening-design.md
    listening_path = os.path.join(content_path, "listening.json")
    listening_data, listening_warning = load_listening(listening_path)
    if listening_warning:
        print(listening_warning)
    listening_tracks, listening_stamp = render_listening(listening_data)
```

Then extend the existing `.replace()` chain by adding two lines after `.replace("{{ PageLinks }}", page_links)`:

```python
        .replace("{{ ListeningTracks }}", listening_tracks)
        .replace("{{ ListeningStamp }}", listening_stamp)
```

- [ ] **Step 4: Verify the empty state builds**

There is no `content/listening.json` yet, which is exactly the fresh-clone case.

Run: `./build.sh 2>&1 | tail -5 && grep -A3 'now-tracks' docs/index.html`
Expected: build succeeds, and the rendered block shows `<li>Nothing logged yet</li>` with the stamp `not yet live`. No warning printed, because a missing file is legitimate.

- [ ] **Step 5: Verify the populated state**

```bash
cat > content/listening.json <<'JSON'
{
  "fetched_at": "2026-08-09T14:17:03Z",
  "tracks": [
    { "artist": "Tech N9ne", "title": "Speedom" },
    { "artist": "Simon & Garfunkel", "title": "The Boxer" }
  ]
}
JSON
./build.sh > /dev/null 2>&1
grep -A5 'now-tracks' docs/index.html
```
Expected: both tracks render, `Simon &amp; Garfunkel` is escaped, stamp reads `on repeat this month`.

- [ ] **Step 6: Verify malformed input degrades with a warning**

```bash
echo '{not json' > content/listening.json
./build.sh 2>&1 | grep -i warning
grep -A3 'now-tracks' docs/index.html
```
Expected: a `Warning: could not read ...` line, build still exits 0, block shows `Nothing logged yet`.

Then restore the good fixture from Step 5 and rebuild.

- [ ] **Step 7: Run the gate**

Run: `./test.sh; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 8: Commit**

```bash
git add titlepage.html static/landing.css src/Gen_Content/generate_landing_page.py content/listening.json docs/
git commit -m "Render the Listening block from content/listening.json

Follows the existing {{ Placeholder }} convention rather than introducing
a new mechanism. The generator gains two replace() calls; the rendering
itself lives in its own module because generate_landing_page is already
doing four jobs.

Also bounds the sticky Now card's height: 10 two-line entries overflow a
laptop viewport, and a sticky element taller than the viewport strands
its lower content unreachable."
```

---

## Task 6: Parse the Spotify response

Pure parsing, split from the network call so it can be tested against handwritten payloads. This is where the **never overwrite good data with worse data** rule is enforced.

**Files:**
- Create: `scripts/fetch_listening.py` (parsing half only)
- Test: `src/tests/test_fetch_listening.py`
- Modify: `scripts/run_tests.py`

**Interfaces:**
- Consumes: nothing
- Produces: `parse_top_tracks(payload: dict, limit: int = 10) -> list[dict]`, raising `ValueError` on unusable payloads. Task 7 calls it.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_fetch_listening.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_fetch_listening.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_listening'`

- [ ] **Step 3: Write the parsing half**

Create `scripts/fetch_listening.py`:

```python
#!/usr/bin/env python3
"""Fetch top tracks from Spotify into content/listening.json.

Knows nothing about HTML — it writes JSON, and the build renders it. See
specs/2026-08-09-spotify-listening-design.md for the contract.
"""
import json

TRACK_LIMIT = 10
TIME_RANGE = "short_term"  # Spotify's rolling ~4-week ranking


def parse_top_tracks(payload, limit=TRACK_LIMIT):
    """Extract [{'artist', 'title'}] from a Spotify top-tracks response.

    Raises ValueError rather than returning an empty list. An empty return
    would let the caller write a file that blanks the page, and a bad
    response must never be able to destroy good data.
    """
    if not isinstance(payload, dict):
        raise ValueError("top-tracks payload is not a JSON object")

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("top-tracks payload has no 'items' list")

    tracks = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("name")
        if not isinstance(title, str) or not title.strip():
            continue

        artists = item.get("artists")
        if not isinstance(artists, list) or not artists:
            continue
        first = artists[0]
        if not isinstance(first, dict):
            continue
        artist = first.get("name")
        if not isinstance(artist, str) or not artist.strip():
            continue

        tracks.append({"artist": artist.strip(), "title": title.strip()})
        if len(tracks) >= limit:
            break

    if not tracks:
        raise ValueError("top-tracks payload yielded zero usable tracks")
    return tracks
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src:scripts python3 -m unittest discover -s src/tests -t src/tests -p "test_fetch_listening.py" -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Add to the strict list and verify the gate**

In `scripts/run_tests.py`:
```python
STRICT: tuple[str, ...] = (
    "test_check_token_age",
    "test_render_listening",
    "test_fetch_listening",
)
```

Run: `./test.sh; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_listening.py src/tests/test_fetch_listening.py scripts/run_tests.py
git commit -m "Add Spotify top-tracks response parsing

Split from the network call so it is testable against handwritten
payloads with no mocking.

Raises rather than returning an empty list when a response yields nothing
usable. An empty return would let the caller write a file that blanks the
page, and a degraded response must never be able to destroy good data."
```

---

## Task 7: Network layer and change detection

**Files:**
- Modify: `scripts/fetch_listening.py`

**Interfaces:**
- Consumes: `parse_top_tracks`, `TRACK_LIMIT`, `TIME_RANGE` from Task 6
- Produces: a CLI writing `content/listening.json`, exiting non-zero on any failure. Accepts `--keep-alive`. Task 8 invokes it.

- [ ] **Step 1: Append the network and write layer**

In `scripts/fetch_listening.py`, **replace** the lone `import json` line from
Task 6 with this full import block:

```python
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
```

Then append below `parse_top_tracks`:

```python
TOKEN_URL = "https://accounts.spotify.com/api/token"
TOP_TRACKS_URL = "https://api.spotify.com/v1/me/top/tracks"
TIMEOUT_SECONDS = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
LISTENING_PATH = REPO_ROOT / "content" / "listening.json"


def _require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable {name}")
    return value


def _read_json(request, what):
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{what} failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{what} failed (network): {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{what} returned invalid JSON: {exc}") from exc


def refresh_access_token(client_id, client_secret, refresh_token):
    """Trade the refresh token for an access token.

    Returns (access_token, rotated_refresh_token_or_None).
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    payload = _read_json(request, "Token refresh")
    access_token = payload.get("access_token")
    if not access_token:
        raise SystemExit(f"Token response carried no access_token: {payload}")
    return access_token, payload.get("refresh_token")


def get_top_tracks(access_token):
    query = urllib.parse.urlencode({
        "time_range": TIME_RANGE,
        "limit": TRACK_LIMIT,
    })
    request = urllib.request.Request(
        f"{TOP_TRACKS_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return _read_json(request, "Top-tracks fetch")


def load_existing_tracks(path):
    """Committed tracks, or None when there is nothing usable on disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    tracks = data.get("tracks")
    return tracks if isinstance(tracks, list) else None


def write_listening(path, tracks):
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"fetched_at": stamp, "tracks": tracks}, handle, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help=(
            "Write the file even when tracks are unchanged, purely to reset "
            "the 60-day scheduled-workflow inactivity clock."
        ),
    )
    args = parser.parse_args(argv)

    client_id = _require_env("SPOTIFY_CLIENT_ID")
    client_secret = _require_env("SPOTIFY_CLIENT_SECRET")
    refresh_token = _require_env("SPOTIFY_REFRESH_TOKEN")

    access_token, rotated = refresh_access_token(
        client_id, client_secret, refresh_token
    )
    if rotated and rotated != refresh_token:
        # A workflow cannot rewrite its own secret. Silently dropping this
        # would make next week fail for reasons that look unrelated.
        print(
            "\n" + "=" * 68 +
            "\nACTION REQUIRED: Spotify returned a NEW refresh token.\n"
            "Update the SPOTIFY_REFRESH_TOKEN secret to:\n\n"
            f"{rotated}\n\n"
            "This run succeeded, but future runs may fail until you do.\n"
            + "=" * 68,
            file=sys.stderr,
        )

    tracks = parse_top_tracks(get_top_tracks(access_token))

    if tracks == load_existing_tracks(LISTENING_PATH):
        if args.keep_alive:
            write_listening(LISTENING_PATH, tracks)
            print("Tracks unchanged; refreshed timestamp as keep-alive.")
        else:
            print("Tracks unchanged; leaving listening.json alone.")
        return 0

    write_listening(LISTENING_PATH, tracks)
    print(f"Wrote {len(tracks)} tracks to {LISTENING_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify missing credentials fail cleanly**

Run:
```bash
env -u SPOTIFY_CLIENT_ID -u SPOTIFY_CLIENT_SECRET -u SPOTIFY_REFRESH_TOKEN \
  python3 scripts/fetch_listening.py; echo "exit=$?"
```
Expected: `Missing required environment variable SPOTIFY_CLIENT_ID`, non-zero exit, no traceback.

- [ ] **Step 3: Verify the parsing tests still pass**

The new imports must not break Task 6's tests.

Run: `./test.sh; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 4: HUMAN STEP — verify against the live API**

Requires the refresh token from Task 2 Step 5. Run locally, never committing the values:

```bash
read -rsp "client id: "     SPOTIFY_CLIENT_ID     && echo
read -rsp "client secret: " SPOTIFY_CLIENT_SECRET && echo
read -rsp "refresh token: " SPOTIFY_REFRESH_TOKEN && echo
export SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET SPOTIFY_REFRESH_TOKEN
python3 scripts/fetch_listening.py
cat content/listening.json
unset SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET SPOTIFY_REFRESH_TOKEN
```
Expected: 10 real tracks written. Then run it a second time and confirm it reports `Tracks unchanged; leaving listening.json alone.`

- [ ] **Step 5: Rebuild and eyeball the page**

```bash
./build.sh > /dev/null && grep -A12 'now-tracks' docs/index.html
```
Expected: 10 real tracks, stamp `on repeat this month`.

Optionally preview in a browser via `ssh -L 8888:localhost:8888` and `./scripts/main.sh`.

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_listening.py content/listening.json docs/
git commit -m "Add Spotify fetch, token refresh, and change detection

Only the tracks array decides whether to commit. fetched_at changes every
run, so a file-level diff would commit 52 times a year and make the
inactivity keep-alive meaningless. fetched_at now means 'when the tracks
last changed', which is the more useful reading anyway.

A rotated refresh token is reported loudly rather than discarded: a
workflow cannot rewrite its own secret, and dropping it silently would
make a later run fail for reasons that look unrelated."
```

---

## Task 8: The weekly workflow

**Files:**
- Create: `.github/workflows/listening.yml`

**Interfaces:**
- Consumes: `scripts/check_token_age.py` (Task 3), `scripts/fetch_listening.py` (Tasks 6–7), `./build.sh`
- Produces: the running pipeline

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/listening.yml`:

```yaml
name: Refresh Listening

on:
  schedule:
    # Mondays at 14:17 UTC. Deliberately off the hour: GitHub delays
    # scheduled runs that land at the top of an hour under load.
    - cron: "17 14 * * 1"
  workflow_dispatch:

permissions:
  contents: write   # commit listening.json + docs/
  issues: write     # open the token-expiry reminder

concurrency:
  group: refresh-listening
  cancel-in-progress: false

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - name: Check out
        uses: actions/checkout@v4
        with:
          fetch-depth: 0   # keep-alive needs real commit dates

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Check refresh-token age
        id: age
        env:
          SPOTIFY_AUTH_DATE: ${{ vars.SPOTIFY_AUTH_DATE }}
        run: python3 scripts/check_token_age.py

      - name: Ensure the reminder label exists
        if: steps.age.outputs.status != 'OK'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh label create spotify-token \
            --color FBCA04 \
            --description "Spotify credential maintenance" \
            --force

      - name: Open the reminder issue
        if: steps.age.outputs.status != 'OK'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DAYS: ${{ steps.age.outputs.days }}
          STATUS: ${{ steps.age.outputs.status }}
        run: |
          open_count=$(gh issue list --label spotify-token --state open \
            --json number --jq 'length')
          if [ "$open_count" -ne 0 ]; then
            echo "A spotify-token issue is already open; not duplicating."
            exit 0
          fi
          if [ "$STATUS" = "EXPIRED" ]; then
            title="Spotify refresh token has EXPIRED"
          else
            title="Spotify refresh token expires in ${DAYS} days"
          fi
          gh issue create --title "$title" --label spotify-token --body "$(cat <<'BODY'
          The Spotify refresh token is at or near its 6-month hard expiry.
          Refreshing does not extend that clock, so it must be reissued by hand.

          **To fix:**

          1. Run `python3 scripts/spotify_auth.py` on a machine with a browser,
             or on the headless host under `ssh -L 7777:localhost:7777`.
          2. Paste the new token into the `SPOTIFY_REFRESH_TOKEN` secret.
          3. Set the `SPOTIFY_AUTH_DATE` variable to today (`YYYY-MM-DD`).
          4. Close this issue.

          Until then the Listening block keeps showing the last good tracks —
          the site does not break, it just stops updating.

          See `specs/2026-08-09-spotify-listening-design.md`.
          BODY
          )"

      - name: Fail if the token has expired
        if: steps.age.outputs.status == 'EXPIRED'
        run: |
          echo "::error::Spotify refresh token expired. See the open issue."
          exit 1

      - name: Decide whether a keep-alive write is needed
        id: keepalive
        run: |
          last=$(git log -1 --format=%ct)
          age_days=$(( ( $(date +%s) - last ) / 86400 ))
          echo "Most recent commit is ${age_days} day(s) old."
          if [ "$age_days" -ge 45 ]; then
            echo "flag=--keep-alive" >> "$GITHUB_OUTPUT"
          else
            echo "flag=" >> "$GITHUB_OUTPUT"
          fi

      - name: Fetch top tracks
        env:
          SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
          SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
          SPOTIFY_REFRESH_TOKEN: ${{ secrets.SPOTIFY_REFRESH_TOKEN }}
        run: python3 scripts/fetch_listening.py ${{ steps.keepalive.outputs.flag }}

      - name: Build the site
        run: ./build.sh

      - name: Commit if anything changed
        run: |
          # --porcelain rather than `git diff --quiet`: the build recreates
          # docs/ from scratch, so new files show up untracked and a plain
          # diff would miss them entirely.
          if [ -z "$(git status --porcelain -- content/listening.json docs/)" ]; then
            echo "Nothing changed; no commit."
            exit 0
          fi
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add content/listening.json docs/
          git commit -m "Refresh listening data"
          git push
```

- [ ] **Step 2: Validate the YAML parses**

Run:
```bash
python3 -c "
import json, sys
try:
    import yaml
except ImportError:
    sys.exit('PyYAML absent (expected — this repo has no deps). Skipping.')
print(json.dumps(list(yaml.safe_load(open('.github/workflows/listening.yml')))))
"
```
Expected: either the key list, or the skip message. If PyYAML is absent, **do not install it** — that would violate the dependency constraint. Rely on Step 4's real run instead.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/listening.yml
git commit -m "Add weekly Listening refresh workflow

Runs Mondays at 14:17 UTC, off the hour because GitHub delays scheduled
runs that land on the hour under load.

Two independent notification channels for the 6-month token expiry: a
proactive issue at the 30-day mark, and the workflow-failure email that
covers expiry, revocation, and outages alike. The keep-alive step guards
against public repos disabling scheduled workflows after 60 days of
inactivity, which would otherwise silence the very job meant to warn."
```

- [ ] **Step 4: HUMAN STEP — trigger a real run**

Requires the secrets and variable from Task 2 Step 5, and the branch pushed.

1. Push the branch and open a PR, or merge to `main` — `workflow_dispatch` only appears once the workflow file exists on the default branch.
2. Actions tab → **Refresh Listening** → **Run workflow**.
3. Confirm: token age reports `OK`, tracks are fetched, and either a commit lands or it reports nothing changed.
4. Visit the live site and confirm the Listening block shows real tracks.

- [ ] **Step 5: HUMAN STEP — prove the reminder actually fires**

Do not trust an untested alarm. Temporarily set the `SPOTIFY_AUTH_DATE` variable to a date ~160 days ago, run the workflow manually, and confirm an issue is opened with the `spotify-token` label. Then set a date ~200 days ago and confirm the job fails with the `::error::` annotation. Finally restore the real date.

---

## Post-Implementation

- [ ] Delete `MIGRATION_NOTES.txt` (`git rm MIGRATION_NOTES.txt`) — the notes ask for this once the migration is done, which it is.
- [ ] Consider a follow-up spec for the stale `src/tests/` files (39 run / 11 failures / 9 errors), which this plan deliberately left alone.
- [ ] The guestbook spec comes next; live currently-playing rides along with the backend it forces into existence.
