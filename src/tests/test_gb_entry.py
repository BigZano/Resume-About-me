"""The Worker HTTP layer, driven end to end against real SQLite.

D1 *is* SQLite, so the storage layer is stood up in-process from
`worker/schema.sql` — every statement entry.py sends hits a real
database, and a typo in a column name is an OperationalError, not a
silent pass. Faked: `workers.Response`, `env`, and a thin async shim
over `sqlite3` for the D1 prepare/bind/first/all/run chain. The SQL
itself is never faked.

Every assertion is a status code, a response body, or a row read back
out of the database — nothing here checks how a collaborator was called.
"""
import asyncio
import hashlib
import json
import sqlite3
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "worker" / "schema.sql"


class _Response:
    """Stand-in for workers.Response. Records what the Worker replied."""

    def __init__(self, body="", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


_WORKERS = types.ModuleType("workers")
_WORKERS.Response = _Response
sys.modules["workers"] = _WORKERS

import entry  # noqa: E402  -- must follow the sys.modules injection above
from matching import Blocklist, digest  # noqa: E402

ORIGIN = "https://bretzanotelli.work"
ADMIN_TOKEN = "test-admin-token"
SALT = "test-rate-salt"
IP = "203.0.113.77"
OTHER_IP = "198.51.100.9"

# A fake term proves the wiring as well as a real slur would, and keeps
# the file readable. 'zq' not 'zz': normalize.candidates() collapses runs
# of a repeated character.
BLOCKED_TERM = "zqblocked"

# Present in the committed worker/data/swaps.txt.
SWAP_IN, SWAP_OUT = "fuck", "flip"

# Present in the committed worker/data/allow.txt.
ALLOWED_WORD = "scunthorpe"


class _JsRow:
    """A D1 row shaped the way Pyodide hands it over: not subscriptable,
    dict() refused, only to_py() gets you in. If entry._row ever stops
    calling to_py(), every test using this class raises."""

    def __init__(self, mapping):
        self._mapping = dict(mapping)

    def to_py(self):
        return dict(self._mapping)


class _Results:
    """The object D1's .all() returns. entry.py calls .to_py() on it, and
    that conversion is recursive, so this shim's to_py() returns rows as
    plain dicts too — matching what the real runtime produces."""

    def __init__(self, results):
        self.results = results

    def to_py(self):
        return {
            "results": [
                row.to_py() if hasattr(row, "to_py") else dict(row)
                for row in self.results
            ]
        }


class _Statement:
    def __init__(self, conn, sql, row_factory):
        self._conn = conn
        self._sql = sql
        self._row_factory = row_factory
        self._params = ()

    def bind(self, *params):
        self._params = params
        return self

    def _execute(self):
        return self._conn.execute(self._sql, self._params)

    async def first(self):
        row = self._execute().fetchone()
        return None if row is None else self._row_factory(dict(row))

    async def all(self):
        rows = self._execute().fetchall()
        return _Results([self._row_factory(dict(r)) for r in rows])

    async def run(self):
        self._execute()
        self._conn.commit()
        return _Results([])


class _D1:
    """env.DB, backed by a real in-memory SQLite database."""

    def __init__(self, conn, row_factory=dict):
        self._conn = conn
        self._row_factory = row_factory

    def prepare(self, sql):
        return _Statement(self._conn, sql, self._row_factory)


class _Env:
    def __init__(self, db, origin=ORIGIN, admin_token=ADMIN_TOKEN, salt=SALT):
        self.DB = db
        self.ALLOWED_ORIGIN = origin
        self.ADMIN_TOKEN = admin_token
        self.RATE_SALT = salt


class _Headers:
    """Case-insensitive, like the Headers object Workers supplies."""

    def __init__(self, mapping=None):
        self._items = {k.lower(): v for k, v in (mapping or {}).items()}

    def get(self, name):
        return self._items.get(name.lower())


class _Request:
    def __init__(self, method="GET", path="/entries", query="",
                 headers=None, body=""):
        self.method = method
        self.url = "https://api.bretzanotelli.work" + path
        if query:
            self.url += "?" + query
        self.headers = _Headers(headers)
        self._body = body

    async def text(self):
        return self._body


def _stamp(offset=None):
    moment = datetime.now(UTC)
    if offset is not None:
        moment -= offset
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_ip_hash(ip, salt=SALT):
    """The digest the spec mandates: sha256(RATE_SALT || ip), truncated."""
    return hashlib.sha256((salt + ip).encode("utf-8")).hexdigest()[:32]


class WorkerCase(unittest.TestCase):
    """Base: a fresh schema-loaded database and a fresh env per test."""

    row_factory = dict

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self.addCleanup(self.conn.close)
        self.env = _Env(_D1(self.conn, self.row_factory))

    # -- driving --------------------------------------------------------

    def fetch(self, request):
        return asyncio.run(entry.on_fetch(request, self.env))

    def post(self, payload=None, ip=IP, raw_body=None, headers=None):
        body = json.dumps(payload) if raw_body is None else raw_body
        hdrs = {"cf-connecting-ip": ip, "content-type": "application/json"}
        hdrs.update(headers or {})
        return self.fetch(
            _Request(method="POST", path="/entries", headers=hdrs, body=body)
        )

    def get(self, query="", ip=IP):
        return self.fetch(
            _Request(path="/entries", query=query,
                     headers={"cf-connecting-ip": ip})
        )

    def admin(self, path="/admin/entries", token=ADMIN_TOKEN, method="GET",
              raw_header=None):
        headers = {}
        if raw_header is not None:
            headers["authorization"] = raw_header
        elif token is not None:
            headers["authorization"] = "Bearer " + token
        return self.fetch(_Request(method=method, path=path, headers=headers))

    # -- reading back ---------------------------------------------------

    @staticmethod
    def payload(response):
        return json.loads(response.body)

    def rows(self):
        cur = self.conn.execute("SELECT * FROM entries ORDER BY id")
        return [dict(r) for r in cur.fetchall()]

    def insert(self, name="Someone", message="hello", created_at=None,
               ip_hash="deadbeef", hidden=0, block_reason=None):
        cur = self.conn.execute(
            "INSERT INTO entries "
            "(name, message, created_at, ip_hash, hidden, block_reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, message, created_at or _stamp(), ip_hash, hidden,
             block_reason),
        )
        self.conn.commit()
        return cur.lastrowid

    # -- seams ----------------------------------------------------------

    def use_blocklist(self, *terms):
        """Point entry at a denylist that actually contains something —
        the committed worker/data/blocked.txt is header-only by design."""
        original = entry.BLOCKLIST
        self.addCleanup(setattr, entry, "BLOCKLIST", original)
        entry.BLOCKLIST = Blocklist(
            digests=frozenset(digest(term) for term in terms),
            minlen=3,
            maxlen=14,
            substr_minlen=5,
        )

    def use_allow(self, allow):
        original = entry.ALLOW
        self.addCleanup(setattr, entry, "ALLOW", original)
        entry.ALLOW = allow


class TestWiring(WorkerCase):
    """The module's own load-time state and its data files."""

    def test_swaps_loaded_from_the_committed_file(self):
        self.assertEqual(entry.SWAPS.get(SWAP_IN), SWAP_OUT)

    def test_allowlist_loaded_from_the_committed_file(self):
        self.assertIn(ALLOWED_WORD, entry.ALLOW)

    def test_committed_blocklist_holds_digests_and_no_plaintext(self):
        """The file is public. Only hashes may be in it, ever."""
        path = _REPO_ROOT / "worker" / "src" / "data" / "blocked.txt"
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertRegex(
                line, r"^[0-9a-f]{64}$",
                f"{path.name}:{number} is not a SHA-256 digest",
            )

    def test_verify_challenge_is_hardcoded_open(self):
        # A documented Turnstile seam, not a feature. Pinned so that
        # "it always returns True" is a decision on the record.
        self.assertIs(entry.verify_challenge(_Request()), True)


class TestPostClean(WorkerCase):
    def test_clean_submission_returns_201(self):
        response = self.post({"name": "Bret", "message": "nice site",
                              "website": ""})
        self.assertEqual(response.status, 201)
        self.assertEqual(self.payload(response)["ok"], True)

    def test_clean_submission_is_stored_visible(self):
        self.post({"name": "Bret", "message": "nice site", "website": ""})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Bret")
        self.assertEqual(rows[0]["message"], "nice site")
        self.assertEqual(rows[0]["hidden"], 0)
        self.assertIsNone(rows[0]["block_reason"])

    def test_response_entry_carries_the_frontend_contract(self):
        response = self.post({"name": "Bret", "message": "nice site",
                              "website": ""})
        entry_payload = self.payload(response)["entry"]
        self.assertEqual(
            set(entry_payload),
            {"name", "message_display", "message_raw", "has_swap",
             "created_at"},
        )
        self.assertEqual(entry_payload["message_display"], "nice site")
        self.assertEqual(entry_payload["message_raw"], "nice site")
        self.assertIs(entry_payload["has_swap"], False)

    def test_name_is_trimmed_before_storage(self):
        self.post({"name": "  Bret  ", "message": "hi", "website": ""})
        self.assertEqual(self.rows()[0]["name"], "Bret")

    def test_stored_name_is_the_policy_display_not_the_raw_field(self):
        # str.strip() does not remove a zero-width space; policy's
        # _cleaned() does. Storing the pre-policy string instead of
        # name_verdict.display would persist the padding and every
        # ordinary trimming test would still pass.
        self.post({"name": "​Bret​", "message": "hi",
                   "website": ""})
        self.assertEqual(self.rows()[0]["name"], "Bret")

    def test_created_at_is_iso_utc(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        stored = self.rows()[0]["created_at"]
        parsed = datetime.strptime(stored, "%Y-%m-%dT%H:%M:%SZ")
        self.assertLess(
            abs((parsed.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()),
            120,
        )

    def test_stored_created_at_matches_the_response(self):
        response = self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertEqual(
            self.payload(response)["entry"]["created_at"],
            self.rows()[0]["created_at"],
        )


class TestPostProfanity(WorkerCase):
    """Profanity is allowed. It is stored raw and softened on render."""

    def test_message_column_holds_the_raw_text(self):
        self.post({"name": "Friend", "message": f"hey {SWAP_IN} you",
                   "website": ""})
        self.assertEqual(self.rows()[0]["message"], f"hey {SWAP_IN} you")

    def test_response_carries_both_forms_and_the_swap_flag(self):
        response = self.post({"name": "Friend",
                              "message": f"hey {SWAP_IN} you", "website": ""})
        payload = self.payload(response)["entry"]
        self.assertEqual(payload["message_display"], f"hey {SWAP_OUT} you")
        self.assertEqual(payload["message_raw"], f"hey {SWAP_IN} you")
        self.assertIs(payload["has_swap"], True)

    def test_profanity_is_not_hidden(self):
        self.post({"name": "Friend", "message": f"hey {SWAP_IN} you",
                   "website": ""})
        self.assertEqual(self.rows()[0]["hidden"], 0)


class TestHoneypot(WorkerCase):
    def test_filled_honeypot_looks_exactly_like_success(self):
        response = self.post({"name": "Bot", "message": "spam",
                              "website": "http://spam.example"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response), {"ok": True})

    def test_filled_honeypot_stores_nothing(self):
        self.post({"name": "Bot", "message": "spam",
                   "website": "http://spam.example"})
        self.assertEqual(self.rows(), [])

    def test_whitespace_only_honeypot_is_not_a_bot(self):
        response = self.post({"name": "Bret", "message": "hi",
                              "website": "   "})
        self.assertEqual(response.status, 201)

    def test_non_string_honeypot_does_not_explode(self):
        # JSON can put a number in any field. `5 .strip()` is an
        # AttributeError without the str() coercion at the boundary.
        response = self.post({"name": "Bot", "message": "spam", "website": 5})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.rows(), [])


class TestBlocked(WorkerCase):
    """Blocked entries are stored hidden, never destroyed."""

    def setUp(self):
        super().setUp()
        self.use_blocklist(BLOCKED_TERM)

    def test_slur_in_message_is_rejected(self):
        response = self.post({"name": "Bret",
                              "message": f"you are a {BLOCKED_TERM}",
                              "website": ""})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "blocked"})

    def test_slur_in_message_is_stored_hidden_with_a_reason(self):
        self.post({"name": "Bret", "message": f"you are a {BLOCKED_TERM}",
                   "website": ""})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hidden"], 1)
        self.assertEqual(rows[0]["block_reason"], "slur")
        self.assertEqual(rows[0]["message"], f"you are a {BLOCKED_TERM}")

    def test_slur_in_the_name_is_rejected_identically(self):
        response = self.post({"name": BLOCKED_TERM, "message": "hello",
                              "website": ""})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "blocked"})

    def test_slur_in_the_name_still_reaches_the_audit_trail(self):
        # The whole point of storing blocked entries is that a filter
        # misfire stays auditable. A name-blocked entry that vanished
        # would be the one misfire nobody could review.
        self.post({"name": BLOCKED_TERM, "message": "hello", "website": ""})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], BLOCKED_TERM)
        self.assertEqual(rows[0]["message"], "hello")
        self.assertEqual(rows[0]["hidden"], 1)
        self.assertEqual(rows[0]["block_reason"], "slur")

    def test_blocked_entries_never_reach_the_public_read(self):
        self.post({"name": BLOCKED_TERM, "message": "hello", "website": ""})
        self.assertEqual(self.payload(self.get())["entries"], [])

    def test_blocked_wins_over_a_fixable_rejection(self):
        # Name blocked, message a link. The audit trail takes precedence:
        # a 'url_not_allowed' answer here would drop the slur on the floor.
        response = self.post({"name": BLOCKED_TERM,
                              "message": "visit example.com", "website": ""})
        self.assertEqual(self.payload(response)["code"], "blocked")
        self.assertEqual(self.rows()[0]["block_reason"], "slur")

    # The allowlist has to be threaded into BOTH policy calls. Each pair
    # below is a test and its control: the same submission passes with
    # ALLOW wired through and is blocked without it, which is what pins
    # the parameter rather than merely exercising it.

    def test_allowlisted_word_in_the_message_is_not_blocked(self):
        self.use_blocklist(ALLOWED_WORD)
        response = self.post({"name": "Bret",
                              "message": f"greetings from {ALLOWED_WORD}",
                              "website": ""})
        self.assertEqual(response.status, 201)

    def test_message_blocks_once_the_allowlist_is_taken_away(self):
        self.use_blocklist(ALLOWED_WORD)
        self.use_allow(frozenset())
        response = self.post({"name": "Bret",
                              "message": f"greetings from {ALLOWED_WORD}",
                              "website": ""})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "blocked")

    def test_allowlisted_word_in_the_name_is_not_blocked(self):
        # 'James Cockburn' is a real surname; blocking it costs more than
        # it saves. See policy.py's module docstring.
        self.use_blocklist(ALLOWED_WORD)
        response = self.post({"name": f"{ALLOWED_WORD} Sam",
                              "message": "hello", "website": ""})
        self.assertEqual(response.status, 201)

    def test_name_blocks_once_the_allowlist_is_taken_away(self):
        self.use_blocklist(ALLOWED_WORD)
        self.use_allow(frozenset())
        response = self.post({"name": f"{ALLOWED_WORD} Sam",
                              "message": "hello", "website": ""})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "blocked")


class TestRejections(WorkerCase):
    """Fixable problems: rejected with a code, and nothing is stored."""

    def assert_rejected(self, payload, code):
        response = self.post(payload)
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response), {"ok": False, "code": code})
        self.assertEqual(self.rows(), [])

    def test_url_in_message(self):
        self.assert_rejected(
            {"name": "X", "message": "buy at spam.example", "website": ""},
            "url_not_allowed",
        )

    def test_url_in_name(self):
        self.assert_rejected(
            {"name": "spam.example", "message": "hello", "website": ""},
            "url_not_allowed",
        )

    def test_empty_name(self):
        self.assert_rejected(
            {"name": "", "message": "hello", "website": ""}, "empty")

    def test_empty_message(self):
        self.assert_rejected(
            {"name": "Bret", "message": "", "website": ""}, "empty")

    def test_missing_fields_entirely(self):
        self.assert_rejected({}, "empty")

    def test_name_over_the_cap(self):
        self.assert_rejected(
            {"name": "n" * 41, "message": "hello", "website": ""},
            "name_too_long",
        )

    def test_name_at_the_cap_is_accepted(self):
        response = self.post({"name": "n" * 40, "message": "hello",
                              "website": ""})
        self.assertEqual(response.status, 201)

    def test_message_over_the_cap(self):
        self.assert_rejected(
            {"name": "Bret", "message": "m" * 501, "website": ""},
            "message_too_long",
        )

    def test_message_at_the_cap_is_accepted(self):
        response = self.post({"name": "Bret", "message": "m" * 500,
                              "website": ""})
        self.assertEqual(response.status, 201)

    def test_unparseable_json(self):
        response = self.post(raw_body="not json at all")
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "empty")
        self.assertEqual(self.rows(), [])

    def test_json_array_body_is_not_a_500(self):
        response = self.post(raw_body="[]")
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "empty")

    def test_json_string_body_is_not_a_500(self):
        response = self.post(raw_body='"hi"')
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "empty")

    def test_json_number_body_is_not_a_500(self):
        response = self.post(raw_body="5")
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "empty")

    def test_json_null_body_is_not_a_500(self):
        response = self.post(raw_body="null")
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "empty")


class TestBodyCap(WorkerCase):
    """The size cap runs before the parser, and before policy."""

    def test_oversized_body_is_rejected_before_parsing(self):
        # Deliberately not JSON. Parsing first would answer 'empty';
        # only a cap that runs first can answer 'message_too_long'.
        response = self.post(raw_body="x" * (entry.MAX_BODY + 1))
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "message_too_long")
        self.assertEqual(self.rows(), [])

    def test_body_exactly_at_the_cap_is_accepted(self):
        base = {"name": "Bret", "message": "hi", "website": "", "pad": ""}
        overhead = len(json.dumps(base))
        base["pad"] = "p" * (entry.MAX_BODY - overhead)
        raw = json.dumps(base)
        self.assertEqual(len(raw), entry.MAX_BODY)
        self.assertEqual(self.post(raw_body=raw).status, 201)


class TestChallengeSeam(WorkerCase):
    def _force(self, result):
        original = entry.verify_challenge
        self.addCleanup(setattr, entry, "verify_challenge", original)
        entry.verify_challenge = lambda request: result

    def test_failed_challenge_is_a_blocked_400(self):
        self._force(False)
        response = self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "blocked")

    def test_failed_challenge_stores_nothing(self):
        # A challenge failure is a bot, not a misfire worth auditing.
        self._force(False)
        self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertEqual(self.rows(), [])

    def test_passing_challenge_still_reaches_storage(self):
        self._force(True)
        self.assertEqual(
            self.post({"name": "Bret", "message": "hi",
                       "website": ""}).status,
            201,
        )


class TestIpPrivacy(WorkerCase):
    def test_stored_hash_is_the_documented_digest(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertEqual(self.rows()[0]["ip_hash"], expected_ip_hash(IP))

    def test_stored_hash_is_thirty_two_hex_characters(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        stored = self.rows()[0]["ip_hash"]
        self.assertEqual(len(stored), 32)
        int(stored, 16)

    def test_no_raw_address_reaches_the_database(self):
        self.post({"name": "Bret", "message": f"my ip is {IP}",
                   "website": ""})
        # The message column is the visitor's own text and may legally
        # contain anything; every other column must be free of it.
        for row in self.rows():
            scrubbed = {k: v for k, v in row.items() if k != "message"}
            self.assertNotIn(IP, json.dumps(scrubbed))

    def test_no_raw_address_reaches_a_response(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertNotIn(IP, self.get().body)
        self.assertNotIn(IP, self.admin().body)

    def test_salt_changes_the_hash(self):
        # Rotating RATE_SALT resets rate-limit history; that only holds
        # if the salt is actually part of the digest.
        self.env.RATE_SALT = "a-different-salt"
        self.post({"name": "Bret", "message": "hi", "website": ""})
        self.assertNotEqual(self.rows()[0]["ip_hash"], expected_ip_hash(IP))
        self.assertEqual(
            self.rows()[0]["ip_hash"],
            expected_ip_hash(IP, salt="a-different-salt"),
        )

    def test_missing_address_header_falls_back(self):
        response = self.fetch(_Request(method="POST", path="/entries",
                                       body=json.dumps({"name": "Bret",
                                                        "message": "hi",
                                                        "website": ""})))
        self.assertEqual(response.status, 201)
        self.assertEqual(self.rows()[0]["ip_hash"], expected_ip_hash("unknown"))

    def test_admin_listing_omits_the_hash_column(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        listed = self.payload(self.admin())["entries"]
        self.assertNotIn("ip_hash", listed[0])


class TestRateLimit(WorkerCase):
    def _submit(self, index, ip=IP):
        return self.post({"name": f"R{index}", "message": f"m{index}",
                          "website": ""}, ip=ip)

    def test_fourth_rapid_submission_is_429(self):
        codes = [self._submit(i).status for i in range(1, 5)]
        self.assertEqual(codes, [201, 201, 201, 429])

    def test_rate_limited_response_carries_the_documented_code(self):
        for i in range(1, 4):
            self._submit(i)
        response = self._submit(4)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "rate_limited"})

    def test_rate_limited_submission_stores_nothing(self):
        for i in range(1, 4):
            self._submit(i)
        self._submit(4)
        self.assertEqual(len(self.rows()), 3)

    def test_the_cap_is_per_address(self):
        for i in range(1, 4):
            self._submit(i)
        self.assertEqual(self._submit(9, ip=OTHER_IP).status, 201)

    def test_blocked_entries_count_toward_the_burst_cap(self):
        self.use_blocklist(BLOCKED_TERM)
        for i in range(1, 4):
            self.post({"name": f"B{i}", "message": BLOCKED_TERM,
                       "website": ""})
        self.assertEqual(self._submit(4).status, 429)

    def _backdate(self, count, age, ip=IP):
        for _ in range(count):
            self.insert(ip_hash=expected_ip_hash(ip), created_at=_stamp(age))

    # The counts and ages below are written as literals on purpose.
    # Phrasing them as entry.DAILY_MAX would make the test move with the
    # constant it is supposed to be pinning, and every off-by-one mutant
    # would survive.

    def test_burst_window_reaches_back_ten_minutes(self):
        # Five minutes old: inside the burst window, so still counted.
        # A narrower window would let this through on the daily cap.
        self._backdate(3, timedelta(minutes=5))
        self.assertEqual(self._submit(1).status, 429)

    def test_history_older_than_the_burst_window_stops_counting(self):
        self._backdate(3, timedelta(minutes=11))
        self.assertEqual(self._submit(1).status, 201)

    def test_daily_cap_is_ten(self):
        # Twelve hours old: well past the burst window, well inside the
        # daily one, so only the daily cap can produce this 429.
        self._backdate(10, timedelta(hours=12))
        self.assertEqual(self._submit(1).status, 429)

    def test_nine_in_a_day_still_passes(self):
        self._backdate(9, timedelta(hours=12))
        self.assertEqual(self._submit(1).status, 201)

    def test_history_older_than_a_day_does_not_count(self):
        self._backdate(20, timedelta(hours=25))
        self.assertEqual(self._submit(1).status, 201)

    def test_burst_history_from_another_address_does_not_count(self):
        self._backdate(20, timedelta(minutes=1), ip=OTHER_IP)
        self.assertEqual(self._submit(1).status, 201)


class TestGetEntries(WorkerCase):
    def test_returns_the_stored_entry(self):
        self.post({"name": "Bret", "message": "nice site", "website": ""})
        entries = self.payload(self.get())["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "Bret")
        self.assertEqual(entries[0]["message_display"], "nice site")
        self.assertEqual(entries[0]["message_raw"], "nice site")
        self.assertIs(entries[0]["has_swap"], False)

    def test_entry_shape_is_the_documented_contract(self):
        self.post({"name": "Bret", "message": "hi", "website": ""})
        entries = self.payload(self.get())["entries"]
        self.assertEqual(
            set(entries[0]),
            {"id", "name", "message_display", "message_raw", "has_swap",
             "created_at"},
        )

    def test_newest_first(self):
        for i in range(3):
            self.insert(name=f"N{i}")
        names = [e["name"] for e in self.payload(self.get())["entries"]]
        self.assertEqual(names, ["N2", "N1", "N0"])

    def test_hidden_entries_are_excluded(self):
        self.insert(name="Visible")
        self.insert(name="Gone", hidden=1, block_reason="slur")
        names = [e["name"] for e in self.payload(self.get())["entries"]]
        self.assertEqual(names, ["Visible"])

    def test_empty_guestbook_returns_an_empty_list(self):
        self.assertEqual(self.payload(self.get()), {"entries": []})

    # 25 and 100 are written out rather than read from entry, for the
    # same reason as the rate-limit counts: a test phrased in terms of
    # the constant it is pinning moves with every mutation of it.

    def test_default_limit_is_twenty_five(self):
        for i in range(30):
            self.insert(name=f"N{i}")
        self.assertEqual(len(self.payload(self.get())["entries"]), 25)

    def test_explicit_limit(self):
        for i in range(10):
            self.insert(name=f"N{i}")
        self.assertEqual(
            len(self.payload(self.get("limit=4"))["entries"]), 4)

    def test_limit_is_clamped_to_one_hundred(self):
        for i in range(105):
            self.insert(name=f"N{i}")
        self.assertEqual(
            len(self.payload(self.get("limit=9999"))["entries"]), 100)

    def test_unparseable_limit_falls_back_to_the_default(self):
        for i in range(30):
            self.insert(name=f"N{i}")
        self.assertEqual(
            len(self.payload(self.get("limit=abc"))["entries"]), 25)

    def test_zero_limit_is_raised_to_one(self):
        for i in range(3):
            self.insert(name=f"N{i}")
        self.assertEqual(len(self.payload(self.get("limit=0"))["entries"]), 1)

    def test_negative_limit_is_raised_to_one(self):
        for i in range(3):
            self.insert(name=f"N{i}")
        self.assertEqual(len(self.payload(self.get("limit=-7"))["entries"]), 1)

    def test_other_query_parameters_are_ignored(self):
        self.insert(name="Only")
        entries = self.payload(self.get("offset=5&sort=asc"))["entries"]
        self.assertEqual(len(entries), 1)


class TestReadPathAppliesSwapOnly(WorkerCase):
    """The read path softens and nothing else — re-running the full policy
    per row would let a grown denylist fail a stored entry and fall back
    to serving the raw, unswapped text."""

    def test_swap_is_applied_at_read_time(self):
        self.insert(message=f"hey {SWAP_IN} you")
        entries = self.payload(self.get())["entries"]
        self.assertEqual(entries[0]["message_display"], f"hey {SWAP_OUT} you")
        self.assertEqual(entries[0]["message_raw"], f"hey {SWAP_IN} you")
        self.assertIs(entries[0]["has_swap"], True)

    def test_a_grown_denylist_does_not_change_a_stored_entry(self):
        # The swapped term is now also on the denylist. Re-running the
        # policy here would fail the check and expose the raw text.
        self.insert(message=f"hey {SWAP_IN} you")
        self.use_blocklist(SWAP_IN, BLOCKED_TERM)
        entries = self.payload(self.get())["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["message_display"], f"hey {SWAP_OUT} you")

    def test_a_stored_url_is_still_served(self):
        # check_message would reject this outright. The read path is not
        # allowed to retroactively unpublish an approved entry.
        self.insert(message="see example.com now")
        entries = self.payload(self.get())["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["message_display"], "see example.com now")

    def test_a_stored_overlong_message_is_still_served(self):
        self.insert(message="m" * 900)
        entries = self.payload(self.get())["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]["message_raw"]), 900)

    def test_names_are_never_swapped(self):
        # The swap is a message-rendering rule. check_name never swaps,
        # and neither does the read path.
        self.insert(name=SWAP_IN, message="hello")
        entries = self.payload(self.get())["entries"]
        self.assertEqual(entries[0]["name"], SWAP_IN)


class TestAdminAuth(WorkerCase):
    """Bearer-token auth on /admin/*.

    Not pinned: swapping hmac.compare_digest for `==` is an equivalent
    mutation from outside — both answer 401, and the timing difference is
    invisible to a behavioural assertion.
    """

    def test_no_header_is_401(self):
        response = self.admin(token=None)
        self.assertEqual(response.status, 401)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "unauthorized"})

    def test_wrong_token_is_401(self):
        self.assertEqual(self.admin(token="nope").status, 401)

    def test_token_prefix_is_not_enough(self):
        self.assertEqual(
            self.admin(token=ADMIN_TOKEN[:-1]).status, 401)

    def test_token_with_extra_characters_is_401(self):
        self.assertEqual(self.admin(token=ADMIN_TOKEN + "x").status, 401)

    def test_wrong_scheme_is_401(self):
        self.assertEqual(
            self.admin(raw_header="Token " + ADMIN_TOKEN).status, 401)

    def test_bare_token_without_a_scheme_is_401(self):
        self.assertEqual(self.admin(raw_header=ADMIN_TOKEN).status, 401)

    def test_lowercase_bearer_is_401(self):
        self.assertEqual(
            self.admin(raw_header="bearer " + ADMIN_TOKEN).status, 401)

    def test_non_ascii_token_is_401_not_a_crash(self):
        # hmac.compare_digest raises TypeError on a str holding a
        # non-ASCII code point. Comparing the header text directly would
        # let any client turn the admin endpoint into a 500.
        self.assertEqual(self.admin(token="tokén").status, 401)

    def test_empty_bearer_token_is_401(self):
        self.assertEqual(self.admin(raw_header="Bearer ").status, 401)

    def test_correct_token_is_200(self):
        self.assertEqual(self.admin().status, 200)

    def test_auth_runs_before_routing(self):
        # An unauthenticated caller must not be able to map the admin
        # surface by watching 404s come back instead of 401s.
        self.assertEqual(
            self.admin(path="/admin/nonsense", token=None).status, 401)


class TestAdminListing(WorkerCase):
    def test_hidden_entries_are_included(self):
        self.insert(name="Visible")
        self.insert(name="Hidden", hidden=1, block_reason="slur")
        names = [e["name"] for e in self.payload(self.admin())["entries"]]
        self.assertEqual(sorted(names), ["Hidden", "Visible"])

    def test_moderation_columns_are_exposed(self):
        self.insert(name="Hidden", hidden=1, block_reason="slur")
        listed = self.payload(self.admin())["entries"][0]
        self.assertEqual(listed["hidden"], 1)
        self.assertEqual(listed["block_reason"], "slur")
        self.assertEqual(listed["message"], "hello")

    def test_listing_is_newest_first(self):
        for i in range(3):
            self.insert(name=f"N{i}")
        names = [e["name"] for e in self.payload(self.admin())["entries"]]
        self.assertEqual(names, ["N2", "N1", "N0"])


class TestAdminModeration(WorkerCase):
    def test_hide_unhide_round_trip(self):
        entry_id = self.insert(name="Rude")
        self.assertEqual(
            len(self.payload(self.get())["entries"]), 1)

        hidden = self.admin(path=f"/admin/entries/{entry_id}/hide",
                            method="POST")
        self.assertEqual(hidden.status, 200)
        self.assertEqual(self.payload(hidden), {"ok": True})
        self.assertEqual(self.payload(self.get())["entries"], [])
        self.assertEqual(self.rows()[0]["hidden"], 1)
        self.assertEqual(self.rows()[0]["block_reason"], "manual")

        shown = self.admin(path=f"/admin/entries/{entry_id}/unhide",
                           method="POST")
        self.assertEqual(shown.status, 200)
        self.assertEqual(
            len(self.payload(self.get())["entries"]), 1)
        self.assertEqual(self.rows()[0]["hidden"], 0)
        self.assertIsNone(self.rows()[0]["block_reason"])

    def test_hide_only_touches_the_named_entry(self):
        first = self.insert(name="Keep")
        second = self.insert(name="Drop")
        self.admin(path=f"/admin/entries/{second}/hide", method="POST")
        by_id = {row["id"]: row["hidden"] for row in self.rows()}
        self.assertEqual(by_id[first], 0)
        self.assertEqual(by_id[second], 1)

    def test_unhide_clears_a_slur_block(self):
        entry_id = self.insert(name="Misfire", hidden=1, block_reason="slur")
        self.admin(path=f"/admin/entries/{entry_id}/unhide", method="POST")
        self.assertEqual(self.rows()[0]["hidden"], 0)
        self.assertIsNone(self.rows()[0]["block_reason"])

    def test_moderation_requires_post(self):
        # A state change reachable by GET is one crawler or link
        # prefetcher away from firing itself.
        entry_id = self.insert(name="Rude")
        response = self.admin(path=f"/admin/entries/{entry_id}/hide",
                              method="GET")
        self.assertEqual(response.status, 404)
        self.assertEqual(self.rows()[0]["hidden"], 0)

    def test_unknown_action_is_404(self):
        entry_id = self.insert()
        response = self.admin(path=f"/admin/entries/{entry_id}/purge",
                              method="POST")
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "not_found"})

    def test_unknown_admin_path_is_404(self):
        self.assertEqual(self.admin(path="/admin/nonsense").status, 404)

    def test_admin_root_is_404(self):
        self.assertEqual(self.admin(path="/admin").status, 404)

    def test_short_admin_path_is_404(self):
        self.assertEqual(
            self.admin(path="/admin/entries/1", method="POST").status, 404)

    def test_wrong_collection_is_404(self):
        self.assertEqual(
            self.admin(path="/admin/users/1/hide", method="POST").status, 404)

    def test_unknown_id_reports_success_and_changes_nothing(self):
        # KNOWN GAP, pinned so a change here is deliberate: an UPDATE that
        # matches no row still answers {"ok": true}.
        self.insert(name="Keep")
        response = self.admin(path="/admin/entries/9999/hide", method="POST")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.rows()[0]["hidden"], 0)

    def test_non_numeric_id_changes_nothing(self):
        self.insert(name="Keep")
        self.admin(path="/admin/entries/abc/hide", method="POST")
        self.assertEqual(self.rows()[0]["hidden"], 0)


class TestRouting(WorkerCase):
    def test_unknown_path_is_404(self):
        response = self.fetch(_Request(path="/nope"))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response),
                         {"ok": False, "code": "not_found"})

    def test_root_is_404(self):
        self.assertEqual(self.fetch(_Request(path="/")).status, 404)

    def test_trailing_slash_is_not_the_entries_route(self):
        self.assertEqual(self.fetch(_Request(path="/entries/")).status, 404)

    def test_delete_on_entries_is_404(self):
        response = self.fetch(_Request(method="DELETE", path="/entries"))
        self.assertEqual(response.status, 404)

    def test_put_on_entries_is_404(self):
        self.assertEqual(
            self.fetch(_Request(method="PUT", path="/entries")).status, 404)

    def test_head_on_entries_is_404(self):
        self.assertEqual(
            self.fetch(_Request(method="HEAD", path="/entries")).status, 404)

    def test_a_path_merely_starting_with_admin_is_not_admin(self):
        # A bare startswith("/admin") would answer /administrivia with an
        # auth challenge, advertising the admin surface to anyone probing.
        response = self.fetch(_Request(path="/administrivia"))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response)["code"], "not_found")

    def test_wrong_method_does_not_store_anything(self):
        self.fetch(_Request(method="DELETE", path="/entries",
                            body=json.dumps({"name": "X", "message": "y"})))
        self.assertEqual(self.rows(), [])


class TestCors(WorkerCase):
    def _origin(self, response):
        return response.headers["Access-Control-Allow-Origin"]

    def test_preflight_is_204_with_no_body(self):
        response = self.fetch(_Request(method="OPTIONS", path="/entries"))
        self.assertEqual(response.status, 204)
        self.assertEqual(response.body, "")

    def test_preflight_carries_cors_headers(self):
        response = self.fetch(_Request(method="OPTIONS", path="/entries"))
        self.assertEqual(self._origin(response), ORIGIN)
        self.assertEqual(response.headers["Access-Control-Allow-Methods"],
                         "GET, POST, OPTIONS")
        self.assertIn("Content-Type",
                      response.headers["Access-Control-Allow-Headers"])
        self.assertIn("Authorization",
                      response.headers["Access-Control-Allow-Headers"])

    def test_preflight_answers_before_routing(self):
        response = self.fetch(_Request(method="OPTIONS", path="/nope"))
        self.assertEqual(response.status, 204)

    def test_origin_is_named_exactly_never_a_wildcard(self):
        responses = [
            self.post({"name": "Bret", "message": "hi", "website": ""}),
            self.post({"name": "", "message": "", "website": ""}),
            self.get(),
            self.admin(token=None),
            self.admin(),
            self.fetch(_Request(path="/nope")),
            self.fetch(_Request(method="OPTIONS", path="/entries")),
        ]
        for response in responses:
            with self.subTest(status=response.status):
                self.assertEqual(self._origin(response), ORIGIN)
                self.assertNotIn("*", self._origin(response))

    def test_rate_limited_response_still_carries_cors(self):
        for i in range(3):
            self.post({"name": f"R{i}", "message": "hi", "website": ""})
        response = self.post({"name": "R4", "message": "hi", "website": ""})
        self.assertEqual(response.status, 429)
        self.assertEqual(self._origin(response), ORIGIN)

    def test_origin_comes_from_the_binding(self):
        self.env.ALLOWED_ORIGIN = "https://example.test"
        self.assertEqual(self._origin(self.get()), "https://example.test")

    def test_responses_are_json(self):
        response = self.get()
        self.assertEqual(response.headers["Content-Type"], "application/json")
        json.loads(response.body)


class TestPyodideRowShape(WorkerCase):
    """Every read path, with rows shaped the way Pyodide delivers them —
    JsProxy, no subscripting, no dict(). The rest of the file runs
    against plain dicts; both shapes are real, so both are exercised."""

    row_factory = _JsRow

    def test_public_read(self):
        self.insert(name="Bret", message=f"hey {SWAP_IN} you")
        entries = self.payload(self.get())["entries"]
        self.assertEqual(entries[0]["name"], "Bret")
        self.assertEqual(entries[0]["message_display"], f"hey {SWAP_OUT} you")

    def test_admin_read(self):
        self.insert(name="Hidden", hidden=1, block_reason="slur")
        listed = self.payload(self.admin())["entries"]
        self.assertEqual(listed[0]["block_reason"], "slur")

    def test_rate_limit_count(self):
        for i in range(3):
            self.post({"name": f"R{i}", "message": "hi", "website": ""})
        self.assertEqual(
            self.post({"name": "R4", "message": "hi", "website": ""}).status,
            429,
        )

    def test_write_then_read_back(self):
        self.assertEqual(
            self.post({"name": "Bret", "message": "hi", "website": ""}).status,
            201,
        )
        self.assertEqual(
            self.payload(self.get())["entries"][0]["name"], "Bret")


if __name__ == "__main__":
    unittest.main()
