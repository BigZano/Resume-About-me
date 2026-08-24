"""Guards the landing-page guestbook cell: markup, styles, and fallback.

The cell is the only live dependency on the front door of the site, so it
has to fail as a design state rather than as a broken box. Three layers:

    1. fetch OK    -> render the latest mark, write the cache
    2. fetch fails -> render the last known good mark from localStorage
    3. no cache    -> the card goes cold and the static "Sign it" link stands

`TestTitlepageMarkup`, `TestLandingCss` and `TestPageLinks` pin the markup
and build contract the script depends on, so a template edit cannot silently
break it. `TestCellScriptSource` guards the invariants that are unsafe to
discover at runtime (the XSS boundary, `message_raw` never being cached).
`TestCellBehaviour` runs the real script against a stub DOM in node and
asserts what the visitor actually ends up looking at; it skips itself where
node is not installed, so the suite stays dependency-free.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from Gen_Content.generate_landing_page import (  # noqa: E402
    generate_landing_page,
)

CELL_JS = ROOT / "static" / "guestbook-cell.js"


class TestTitlepageMarkup(unittest.TestCase):
    def setUp(self):
        self.markup = (ROOT / "titlepage.html").read_text(encoding="utf-8")

    def test_has_the_guestbook_card(self):
        self.assertIn("into-card--guestbook", self.markup)

    def test_card_has_the_mount_point(self):
        self.assertIn('id="gb-latest"', self.markup)

    def test_card_sits_after_the_cooking_card(self):
        cooking = self.markup.index("<h3>Cooking</h3>")
        guestbook = self.markup.index("into-card--guestbook")
        self.assertGreater(guestbook, cooking)

    def test_card_is_inside_the_into_grid(self):
        grid = self.markup.index('class="into-grid"')
        guestbook = self.markup.index("into-card--guestbook")
        grid_end = self.markup.index("</div>", guestbook)
        self.assertLess(grid, guestbook)
        self.assertLess(guestbook, grid_end)

    def test_loads_the_cell_script(self):
        self.assertIn("guestbook-cell.js", self.markup)

    def test_script_is_deferred(self):
        match = re.search(r'<script[^>]*guestbook-cell\.js[^>]*>', self.markup)
        self.assertIsNotNone(match)
        self.assertIn("defer", match.group(0))

    def test_card_carries_the_signature_slot(self):
        """The script replaces the contents of this node and nothing else."""
        self.assertIn("gb-sig", self.markup)

    def test_card_links_to_the_guestbook_without_javascript(self):
        """Layer 3 made visible: the static markup is already the fallback."""
        card = self.markup.split("into-card--guestbook", 1)[1]
        card = card.split("</article>", 1)[0]
        self.assertIn('href="guestbook.html"', card)

    def test_no_element_carries_a_bare_guestbook_class(self):
        """static/index.css hides `.guestbook` on paper. A bare class here
        would blank the cell in print with no error anywhere."""
        for attr in re.findall(r'class="([^"]*)"', self.markup):
            self.assertNotIn("guestbook", attr.split())


class TestLandingCss(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "static" / "landing.css").read_text(encoding="utf-8")

    def test_styles_the_guestbook_card(self):
        self.assertIn(".into-card--guestbook", self.css)

    def test_defines_the_blackout_state(self):
        self.assertIn("is-cold", self.css)

    def test_defines_the_live_state(self):
        self.assertIn("is-live", self.css)

    def test_defines_the_cached_state(self):
        self.assertIn("is-cached", self.css)

    def test_does_not_rewrite_the_grid_template(self):
        # The auto-fit grid already absorbs a 4th card. Rewriting it is a
        # regression, not a fix.
        self.assertIn("repeat(auto-fit,minmax(190px,1fr))",
                      self.css.replace(" ", ""))

    def test_defines_no_new_colour_values(self):
        """The forge palette lives in index.css. This file reuses it."""
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.css))
        self.assertNotIn("rgb(", self.css)
        self.assertNotIn("hsl(", self.css)

    def test_cell_rules_are_scoped_to_the_landing_body(self):
        for line in self.css.splitlines():
            if ".into-card--guestbook" not in line:
                continue
            self.assertIn("body.landing", line)

    def test_cold_card_stays_readable_on_paper(self):
        """index.css prints black on white. Cooling text to --iron there
        would print an empty card."""
        self.assertIn("@media print", self.css)


class TestPageLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.content = Path(self.tmp) / "content"
        self.content.mkdir()
        (self.content / "aboutme.md").write_text(
            "# About Me\n", encoding="utf-8"
        )
        self.dest = Path(self.tmp) / "index.html"

    def _generate(self):
        generate_landing_page(
            str(self.content),
            str(ROOT / "titlepage.html"),
            str(self.dest),
            {"site_title": "T", "site_author": "A",
             "title": "t", "description": "d", "site_description": "sd"},
        )
        return self.dest.read_text(encoding="utf-8")

    def test_guestbook_link_is_in_page_links(self):
        self.assertIn('href="guestbook.html"', self._generate())

    def test_guestbook_link_is_labelled(self):
        self.assertIn(">Guestbook<", self._generate())

    def test_guestbook_link_is_inside_the_page_links_list(self):
        page = self._generate()
        nav = page.split('class="page-links"', 1)[1].split("</ul>", 1)[0]
        self.assertIn('href="guestbook.html"', nav)

    def test_no_unsubstituted_placeholders_remain(self):
        self.assertNotIn("{{", self._generate())

    def test_existing_pages_still_render(self):
        self.assertIn('href="aboutme.html"', self._generate())

    def test_guestbook_link_survives_an_empty_content_directory(self):
        """A clone with no markdown must still reach the guestbook."""
        empty = Path(self.tmp) / "empty"
        empty.mkdir()
        dest = Path(self.tmp) / "empty.html"
        generate_landing_page(
            str(empty), str(ROOT / "titlepage.html"), str(dest),
            {"site_title": "T", "site_author": "A", "title": "t",
             "description": "d", "site_description": "sd"},
        )
        self.assertIn('href="guestbook.html"',
                      dest.read_text(encoding="utf-8"))


def _code_only(source):
    """The script with `/* ... */` comments removed.

    The invariants below are about what the code does, not about what the
    prose says. Line comments are deliberately left alone: `//` also opens
    the scheme of the Worker URL, and stripping to end-of-line would eat
    the code this is meant to inspect.
    """
    return re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)


def _try_block_spans(source):
    """(start, end) character spans of every `try { ... }` block."""
    spans = []
    for match in re.finditer(r"\btry\s*\{", source):
        start = match.end() - 1
        depth = 0
        for i in range(start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((start, i))
                    break
    return spans


class TestCellScriptSource(unittest.TestCase):
    def setUp(self):
        self.js = CELL_JS.read_text(encoding="utf-8")
        self.code = _code_only(self.js)

    def test_never_injects_html(self):
        """The XSS boundary. The Worker does not sanitise; the client must
        build nodes, never parse strings."""
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("outerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("document.write", self.js)

    def test_renders_entry_text_with_textcontent(self):
        self.assertIn("textContent", self.js)

    def test_never_touches_message_raw(self):
        """A hidden entry must not resurface unswapped from a stale cache.
        The cell has no reveal toggle, so it has no reason to know the raw
        text at all."""
        self.assertNotIn("message_raw", self.code)

    def test_uses_the_agreed_cache_key(self):
        self.assertIn('"gb_cache"', self.js)

    def test_cache_expires_after_24_hours(self):
        self.assertIn("24 * 60 * 60 * 1000", self.js)

    def test_every_localstorage_access_is_inside_a_try_block(self):
        """Private browsing throws on access. An uncaught throw takes out
        the whole card."""
        spans = _try_block_spans(self.code)
        hits = [m.start() for m in re.finditer(r"localStorage", self.code)]
        self.assertGreater(len(hits), 0)
        for hit in hits:
            self.assertTrue(
                any(start < hit < end for start, end in spans),
                f"unguarded localStorage access at offset {hit}",
            )

    def test_targets_the_worker_origin(self):
        self.assertIn("https://api.bretzanotelli.work", self.js)

    def test_asks_for_a_single_entry(self):
        self.assertIn("/entries?limit=1", self.js)


HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const scenario = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const source = fs.readFileSync(process.argv[2], "utf8");

const problems = [];

function El(tag) {
  this.tag = tag;
  this.kids = [];
  this.classes = new Set();
  this.attrs = {};
  this.own = "";
}
El.prototype.appendChild = function (kid) { this.kids.push(kid); return kid; };
El.prototype.prepend = function (kid) { this.kids.unshift(kid); return kid; };
El.prototype.replaceChildren = function () {
  this.kids = Array.prototype.slice.call(arguments);
  this.own = "";
};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.querySelector = function (sel) {
  const want = sel.replace(/^\./, "");
  for (const kid of this.kids) {
    if (kid.classes.has(want)) return kid;
    const deeper = kid.querySelector(sel);
    if (deeper) return deeper;
  }
  return null;
};
Object.defineProperty(El.prototype, "classList", {
  get: function () {
    const self = this;
    return {
      add: function () {
        for (const c of arguments) { self.classes.add(c); }
      },
      remove: function () {
        for (const c of arguments) { self.classes.delete(c); }
      },
      contains: function (c) { return self.classes.has(c); },
      toggle: function (c, on) {
        if (on) { self.classes.add(c); } else { self.classes.delete(c); }
      }
    };
  }
});
Object.defineProperty(El.prototype, "className", {
  get: function () { return Array.from(this.classes).join(" "); },
  set: function (v) {
    this.classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }
});
Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    return this.own + this.kids.map((k) => k.textContent).join("");
  },
  set: function (v) {
    if (typeof v !== "string") { problems.push("non-string textContent"); }
    this.kids = [];
    this.own = String(v);
  }
});

// <article id="gb-latest" class="into-card into-card--guestbook">
//   <h3>Guestbook</h3>
//   <p class="gb-sig"><span class="gb-invite">Leave a mark.</span></p>
//   <p class="gb-cta"><a href="guestbook.html">Sign it</a></p>
// </article>
const card = new El("article");
card.className = "into-card into-card--guestbook";
const heading = new El("h3");
heading.textContent = "Guestbook";
const sig = new El("p");
sig.className = "gb-sig";
const invite = new El("span");
invite.className = "gb-invite";
invite.textContent = "Leave a mark.";
sig.appendChild(invite);
const cta = new El("p");
cta.className = "gb-cta";
const link = new El("a");
link.attrs.href = "guestbook.html";
link.textContent = "Sign it";
cta.appendChild(link);
card.appendChild(heading);
card.appendChild(sig);
card.appendChild(cta);

const store = Object.assign({}, scenario.store || {});

const localStorage = {
  getItem: function (k) {
    if (scenario.storageThrows === "read" ||
        scenario.storageThrows === "both") {
      throw new Error("SecurityError: access denied");
    }
    return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
  },
  setItem: function (k, v) {
    if (scenario.storageThrows === "write" ||
        scenario.storageThrows === "both") {
      throw new Error("QuotaExceededError");
    }
    store[k] = String(v);
  },
  removeItem: function (k) {
    if (scenario.storageThrows === "write" ||
        scenario.storageThrows === "both") {
      throw new Error("QuotaExceededError");
    }
    delete store[k];
  }
};

let fetched = 0;
function fetchStub() {
  fetched += 1;
  const mode = scenario.fetch;
  if (mode === "reject") {
    return Promise.reject(new TypeError("Failed to fetch"));
  }
  if (mode === "status") {
    return Promise.resolve({
      ok: false, status: 500, json: () => Promise.resolve({})
    });
  }
  if (mode === "badjson") {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token"))
    });
  }
  return Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve(scenario.body)
  });
}

const sandbox = {
  document: {
    getElementById: (id) => (id === "gb-latest" ? card : null),
    querySelector: (sel) => card.querySelector(sel),
    createElement: (tag) => new El(tag)
  },
  window: { localStorage: localStorage },
  localStorage: localStorage,
  fetch: fetchStub,
  AbortSignal: AbortSignal,
  Date: Date,
  JSON: JSON,
  Math: Math,
  isNaN: isNaN,
  String: String,
  Array: Array,
  Object: Object,
  Number: Number,
  Promise: Promise,
  setTimeout: setTimeout,
  console: {
    log: () => {},
    warn: () => {},
    error: (...args) => problems.push("console.error: " + args.join(" "))
  }
};
sandbox.globalThis = sandbox;

process.on("uncaughtException", (e) => problems.push("uncaught: " + e.message));
process.on("unhandledRejection", (e) => problems.push("unhandled: " + e));

try {
  vm.runInNewContext(source, sandbox, { filename: "guestbook-cell.js" });
} catch (e) {
  problems.push("threw at load: " + e.message);
}

setTimeout(() => {
  process.stdout.write(JSON.stringify({
    classes: Array.from(card.classes),
    sigText: sig.textContent,
    sigClasses: sig.kids.map((k) => k.className),
    ctaText: cta.textContent,
    ctaHref: link.attrs.href,
    headingText: heading.textContent,
    store: store,
    fetched: fetched,
    problems: problems
  }));
}, 40);
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestCellBehaviour(unittest.TestCase):
    """Runs the shipped script against a stub DOM and asserts what a
    visitor is left looking at in each fallback layer."""

    ENTRY = {
        "id": 7,
        "name": "Vulkan",
        "message_display": "Into the fires of battle.",
        "message_raw": "Into the fires of battle.",
        "has_swap": False,
        "created_at": "2026-08-19T14:03:11Z",
    }

    @classmethod
    def setUpClass(cls):
        cls.harness = Path(tempfile.mkdtemp()) / "harness.js"
        cls.harness.write_text(HARNESS, encoding="utf-8")

    def run_cell(self, **scenario):
        scenario.setdefault("fetch", "ok")
        scenario.setdefault("body", {"entries": [self.ENTRY]})
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(scenario, handle)
            path = handle.name
        result = subprocess.run(
            ["node", str(self.harness), str(CELL_JS), path],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fresh_cache(self, entries):
        return {"gb_cache": json.dumps(entries)}

    def cached(self, name, age_ms=0, message="cached mark"):
        return {
            "name": name,
            "message_display": message,
            "created_at": "2026-08-18T09:00:00Z",
            "cachedAt": int(time.time() * 1000) - age_ms,
        }

    # -- layer 1: live -------------------------------------

    def test_live_fetch_renders_the_signature(self):
        out = self.run_cell()
        self.assertIn("Vulkan", out["sigText"])
        self.assertIn("Into the fires of battle.", out["sigText"])

    def test_live_fetch_drops_the_invitation_copy(self):
        self.assertNotIn("Leave a mark.", self.run_cell()["sigText"])

    def test_live_fetch_marks_the_card_live(self):
        self.assertIn("is-live", self.run_cell()["classes"])

    def test_live_fetch_does_not_black_out_the_card(self):
        self.assertNotIn("is-cold", self.run_cell()["classes"])

    def test_live_fetch_writes_the_cache(self):
        cache = json.loads(self.run_cell()["store"]["gb_cache"])
        self.assertEqual(cache[0]["name"], "Vulkan")

    def test_cache_never_stores_the_raw_message(self):
        """A moderated entry must not resurface unswapped."""
        entry = dict(self.ENTRY)
        entry["message_display"] = "flip you"
        entry["message_raw"] = "REDACTED-RAW-TEXT"
        entry["has_swap"] = True
        out = self.run_cell(body={"entries": [entry]})
        self.assertNotIn("REDACTED-RAW-TEXT", out["store"]["gb_cache"])
        self.assertNotIn("message_raw", out["store"]["gb_cache"])

    def test_card_never_renders_the_raw_message(self):
        entry = dict(self.ENTRY)
        entry["message_display"] = "flip you"
        entry["message_raw"] = "REDACTED-RAW-TEXT"
        entry["has_swap"] = True
        self.assertNotIn("REDACTED-RAW-TEXT",
                         self.run_cell(body={"entries": [entry]})["sigText"])

    def test_cache_keeps_at_most_two_entries(self):
        store = self.fresh_cache([
            self.cached("One"), self.cached("Two"), self.cached("Three"),
        ])
        out = self.run_cell(store=store)
        self.assertLessEqual(len(json.loads(out["store"]["gb_cache"])), 2)

    def test_markup_is_never_parsed_as_html(self):
        entry = dict(self.ENTRY)
        entry["name"] = '<img src=x onerror="alert(1)">'
        out = self.run_cell(body={"entries": [entry]})
        self.assertIn('<img src=x onerror="alert(1)">', out["sigText"])

    def test_missing_display_text_never_renders_undefined(self):
        entry = {"name": "Nocturne", "created_at": self.ENTRY["created_at"]}
        out = self.run_cell(body={"entries": [entry]})
        self.assertNotIn("undefined", out["sigText"])

    def test_unparseable_timestamp_never_renders_invalid_date(self):
        entry = dict(self.ENTRY)
        entry["created_at"] = "not a date"
        out = self.run_cell(body={"entries": [entry]})
        self.assertNotIn("Invalid Date", out["sigText"])

    # -- an authoritative empty answer ---------------------

    def test_empty_guestbook_cools_the_card(self):
        """Nothing to show is a cooled forge, not an outage."""
        out = self.run_cell(body={"entries": []})
        self.assertIn("is-cold", out["classes"])

    def test_empty_guestbook_evicts_the_cache(self):
        """The server said there is nothing. A moderated entry must not
        keep showing from cache for another 24 hours."""
        out = self.run_cell(body={"entries": []},
                            store=self.fresh_cache([self.cached("Ghost")]))
        self.assertNotIn("Ghost", out["store"].get("gb_cache", ""))

    def test_empty_guestbook_does_not_render_the_cached_mark(self):
        out = self.run_cell(body={"entries": []},
                            store=self.fresh_cache([self.cached("Ghost")]))
        self.assertNotIn("Ghost", out["sigText"])

    # -- layer 2: cache ------------------------------------

    def test_failed_fetch_renders_the_cached_mark(self):
        out = self.run_cell(fetch="reject",
                            store=self.fresh_cache([self.cached("Xavier")]))
        self.assertIn("Xavier", out["sigText"])

    def test_failed_fetch_marks_the_card_cached(self):
        out = self.run_cell(fetch="reject",
                            store=self.fresh_cache([self.cached("Xavier")]))
        self.assertIn("is-cached", out["classes"])
        self.assertNotIn("is-cold", out["classes"])

    def test_server_error_falls_back_to_the_cache(self):
        out = self.run_cell(fetch="status",
                            store=self.fresh_cache([self.cached("Xavier")]))
        self.assertIn("Xavier", out["sigText"])

    def test_unparseable_json_falls_back_to_the_cache(self):
        out = self.run_cell(fetch="badjson",
                            store=self.fresh_cache([self.cached("Xavier")]))
        self.assertIn("Xavier", out["sigText"])

    def test_malformed_payload_falls_back_to_the_cache(self):
        out = self.run_cell(body={"entries": "not a list"},
                            store=self.fresh_cache([self.cached("Xavier")]))
        self.assertIn("Xavier", out["sigText"])

    # -- layer 3: the blackout -----------------------------

    def test_offline_with_no_cache_blacks_out_the_card(self):
        out = self.run_cell(fetch="reject")
        self.assertIn("is-cold", out["classes"])

    def test_offline_with_no_cache_keeps_the_sign_link(self):
        out = self.run_cell(fetch="reject")
        self.assertIn("Sign it", out["ctaText"])
        self.assertEqual(out["ctaHref"], "guestbook.html")

    def test_offline_with_no_cache_keeps_the_invitation(self):
        """No spinner, no error text -- the static copy simply stands."""
        out = self.run_cell(fetch="reject")
        self.assertIn("Leave a mark.", out["sigText"])

    def test_expired_cache_is_not_rendered(self):
        stale = self.cached("Ancient", age_ms=25 * 60 * 60 * 1000)
        out = self.run_cell(fetch="reject", store=self.fresh_cache([stale]))
        self.assertNotIn("Ancient", out["sigText"])
        self.assertIn("is-cold", out["classes"])

    def test_cache_just_inside_the_ttl_is_still_rendered(self):
        recent = self.cached("Recent", age_ms=23 * 60 * 60 * 1000)
        out = self.run_cell(fetch="reject", store=self.fresh_cache([recent]))
        self.assertIn("Recent", out["sigText"])

    def test_corrupt_cache_json_blacks_out_instead_of_throwing(self):
        out = self.run_cell(fetch="reject", store={"gb_cache": "{not json"})
        self.assertIn("is-cold", out["classes"])
        self.assertEqual(out["problems"], [])

    def test_cache_holding_a_non_list_blacks_out(self):
        out = self.run_cell(fetch="reject",
                            store={"gb_cache": '{"name":"Sneaky"}'})
        self.assertIn("is-cold", out["classes"])
        self.assertNotIn("Sneaky", out["sigText"])

    def test_cache_entry_without_a_timestamp_is_discarded(self):
        out = self.run_cell(
            fetch="reject",
            store={"gb_cache": '[{"name":"Undated",'
                               '"message_display":"hi"}]'},
        )
        self.assertNotIn("Undated", out["sigText"])

    # -- private browsing ----------------------------------

    def test_private_browsing_read_does_not_break_the_card(self):
        out = self.run_cell(fetch="reject", storageThrows="read")
        self.assertIn("is-cold", out["classes"])
        self.assertEqual(out["problems"], [])

    def test_private_browsing_write_still_renders_the_live_mark(self):
        out = self.run_cell(storageThrows="write")
        self.assertIn("Vulkan", out["sigText"])
        self.assertEqual(out["problems"], [])

    def test_private_browsing_raises_nothing_on_either_path(self):
        out = self.run_cell(storageThrows="both")
        self.assertEqual(out["problems"], [])

    # -- general -------------------------------------------

    def test_the_card_heading_is_left_alone(self):
        self.assertEqual(self.run_cell()["headingText"], "Guestbook")

    def test_only_one_request_is_made(self):
        self.assertEqual(self.run_cell()["fetched"], 1)

    def test_no_scenario_produces_a_console_error(self):
        for scenario in (
            {},
            {"fetch": "reject"},
            {"fetch": "status"},
            {"fetch": "badjson"},
            {"body": {"entries": []}},
            {"body": {}},
            {"body": None},
        ):
            with self.subTest(scenario=scenario):
                self.assertEqual(self.run_cell(**scenario)["problems"], [])


if __name__ == "__main__":
    unittest.main()
