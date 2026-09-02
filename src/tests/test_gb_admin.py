"""Tests for scripts/guestbook_admin.py, the standalone moderation CLI.

Two layers: unit tests importing the module directly (the local
normalize()/digest() duplicate cross-checked against the real
worker/src implementation, plus check_allow_overlap()), and CLI-level
tests driving the script as a subprocess against a stub admin API on
http.server — covering exit codes, stdout/stderr, and what actually hit
the wire, including proof that a missing token short-circuits before any
network call.

The token is never passed on argv — it goes through the environment,
matching the script's own contract.
"""
import contextlib
import http.server
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
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
    """The script's local normalize duplicate must track the real one —
    if worker/src/normalize.py's table changes without a matching update
    here, this test starts failing."""

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
    """An allow.txt entry that is itself a blocked term.

    Blocked digests are computed through the REAL worker/src pipeline,
    not the module under test's own _digest_local, so a broken
    _digest_local can't make these pass vacuously.
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
    Pure wiring — the overlap logic itself is covered above."""

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
        return self.headers.get("authorization") == expected

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        # Lowercased keys: header names are case-insensitive on the
        # wire, and urllib normalises "CF-Access-Client-Id" to
        # "Cf-access-client-id". Asserting on exact case would test
        # urllib's capitalisation rather than this tool's behaviour.
        self.server.state.requests.append(
            (method, self.path,
             {k.lower(): v for k, v in self.headers.items()})
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


class TestCredentialLoading(unittest.TestCase):
    """Where the tool gets its secrets, and what it refuses."""

    def _write(self, body, mode=0o600):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "credentials"
        path.write_text(body, encoding="utf-8")
        path.chmod(mode)
        self.addCleanup(shutil.rmtree, directory)
        return path

    def test_reads_key_value_pairs(self):
        path = self._write("GUESTBOOK_ADMIN_TOKEN=abc123\n")
        self.assertEqual(
            guestbook_admin._read_credentials_file(path),
            {"GUESTBOOK_ADMIN_TOKEN": "abc123"},
        )

    def test_ignores_comments_blanks_and_junk(self):
        path = self._write("# a note\n\nGUESTBOOK_ADMIN_TOKEN=abc\nnonsense\n")
        self.assertEqual(
            guestbook_admin._read_credentials_file(path),
            {"GUESTBOOK_ADMIN_TOKEN": "abc"},
        )

    def test_strips_surrounding_quotes(self):
        """A pasted value often arrives quoted; the quotes are not the secret."""
        path = self._write('GUESTBOOK_ADMIN_TOKEN="abc123"\n')
        self.assertEqual(
            guestbook_admin._read_credentials_file(path)["GUESTBOOK_ADMIN_TOKEN"],
            "abc123",
        )

    def test_missing_file_is_not_an_error(self):
        """Environment-only use must keep working with no file present."""
        missing = Path(tempfile.mkdtemp()) / "nope" / "credentials"
        self.assertEqual(guestbook_admin._read_credentials_file(missing), {})

    def test_refuses_a_file_others_can_read(self):
        path = self._write("GUESTBOOK_ADMIN_TOKEN=abc\n", mode=0o644)
        with self.assertRaises(SystemExit) as caught:
            guestbook_admin._read_credentials_file(path)
        self.assertEqual(caught.exception.code, 2)

    def test_refuses_a_group_readable_file(self):
        path = self._write("GUESTBOOK_ADMIN_TOKEN=abc\n", mode=0o640)
        with self.assertRaises(SystemExit):
            guestbook_admin._read_credentials_file(path)

    def test_path_can_be_overridden_by_environment(self):
        """The suite must never read the developer's own credentials, or
        "no token configured" is untestable on the machines that matter."""
        path = self._write("GUESTBOOK_ADMIN_TOKEN=from-override\n")
        with mock.patch.dict(os.environ, {"GUESTBOOK_CREDENTIALS": str(path)}):
            self.assertEqual(
                guestbook_admin._read_credentials_file(),
                {"GUESTBOOK_ADMIN_TOKEN": "from-override"},
            )

    def test_override_pointing_nowhere_reads_nothing(self):
        missing = Path(tempfile.gettempdir()) / "gb-definitely-not-here"
        with mock.patch.dict(os.environ, {"GUESTBOOK_CREDENTIALS": str(missing)}):
            self.assertEqual(guestbook_admin._read_credentials_file(), {})

    def test_environment_beats_the_file(self):
        stored = {"GUESTBOOK_ADMIN_TOKEN": "from-file"}
        with mock.patch.dict(os.environ, {"GUESTBOOK_ADMIN_TOKEN": "from-env"}):
            self.assertEqual(
                guestbook_admin._credential("GUESTBOOK_ADMIN_TOKEN", stored),
                "from-env",
            )

    def test_file_is_used_when_the_environment_is_unset(self):
        stored = {"GUESTBOOK_ADMIN_TOKEN": "from-file"}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                guestbook_admin._credential("GUESTBOOK_ADMIN_TOKEN", stored),
                "from-file",
            )

    def test_empty_environment_value_falls_through_to_the_file(self):
        """`export TOKEN=` is a mistake, not a decision to send nothing."""
        stored = {"GUESTBOOK_ADMIN_TOKEN": "from-file"}
        with mock.patch.dict(os.environ, {"GUESTBOOK_ADMIN_TOKEN": ""}):
            self.assertEqual(
                guestbook_admin._credential("GUESTBOOK_ADMIN_TOKEN", stored),
                "from-file",
            )


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
        # Point the CLI at a path that does not exist, so the suite can
        # never read the credentials file of whoever is running it. A
        # "no token configured" test is meaningless on a machine where
        # one is configured.
        env["GUESTBOOK_CREDENTIALS"] = os.path.join(
            tempfile.gettempdir(), "gb-admin-tests-nonexistent-credentials"
        )
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
        self.assertEqual(headers.get("authorization"), f"Bearer {self.token}")

    def test_sends_access_service_token_when_both_halves_are_present(self):
        with mock.patch.dict(os.environ, {
            "CF_ACCESS_CLIENT_ID": "id-value",
            "CF_ACCESS_CLIENT_SECRET": "secret-value",
        }):
            self._run(["--list"])
        _method, _path, headers = self.server.state.requests[-1]
        self.assertEqual(headers.get("cf-access-client-id"), "id-value")
        self.assertEqual(headers.get("cf-access-client-secret"), "secret-value")

    def test_sends_neither_half_when_only_one_is_configured(self):
        """Half a service token is a misconfiguration, not a credential —
        sending the id alone reads to Access as a failed auth attempt."""
        with mock.patch.dict(os.environ, {"CF_ACCESS_CLIENT_ID": "id-only"},
                             clear=False):
            os.environ.pop("CF_ACCESS_CLIENT_SECRET", None)
            self._run(["--list"])
        _method, _path, headers = self.server.state.requests[-1]
        self.assertIsNone(headers.get("cf-access-client-id"))
        self.assertIsNone(headers.get("cf-access-client-secret"))

    def test_identifies_itself_by_user_agent(self):
        """urllib's default agent is 403'd by Cloudflare bot protection
        (error 1010) before the Worker even runs — its absence is a
        production outage, not a cosmetic omission."""
        self._run(["--list"])
        _method, _path, headers = self.server.state.requests[-1]
        agent = headers.get("user-agent", "")
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
