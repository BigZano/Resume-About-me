"""Guards the live Armory Bot numbers on the Workshop and About Me pages.

The pages carry static text ("35 servers", "70,000+") and
static/armory-stats.js replaces it in the browser with the figures from
the bot's public stats API. The static text is the layer that stays when
the script never runs or the answer can't be trusted.

`TestMarkup` and `TestRenderedPages` pin the contract the script depends
on: the spans, their fallback text, and the script tag on each page that
needs it. `TestScriptSource` guards invariants unsafe to discover at
runtime (text only, never a console write). `TestStatsText` runs the pure
formatting function under node. `TestScriptBehaviour` runs the real
script against a stub DOM and stub fetch in node. Both node classes skip
themselves where node isn't installed.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from Gen_Content.generate_page import generate_page  # noqa: E402
from Gen_Content.generate_static_page import (  # noqa: E402
    generate_static_page,
)

STATS_JS = ROOT / "static" / "armory-stats.js"
WORKSHOP = ROOT / "workshop.html"
TEMPLATE = ROOT / "template.html"
ABOUT_ME = ROOT / "content" / "aboutme.md"

SCRIPT_TAG = '<script src="./armory-stats.js?v=1" defer></script>'

WORKSHOP_USED_BY = (
    '<dd><span data-stat="armory-servers">35 servers</span>, with '
    '<span data-stat="armory-members">70,000+</span> members between '
    "them</dd>"
)
ABOUT_ME_SENTENCE = (
    'Today it sits in <span data-stat="armory-servers">35 servers</span> '
    'with <span data-stat="armory-members">70,000+</span> members between '
    "them."
)


def _scripts_before_body_end(markup):
    """True when the stats script is the last thing before </body>."""
    return re.search(
        re.escape(SCRIPT_TAG) + r"\s*</body>", markup
    ) is not None


class TestMarkup(unittest.TestCase):
    def test_script_exists_in_static(self):
        self.assertTrue(STATS_JS.is_file())

    def test_workshop_loads_the_script_last(self):
        markup = WORKSHOP.read_text(encoding="utf-8")
        self.assertTrue(_scripts_before_body_end(markup))

    def test_shared_template_loads_the_script_last(self):
        markup = TEMPLATE.read_text(encoding="utf-8")
        self.assertTrue(_scripts_before_body_end(markup))

    def test_script_is_deferred_so_the_spans_exist_when_it_runs(self):
        for path in (WORKSHOP, TEMPLATE):
            with self.subTest(page=path.name):
                markup = path.read_text(encoding="utf-8")
                self.assertRegex(
                    markup, r'<script src="\./armory-stats\.js[^"]*" defer>'
                )

    def test_workshop_used_by_line_carries_the_spans_and_fallback(self):
        markup = WORKSHOP.read_text(encoding="utf-8")
        self.assertIn(WORKSHOP_USED_BY, markup)

    def test_workshop_servers_span_holds_the_word_too(self):
        """The script writes "N servers" whole, so the fallback must read
        the same way or the page jumps from "35" + " servers" to a
        different shape once the live text lands."""
        markup = WORKSHOP.read_text(encoding="utf-8")
        self.assertIn('<span data-stat="armory-servers">35 servers</span>',
                      markup)
        self.assertNotIn('armory-servers">35</span>', markup)

    def test_workshop_todo_is_replaced_by_a_note_about_the_script(self):
        markup = WORKSHOP.read_text(encoding="utf-8")
        self.assertNotIn("TODO: wire the live figure", markup)
        self.assertRegex(
            markup,
            r"<!--[^>]*armory-stats\.js[^>]*api\.armorybot\.win[^>]*-->",
        )

    def test_about_me_sentence_carries_the_spans_and_fallback(self):
        source = ABOUT_ME.read_text(encoding="utf-8")
        self.assertIn(ABOUT_ME_SENTENCE, source)

    def test_copy_never_calls_the_member_total_people(self):
        """`users` sums members across servers, so one person in three
        servers is counted three times."""
        for label, text in (
            ("workshop", WORKSHOP_USED_BY),
            ("about me", ABOUT_ME_SENTENCE),
        ):
            with self.subTest(page=label):
                self.assertIn("members between them", text)
                self.assertNotIn("people", text)

    def test_each_page_has_one_pair_of_spans(self):
        for path in (WORKSHOP, ABOUT_ME):
            with self.subTest(page=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text.count('data-stat="armory-servers"'), 1)
                self.assertEqual(text.count('data-stat="armory-members"'), 1)


class TestRenderedPages(unittest.TestCase):
    """Runs the real generators, so the spans and the script tag are
    checked as a visitor's browser would receive them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        # The generators locate the site root by walking up to a
        # directory named docs, so the output has to live under one.
        docs = Path(cls.tmp.name) / "docs"
        (docs / "dev_diary").mkdir(parents=True)

        source = Path(cls.tmp.name) / "aboutme.md"
        source.write_text(
            ABOUT_ME.read_text(encoding="utf-8"), encoding="utf-8"
        )
        cls.about = docs / "aboutme.html"
        generate_page(str(source), str(TEMPLATE), str(cls.about))

        post = Path(cls.tmp.name) / "post.md"
        post.write_text(
            "<!-- page-date: 2026-01-01 -->\n# A post\n\nNo stats here.\n",
            encoding="utf-8",
        )
        cls.post = docs / "dev_diary" / "post.html"
        generate_page(
            str(post), str(TEMPLATE), str(cls.post), is_blog_post=True
        )

        cls.workshop = docs / "workshop.html"
        generate_static_page(
            str(WORKSHOP),
            str(cls.workshop),
            {"title": "Workshop", "description": "Things I have built."},
            "/workshop.html",
        )

    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_converter_passes_the_about_me_spans_through_untouched(self):
        self.assertIn(
            '<span data-stat="armory-servers">35 servers</span> with '
            '<span data-stat="armory-members">70,000+</span> members '
            "between them.",
            self.read(self.about),
        )

    def test_about_me_page_loads_the_script(self):
        self.assertIn(SCRIPT_TAG, self.read(self.about))

    def test_workshop_page_keeps_spans_and_loads_the_script(self):
        page = self.read(self.workshop)
        self.assertIn(WORKSHOP_USED_BY, page)
        self.assertIn(SCRIPT_TAG, page)

    def test_subdirectory_pages_get_a_working_script_path(self):
        """generate_page rewrites src="./ for pages in a subdirectory, so
        a ./ src in the template resolves to the site root from there."""
        page = self.read(self.post)
        self.assertIn(
            '<script src="../armory-stats.js?v=1" defer></script>', page
        )
        self.assertNotIn(SCRIPT_TAG, page)

    def test_a_page_without_the_spans_still_loads_the_script(self):
        """The script is in the shared template and no-ops by itself, so
        there is no per-page switch to forget."""
        page = self.read(self.post)
        self.assertNotIn("data-stat", page)
        self.assertIn("armory-stats.js", page)


class TestScriptSource(unittest.TestCase):
    def setUp(self):
        self.js = STATS_JS.read_text(encoding="utf-8")

    def test_never_injects_html(self):
        """The numbers come from a third-party origin. Text only."""
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("outerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("document.write", self.js)
        self.assertNotIn("createContextualFragment", self.js)

    def test_writes_with_textcontent(self):
        self.assertIn("textContent", self.js)

    def test_never_touches_the_console(self):
        self.assertNotIn("console", self.js)

    def test_targets_the_public_stats_endpoint(self):
        self.assertIn("https://api.armorybot.win/api/stats", self.js)

    def test_requests_without_credentials(self):
        self.assertIn('credentials: "omit"', self.js)

    def test_has_no_dependencies(self):
        for needle in ("import ", "require(", "XMLHttpRequest"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.js)


MODULE_HARNESS = r"""
// Loads the script the way `require` does and exercises the pure
// function. A fetch or a document that gets touched during load is
// reported, because loading as a module must have no side effects.
let touched = 0;
globalThis.fetch = function () {
  touched += 1;
  return Promise.reject(new Error("fetch during module load"));
};
globalThis.document = {
  querySelectorAll: function () { touched += 1; return []; },
  querySelector: function () { touched += 1; return null; }
};

const mod = require(process.argv[2]);
const cases = JSON.parse(process.argv[3]);

setTimeout(() => {
  process.stdout.write(JSON.stringify({
    exports: Object.keys(mod),
    results: cases.map((c) => mod.armoryStatsText(c)),
    touched: touched
  }));
}, 10);
"""


HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const scenario = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const source = fs.readFileSync(process.argv[2], "utf8");

const problems = [];

// <span data-stat="...">fallback text</span>. Every write is counted, so
// "left alone" can be asserted as "never written to", not just "reads the
// same afterwards".
function Span(stat, text) {
  this.stat = stat;
  this.text = text;
  this.writes = 0;
}
Object.defineProperty(Span.prototype, "textContent", {
  get: function () { return this.text; },
  set: function (v) {
    if (typeof v !== "string") { problems.push("non-string textContent"); }
    this.text = String(v);
    this.writes += 1;
  }
});
["innerHTML", "outerHTML"].forEach(function (sink) {
  Object.defineProperty(Span.prototype, sink, {
    get: function () { return ""; },
    set: function () { problems.push(sink + " assigned"); }
  });
});
Span.prototype.insertAdjacentHTML = function () {
  problems.push("insertAdjacentHTML called");
};

const page = Object.assign(
  { servers: ["35 servers"], members: ["70,000+"] },
  scenario.page || {}
);
const servers = page.servers.map((t) => new Span("armory-servers", t));
const members = page.members.map((t) => new Span("armory-members", t));
const everything = servers.concat(members);

function select(sel) {
  const m = /^\[data-stat="([^"]+)"\]$/.exec(sel);
  if (!m) {
    problems.push("unsupported selector: " + sel);
    return [];
  }
  return everything.filter((el) => el.stat === m[1]);
}

const fetchCalls = [];
let lastSignal = null;

function abortError() {
  const err = new Error("The operation was aborted.");
  err.name = "AbortError";
  return err;
}

function onAbort(signal, reject) {
  if (signal) {
    signal.addEventListener("abort", () => reject(abortError()));
  }
}

function fetchStub(url, options) {
  options = options || {};
  lastSignal = options.signal || null;
  fetchCalls.push({
    url: url,
    credentials: options.credentials,
    hasSignal: !!options.signal
  });
  const mode = scenario.fetch;
  if (mode === "throw") {
    throw new TypeError("fetch threw synchronously");
  }
  if (mode === "reject") {
    return Promise.reject(new TypeError("Failed to fetch"));
  }
  if (mode === "status") {
    return Promise.resolve({
      ok: false, status: 503, json: () => Promise.resolve(scenario.body)
    });
  }
  if (mode === "badjson") {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token"))
    });
  }
  if (mode === "hang") {
    // Never answers. Only the abort signal ends it, like a real fetch.
    return new Promise((resolve, reject) => onAbort(options.signal, reject));
  }
  if (mode === "stalledbody") {
    // Headers arrive, the body never does.
    return Promise.resolve({
      ok: true, status: 200,
      json: () => new Promise((resolve, reject) => onAbort(options.signal, reject))
    });
  }
  return Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve(scenario.body)
  });
}

// Fake timers, so the 5 s timeout can be fired on demand instead of
// waited out.
const timers = [];
function setTimeoutStub(fn, ms) {
  timers.push({ fn: fn, ms: ms, cleared: false, fired: false });
  return timers.length;
}
function clearTimeoutStub(id) {
  if (timers[id - 1]) { timers[id - 1].cleared = true; }
}

const sandbox = {
  document: {
    querySelectorAll: select,
    querySelector: (sel) => select(sel)[0] || null,
    getElementById: () => null,
    write: function () { problems.push("document.write called"); }
  },
  fetch: scenario.noFetch ? undefined : fetchStub,
  AbortController: scenario.noAbortController ? undefined : AbortController,
  setTimeout: setTimeoutStub,
  clearTimeout: clearTimeoutStub,
  console: {
    log: () => problems.push("console.log"),
    info: () => problems.push("console.info"),
    debug: () => problems.push("console.debug"),
    warn: (...args) => problems.push("console.warn: " + args.join(" ")),
    error: (...args) => problems.push("console.error: " + args.join(" "))
  }
};
sandbox.globalThis = sandbox;

process.on("uncaughtException", (e) => problems.push("uncaught: " + e.message));
process.on("unhandledRejection", (e) => problems.push("unhandled: " + e));

try {
  vm.runInNewContext(source, sandbox, { filename: "armory-stats.js" });
} catch (e) {
  problems.push("threw at load: " + e.message);
}

function report() {
  process.stdout.write(JSON.stringify({
    servers: servers.map((s) => s.text),
    members: members.map((s) => s.text),
    serverWrites: servers.map((s) => s.writes),
    memberWrites: members.map((s) => s.writes),
    fetchCalls: fetchCalls,
    aborted: lastSignal ? lastSignal.aborted : null,
    timers: timers.map((t) => ({ ms: t.ms, cleared: t.cleared, fired: t.fired })),
    problems: problems
  }));
}

setTimeout(() => {
  if (scenario.fireTimers) {
    timers.forEach((t) => {
      if (!t.cleared) { t.fired = true; t.fn(); }
    });
  }
  setTimeout(report, 30);
}, 20);
"""


def _payload(**overrides):
    body = {
        "guilds": 36,
        "users": 71933,
        "transactions": 150,
        "latency_ms": 88.66,
        "is_ready": True,
        "timestamp": "2026-11-25T22:00:00Z",
    }
    body.update(overrides)
    return body


def _without(key):
    body = _payload()
    del body[key]
    return body


# Each of these must leave the page exactly as the markup shipped it.
UNTRUSTWORTHY = {
    "not ready": _payload(is_ready=False),
    "ready is the string true": _payload(is_ready="true"),
    "ready is 1": _payload(is_ready=1),
    "ready missing": _without("is_ready"),
    "guilds missing": _without("guilds"),
    "users missing": _without("users"),
    "guilds zero": _payload(guilds=0),
    "users zero": _payload(users=0),
    "guilds negative": _payload(guilds=-3),
    "users negative": _payload(users=-71933),
    "guilds fractional": _payload(guilds=35.5),
    "users fractional": _payload(users=71933.25),
    "guilds a numeric string": _payload(guilds="35"),
    "users a numeric string": _payload(users="71933"),
    "guilds null": _payload(guilds=None),
    "users null": _payload(users=None),
    "guilds boolean": _payload(guilds=True),
    "users boolean": _payload(users=True),
    "guilds an object": _payload(guilds={"n": 35}),
    "users an array": _payload(users=[71933]),
    # One good number must not drag the other onto the page alone.
    "good guilds, bad users": _payload(users=0),
    "bad guilds, good users": _payload(guilds=0),
    "empty object": {},
    "null body": None,
    "array body": [_payload()],
    "string body": "ready",
    "number body": 36,
    "boolean body": True,
}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStatsText(unittest.TestCase):
    """The pure half: payload in, the two strings (or None) out."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.harness = Path(tmp.name) / "module_harness.js"
        cls.harness.write_text(MODULE_HARNESS, encoding="utf-8")

    def run_cases(self, *cases):
        result = subprocess.run(
            ["node", str(self.harness), str(STATS_JS), json.dumps(cases)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def text(self, **overrides):
        return self.run_cases(_payload(**overrides))["results"][0]

    def test_exports_the_pure_function(self):
        self.assertIn("armoryStatsText", self.run_cases()["exports"])

    def test_loading_as_a_module_makes_no_request_and_reads_no_page(self):
        self.assertEqual(self.run_cases()["touched"], 0)

    def test_valid_payload_gives_both_strings(self):
        self.assertEqual(
            self.run_cases(_payload())["results"][0],
            {"servers": "36 servers", "members": "71,933"},
        )

    def test_one_server_is_singular(self):
        self.assertEqual(self.text(guilds=1)["servers"], "1 server")

    def test_two_servers_is_plural(self):
        self.assertEqual(self.text(guilds=2)["servers"], "2 servers")

    def test_one_member_is_a_bare_number(self):
        self.assertEqual(self.text(users=1)["members"], "1")

    def test_numbers_are_grouped_with_commas(self):
        out = self.text(guilds=1234, users=1234567)
        self.assertEqual(out["servers"], "1,234 servers")
        self.assertEqual(out["members"], "1,234,567")

    def test_three_digit_numbers_are_not_grouped(self):
        out = self.text(guilds=999, users=999)
        self.assertEqual(out["servers"], "999 servers")
        self.assertEqual(out["members"], "999")

    def test_extra_fields_are_ignored(self):
        self.assertEqual(
            self.text(brand_new_field={"deep": [1, 2, 3]}),
            {"servers": "36 servers", "members": "71,933"},
        )

    def test_untrustworthy_payloads_give_none(self):
        names = list(UNTRUSTWORTHY)
        results = self.run_cases(*UNTRUSTWORTHY.values())["results"]
        for name, result in zip(names, results):
            with self.subTest(payload=name):
                self.assertIsNone(result)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestScriptBehaviour(unittest.TestCase):
    """Runs the shipped script against a stub DOM and a stub fetch, and
    asserts what a visitor is left reading."""

    FALLBACK_SERVERS = "35 servers"
    FALLBACK_MEMBERS = "70,000+"

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.dir = Path(tmp.name)
        cls.harness = cls.dir / "harness.js"
        cls.harness.write_text(HARNESS, encoding="utf-8")
        cls.count = 0

    def run_script(self, **scenario):
        scenario.setdefault("fetch", "ok")
        scenario.setdefault("body", _payload())
        type(self).count += 1
        path = self.dir / f"scenario-{type(self).count}.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            ["node", str(self.harness), str(STATS_JS), str(path)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_fallback_untouched(self, out):
        self.assertEqual(out["servers"], [self.FALLBACK_SERVERS])
        self.assertEqual(out["members"], [self.FALLBACK_MEMBERS])
        self.assertEqual(out["serverWrites"], [0])
        self.assertEqual(out["memberWrites"], [0])

    # -- the live answer -----------------------------------

    def test_valid_payload_fills_the_servers_span(self):
        self.assertEqual(self.run_script()["servers"], ["36 servers"])

    def test_valid_payload_fills_the_members_span(self):
        self.assertEqual(self.run_script()["members"], ["71,933"])

    def test_numbers_are_grouped(self):
        out = self.run_script(body=_payload(guilds=1200, users=1234567))
        self.assertEqual(out["servers"], ["1,200 servers"])
        self.assertEqual(out["members"], ["1,234,567"])

    def test_one_server_reads_singular(self):
        out = self.run_script(body=_payload(guilds=1))
        self.assertEqual(out["servers"], ["1 server"])

    def test_the_words_around_the_spans_are_the_markups_not_the_scripts(self):
        """The members span gets a bare number: "members between them" is
        already in the sentence, and "people" is never written."""
        out = self.run_script()
        self.assertNotIn("members", out["members"][0])
        self.assertNotIn("people", out["members"][0])

    def test_each_span_is_written_exactly_once(self):
        out = self.run_script()
        self.assertEqual(out["serverWrites"], [1])
        self.assertEqual(out["memberWrites"], [1])

    def test_live_numbers_win_even_when_smaller_than_the_fallback(self):
        """The fallback is a stand-in, not a floor: the bot really can
        shrink, and the page should say so."""
        out = self.run_script(body=_payload(guilds=1, users=2))
        self.assertEqual(out["servers"], ["1 server"])
        self.assertEqual(out["members"], ["2"])

    # -- the request ---------------------------------------

    def test_makes_exactly_one_request(self):
        self.assertEqual(len(self.run_script()["fetchCalls"]), 1)

    def test_requests_the_stats_endpoint_without_credentials(self):
        call = self.run_script()["fetchCalls"][0]
        self.assertEqual(call["url"], "https://api.armorybot.win/api/stats")
        self.assertEqual(call["credentials"], "omit")

    def test_request_carries_an_abort_signal(self):
        self.assertTrue(self.run_script()["fetchCalls"][0]["hasSignal"])

    def test_timeout_is_about_five_seconds(self):
        timers = self.run_script()["timers"]
        self.assertEqual([t["ms"] for t in timers], [5000])

    def test_timer_is_cleared_once_the_answer_is_in(self):
        out = self.run_script()
        self.assertTrue(all(t["cleared"] for t in out["timers"]))

    def test_timer_is_cleared_after_a_failure_too(self):
        for mode in ("reject", "status", "badjson"):
            with self.subTest(fetch=mode):
                out = self.run_script(fetch=mode)
                self.assertTrue(all(t["cleared"] for t in out["timers"]))

    # -- pages without the spans ---------------------------

    def test_no_spans_means_no_request(self):
        out = self.run_script(page={"servers": [], "members": []})
        self.assertEqual(out["fetchCalls"], [])

    def test_no_spans_means_no_timer_either(self):
        out = self.run_script(page={"servers": [], "members": []})
        self.assertEqual(out["timers"], [])

    def test_no_spans_is_not_an_error(self):
        out = self.run_script(page={"servers": [], "members": []})
        self.assertEqual(out["problems"], [])

    def test_only_a_members_span_still_asks_and_fills_it(self):
        out = self.run_script(page={"servers": [], "members": ["70,000+"]})
        self.assertEqual(len(out["fetchCalls"]), 1)
        self.assertEqual(out["members"], ["71,933"])
        self.assertEqual(out["problems"], [])

    def test_only_a_servers_span_still_asks_and_fills_it(self):
        out = self.run_script(page={"servers": ["35 servers"], "members": []})
        self.assertEqual(len(out["fetchCalls"]), 1)
        self.assertEqual(out["servers"], ["36 servers"])
        self.assertEqual(out["problems"], [])

    def test_every_matching_span_is_filled(self):
        out = self.run_script(page={
            "servers": ["35 servers", "35 servers"],
            "members": ["70,000+", "70,000+"],
        })
        self.assertEqual(out["servers"], ["36 servers", "36 servers"])
        self.assertEqual(out["members"], ["71,933", "71,933"])

    # -- the fallback stays --------------------------------

    def test_untrustworthy_payloads_leave_the_fallback_alone(self):
        for name, body in UNTRUSTWORTHY.items():
            with self.subTest(payload=name):
                out = self.run_script(body=body)
                self.assertEqual(len(out["fetchCalls"]), 1)
                self.assert_fallback_untouched(out)
                self.assertEqual(out["problems"], [])

    def test_http_error_leaves_the_fallback_alone(self):
        """A 503 whose body happens to look valid is still an outage."""
        out = self.run_script(fetch="status")
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_network_error_leaves_the_fallback_alone(self):
        out = self.run_script(fetch="reject")
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_invalid_json_leaves_the_fallback_alone(self):
        out = self.run_script(fetch="badjson")
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_a_synchronous_throw_from_fetch_leaves_the_fallback_alone(self):
        out = self.run_script(fetch="throw")
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_missing_fetch_leaves_the_fallback_alone(self):
        out = self.run_script(noFetch=True)
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_timeout_aborts_the_request_and_leaves_the_fallback_alone(self):
        out = self.run_script(fetch="hang", fireTimers=True)
        self.assertTrue(out["aborted"])
        self.assertEqual([t["fired"] for t in out["timers"]], [True])
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_a_stalled_body_is_cut_off_by_the_timeout_too(self):
        out = self.run_script(fetch="stalledbody", fireTimers=True)
        self.assertTrue(out["aborted"])
        self.assert_fallback_untouched(out)
        self.assertEqual(out["problems"], [])

    def test_before_the_timeout_the_fallback_is_what_shows(self):
        """No spinner, no placeholder: while the request is in flight the
        markup's own text is on screen."""
        out = self.run_script(fetch="hang")
        self.assertFalse(out["aborted"])
        self.assert_fallback_untouched(out)

    def test_without_abortcontroller_it_still_works(self):
        out = self.run_script(noAbortController=True)
        self.assertEqual(out["servers"], ["36 servers"])
        self.assertEqual(out["members"], ["71,933"])
        self.assertEqual(out["problems"], [])
        self.assertFalse(out["fetchCalls"][0]["hasSignal"])
        self.assertEqual(out["timers"], [])

    # -- general -------------------------------------------

    def test_no_scenario_writes_to_the_console_or_throws(self):
        scenarios = [{}, {"body": None}, {"body": {}}]
        scenarios += [{"fetch": m} for m in
                      ("reject", "status", "badjson", "throw")]
        scenarios += [{"fetch": "hang", "fireTimers": True}]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.assertEqual(self.run_script(**scenario)["problems"], [])

    def test_no_html_sink_is_ever_touched(self):
        """The stub spans record any assignment to innerHTML and friends
        as a problem; a valid payload exercises every write path."""
        self.assertEqual(self.run_script()["problems"], [])


if __name__ == "__main__":
    unittest.main()
