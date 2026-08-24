"""Tests for scripts/guestbook_admin.py, the standalone moderation CLI.

Two layers:

  * Unit tests, importing the module directly (scripts/ is on sys.path
    via scripts/run_tests.py, same as test_check_token_age.py does for
    check_token_age.py). These cover the pure helpers: the local
    normalize()/digest() duplicate (cross-checked against the real
    worker/src implementation, so a drift between the two fails loudly
    instead of silently) and check_allow_overlap().

  * CLI-level tests, driving the script as a subprocess against a real
    stub admin API built on http.server and bound to port 0. These cover
    everything that only exists at the process boundary: exit codes,
    stdout/stderr text, and what the stub actually received on the wire
    (method, path, headers) -- including proof that a missing token or a
    rejected flag combination short-circuits BEFORE any network call.

The token is never passed on argv in any of these -- it goes through the
environment, matching the script's own contract.
"""
import contextlib
import http.server
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import guestbook_admin
from matching import digest as real_digest
from normalize import normalize as real_normalize
from normalize import strip_nonalnum as real_strip_nonalnum

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "guestbook_admin.py"
TOKEN_VAR = "GUESTBOOK_ADMIN_TOKEN"


def _real_pipeline_digest(term):
    """The digest scripts/hash_terms.py would have written for `term`."""
    return real_digest(real_strip_nonalnum(real_normalize(term)))


# ---------------------------------------------------------------------------
# Unit tests: pure helpers, imported directly.
# ---------------------------------------------------------------------------

SAMPLE_TERMS = [
    "hello",
    "HELLO",
    "Héllo",
    "hello world",
    "  spaced  ",
    "café",
    "CAFÉ",
    "naïve",
    "über",
    "test-case!!",
    "Cockburn",
    "а",  # Cyrillic 'а' (U+0430), a CONFUSABLES key -> should fold to 'a'
]


class TestNormalizeLocalMatchesReal(unittest.TestCase):
    """The script's local normalize duplicate must track the real one.

    This is the guard against the duplication risk called out in the
    module: if worker/src/normalize.py's table changes and the copy in
    guestbook_admin.py is not updated to match, this test starts failing.
    """

    def test_matches_real_normalize_for_sample_terms(self):
        for term in SAMPLE_TERMS:
            with self.subTest(term=term):
                self.assertEqual(
                    guestbook_admin._normalize_local(term),
                    real_normalize(term),
                )

    def test_differs_for_a_case_that_would_expose_a_broken_copy(self):
        # Sanity check on the sample set itself: casefold and confusable
        # folding must actually be doing something observable, or the
        # equality above would pass vacuously for a no-op implementation.
        self.assertNotEqual(
            guestbook_admin._normalize_local("HELLO"),
            "HELLO",
        )
        self.assertEqual(
            guestbook_admin._normalize_local("а"),  # Cyrillic
            "a",  # Latin
        )


class TestDigestLocalMatchesReal(unittest.TestCase):
    def test_matches_the_committed_digest_pipeline(self):
        for term in SAMPLE_TERMS:
            with self.subTest(term=term):
                self.assertEqual(
                    guestbook_admin._digest_local(term),
                    _real_pipeline_digest(term),
                )

    def test_case_and_accent_variants_collide_like_the_real_pipeline(self):
        # If digest() folded on the real side but the local copy didn't,
        # these would produce different hashes and this test would catch
        # it even though test_matches_the_committed_digest_pipeline above
        # checks each term only against itself.
        self.assertEqual(
            guestbook_admin._digest_local("café"),
            guestbook_admin._digest_local("CAFÉ"),
        )
        self.assertEqual(
            guestbook_admin._digest_local("cafe"),
            guestbook_admin._digest_local("café"),
        )


class TestCheckAllowOverlap(unittest.TestCase):
    """Task 5's gap: an allow.txt entry that is itself a blocked term.

    Blocked digests here are computed through the REAL worker/src
    pipeline (matching.digest + normalize.strip_nonalnum/normalize), not
    through the module under test's own _digest_local -- so a broken
    _digest_local (e.g. one that always returns a constant) cannot make
    these pass vacuously.
    """

    def _write(self, dir_path, name, lines):
        path = Path(dir_path) / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_detects_overlap_case_and_accent_insensitive(self):
        with tempfile.TemporaryDirectory() as d:
            blocked = self._write(
                d, "blocked.txt", ["# header", _real_pipeline_digest("cafe")]
            )
            allow = self._write(d, "allow.txt", ["# note", "Café"])
            overlap = guestbook_admin.check_allow_overlap(allow, blocked)
            self.assertEqual(overlap, ["Café"])

    def test_no_overlap_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            blocked = self._write(
                d, "blocked.txt", [_real_pipeline_digest("zzzunrelatedterm")]
            )
            allow = self._write(d, "allow.txt", ["Bob", "Cockburn"])
            self.assertEqual(
                guestbook_admin.check_allow_overlap(allow, blocked), []
            )

    def test_empty_blocked_file_short_circuits(self):
        # Header-only blocked.txt (the committed state of this repo's
        # copy) must not be treated as "everything overlaps."
        with tempfile.TemporaryDirectory() as d:
            blocked = self._write(d, "blocked.txt", ["# header only, no digests"])
            allow = self._write(d, "allow.txt", ["Anything"])
            self.assertEqual(
                guestbook_admin.check_allow_overlap(allow, blocked), []
            )

    def test_missing_files_return_empty_not_an_exception(self):
        missing_allow = Path("/nonexistent-guestbook-admin-test/allow.txt")
        missing_blocked = Path("/nonexistent-guestbook-admin-test/blocked.txt")
        self.assertEqual(
            guestbook_admin.check_allow_overlap(missing_allow, missing_blocked),
            [],
        )

    def test_comments_and_blank_lines_ignored_on_both_sides(self):
        with tempfile.TemporaryDirectory() as d:
            blocked = self._write(
                d,
                "blocked.txt",
                ["", "# comment", _real_pipeline_digest("shibboleth"), ""],
            )
            allow = self._write(
                d, "allow.txt", ["", "# note", "shibboleth", ""]
            )
            self.assertEqual(
                guestbook_admin.check_allow_overlap(allow, blocked),
                ["shibboleth"],
            )


class TestReviewOverlapWarningWiring(unittest.TestCase):
    """main() must actually consult check_allow_overlap() and gate on it.

    Drives main() in-process with _call and check_allow_overlap
    monkeypatched, so this is pure wiring -- the overlap logic itself is
    covered above, independently.
    """

    def setUp(self):
        self._orig_call = guestbook_admin._call
        self._orig_overlap = guestbook_admin.check_allow_overlap
        self._orig_argv = sys.argv
        self._orig_token = os.environ.get(TOKEN_VAR)
        os.environ[TOKEN_VAR] = "irrelevant-not-used-by-the-stub"

    def tearDown(self):
        guestbook_admin._call = self._orig_call
        guestbook_admin.check_allow_overlap = self._orig_overlap
        sys.argv = self._orig_argv
        if self._orig_token is None:
            os.environ.pop(TOKEN_VAR, None)
        else:
            os.environ[TOKEN_VAR] = self._orig_token

    def _run_review(self, entries, overlap):
        guestbook_admin._call = lambda path, method="GET": {"entries": entries}
        guestbook_admin.check_allow_overlap = lambda: overlap
        sys.argv = ["guestbook_admin.py", "--review"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = guestbook_admin.main()
        return code, buf.getvalue()

    def test_warns_when_overlap_present(self):
        entries = [{
            "id": 1, "name": "X", "message": "m", "created_at": "t",
            "hidden": 1, "block_reason": "slur",
        }]
        code, out = self._run_review(entries, ["dangerword"])
        self.assertEqual(code, 0)
        self.assertIn("WARNING", out)
        self.assertIn("dangerword", out)

    def test_silent_when_no_overlap(self):
        entries = [{
            "id": 1, "name": "X", "message": "m", "created_at": "t",
            "hidden": 1, "block_reason": "slur",
        }]
        code, out = self._run_review(entries, [])
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING", out)


# ---------------------------------------------------------------------------
# CLI-level tests: subprocess against a real stub admin API.
# ---------------------------------------------------------------------------

FIXTURE_ENTRIES = [
    {
        "id": 1, "name": "Alice", "message": "hello there",
        "created_at": "2026-01-01T00:00:00Z",
        "hidden": 0, "block_reason": None,
    },
    {
        "id": 2, "name": "Eve", "message": "filtered text",
        "created_at": "2026-01-02T00:00:00Z",
        "hidden": 1, "block_reason": "slur",
    },
    {
        "id": 3, "name": "Mallory", "message": "manually removed",
        "created_at": "2026-01-03T00:00:00Z",
        "hidden": 1, "block_reason": "manual",
    },
]


class _StubState:
    def __init__(self, token, entries):
        self.token = token
        self.entries = entries
        self.requests = []  # list of (method, path, headers-dict)


class _StubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep test output clean

    def _authorized(self):
        expected = f"Bearer {self.server.state.token}"
        return self.headers.get("Authorization") == expected

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        self.server.state.requests.append(
            (method, self.path, dict(self.headers.items()))
        )
        if not self._authorized():
            self._respond(401, {"ok": False, "code": "unauthorized"})
            return
        if method == "GET" and self.path == "/admin/entries":
            self._respond(200, {"entries": self.server.state.entries})
            return
        if method == "POST" and self.path.startswith("/admin/entries/"):
            self._respond(200, {"ok": True})
            return
        self._respond(404, {"ok": False, "code": "not_found"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def _start_stub(token, entries):
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubHandler)
    server.state = _StubState(token, entries)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_stub(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _closed_port_url():
    """A URL nothing listens on: bind port 0, note it, close immediately."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


class TestCliAgainstStubServer(unittest.TestCase):
    def setUp(self):
        self.token = "s3cret-admin-token"
        self.server, self.thread = _start_stub(self.token, FIXTURE_ENTRIES)
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        _stop_stub(self.server, self.thread)

    def _env(self, api=None, token="__default__"):
        env = dict(os.environ)
        env["GUESTBOOK_API"] = self.api if api is None else api
        used_token = self.token if token == "__default__" else token
        if used_token is None:
            env.pop(TOKEN_VAR, None)
        else:
            env[TOKEN_VAR] = used_token
        return env

    def _run(self, args, api=None, token="__default__"):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            env=self._env(api=api, token=token),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    # -- happy paths: filtering -------------------------------------

    def test_list_shows_only_visible_entries(self):
        result = self._run(["--list"])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Alice", result.stdout)
        self.assertNotIn("Eve", result.stdout)
        self.assertNotIn("Mallory", result.stdout)

    def test_review_shows_only_slur_blocked_entries(self):
        result = self._run(["--review"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Eve", result.stdout)
        self.assertNotIn("Alice", result.stdout)
        self.assertNotIn("Mallory", result.stdout)
        self.assertIn("allow.txt", result.stdout)

    def test_all_shows_visible_and_hidden_entries(self):
        result = self._run(["--all"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Alice", result.stdout)
        self.assertIn("Eve", result.stdout)
        self.assertIn("Mallory", result.stdout)

    # -- hide / unhide: correct path and method ----------------------

    def test_hide_hits_correct_path_and_method(self):
        result = self._run(["--hide", "41"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Hid entry 41", result.stdout)
        method, path, _headers = self.server.state.requests[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/admin/entries/41/hide")

    def test_unhide_hits_correct_path_and_method(self):
        result = self._run(["--unhide", "41"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Restored entry 41", result.stdout)
        method, path, _headers = self.server.state.requests[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/admin/entries/41/unhide")

    # -- header actually sent -----------------------------------------

    def test_authorization_header_is_sent(self):
        self._run(["--list"])
        _method, _path, headers = self.server.state.requests[-1]
        self.assertEqual(headers.get("Authorization"), f"Bearer {self.token}")

    def test_identifies_itself_by_user_agent(self):
        """urllib's default agent is 403'd by Cloudflare bot protection.

        Error 1010, at the edge, before the Worker runs -- so every admin
        command failed against production while passing against this
        stub. The header is what makes the tool reachable, so its absence
        is a production outage, not a cosmetic omission.
        """
        self._run(["--list"])
        _method, _path, headers = self.server.state.requests[-1]
        agent = headers.get("User-Agent", "")
        self.assertIn("guestbook-admin", agent)
        self.assertNotIn("Python-urllib", agent)

    # -- failure paths: clean, correct exit code, no traceback --------

    def test_missing_token_exits_2_and_never_touches_the_network(self):
        result = self._run(["--list"], token=None)
        self.assertEqual(result.returncode, 2)
        self.assertIn(TOKEN_VAR, result.stderr)
        self.assertIn("not set", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.state.requests, [])

    def test_wrong_token_exits_1_clean(self):
        result = self._run(["--list"], token="not-the-right-token")
        self.assertEqual(result.returncode, 1)
        self.assertIn("401", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unreachable_host_exits_1_clean(self):
        result = self._run(["--list"], api=_closed_port_url())
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not reach", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    # -- argument validation -------------------------------------------

    def test_mutually_exclusive_flags_rejected(self):
        result = self._run(["--list", "--review"])
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.state.requests, [])

    def test_no_flags_rejected(self):
        result = self._run([])
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.state.requests, [])


if __name__ == "__main__":
    unittest.main()
