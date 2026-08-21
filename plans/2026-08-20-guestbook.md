# Guestbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a live guestbook — a Python Cloudflare Worker backed by D1 — plus the static pages that read and write it, without adding a single dependency or network call to the existing build.

**Architecture:** All fallible logic lives in four pure Python modules under `worker/src/` that know nothing about Cloudflare, HTTP, or the network. `entry.py` is a thin routing shell over them. The static site talks to the Worker over a documented JSON contract, and degrades through a two-layer fallback so the landing page never shows a broken box.

**Tech Stack:** Python 3.12 stdlib only (build + policy), Cloudflare Workers (Python, `python_workers` compat flag), D1, vanilla JS (no bundler, no deps).

**Spec:** `specs/2026-08-20-guestbook-design.md`

## Global Constraints

- **The build stays offline.** No task may add a network call, dependency, or non-stdlib import to `build.sh`, `src/main.py`, or anything under `src/Gen_Content/`.
- **`worker/src/*.py` policy modules import stdlib only** — no Cloudflare APIs, no `js` module, no I/O at import time. Wordlists are passed in as parameters, never read from disk inside a policy function.
- **Python ≥ 3.12** (`.python-version`, `pyproject.toml` `requires-python`).
- **Test modules for this feature MUST be named `src/tests/test_gb_*.py`.** Task 0 makes that prefix automatically strict. Any other name silently loses its gate.
- **Frontend is vanilla JS**, no bundler, no npm, no framework. Inline `<script>` is not used; JS lives in `static/*.js` and is copied by the existing static copier.
- **Never store or log a raw IP.** Only `sha256(RATE_SALT || ip)[:32]`.
- **`message` column stores raw text always.** The profanity swap is render-time only.
- **Copy strings live in the frontend, not the Worker.** The Worker returns stable machine `code` values only.
- **Mutation runs must clear `__pycache__` first** (`find . -name __pycache__ -prune -exec rm -rf {} +` or `python3 -B`). Same-length mutants otherwise read stale bytecode and report false survivors.

## Parallelism Map

Tasks within a wave touch **disjoint file sets** and are safe to run in separate worktrees simultaneously. Do not start a wave until the previous wave is merged.

| Wave | Tasks | Parallel? |
|---|---|---|
| 0 | Task 0 | Solo — must merge before anything else |
| 1 | Tasks 1, 2, 3, 4 | 4-way parallel |
| 2 | Tasks 5, 6 | 2-way parallel |
| 3 | Task 7 | Solo (consumes 1, 2, 5) |
| 4 | Tasks 8, 9 | 2-way parallel |
| 5 | Task 10 | Solo — live deploy + verification |

**File ownership, for collision auditing:**

| Task | Owns |
|---|---|
| 0 | `scripts/run_tests.py`, `pyproject.toml`, `worker/.gitignore` |
| 1 | `worker/src/normalize.py`, `src/tests/test_gb_normalize.py` |
| 2 | `worker/src/swaps.py`, `worker/data/swaps.txt`, `src/tests/test_gb_swaps.py` |
| 3 | `worker/schema.sql`, `worker/wrangler.toml`, `worker/README.md` |
| 4 | `guestbook.html`, `static/guestbook.css`, `static/guestbook.js`, `src/Gen_Content/generate_guestbook_page.py`, `src/main.py`, `src/tests/test_gb_page.py` |
| 5 | `worker/src/matching.py`, `worker/data/allow.txt`, `worker/data/blocked.txt`, `scripts/hash_terms.py`, `src/tests/test_gb_matching.py` |
| 6 | `titlepage.html`, `static/landing.css`, `static/guestbook-cell.js`, `src/Gen_Content/generate_landing_page.py`, `src/tests/test_gb_cell.py` |
| 7 | `worker/src/policy.py`, `src/tests/test_gb_policy.py` |
| 8 | `worker/src/entry.py`, `worker/wrangler.toml` (append bindings) |
| 9 | `scripts/guestbook_admin.py` |
| 10 | `worker/README.md` (append runbook) |

**Frontend-design skill applies to Tasks 4 and 6 only.**

**Running a single test module.** `python3 -m unittest src.tests.test_gb_<x>`
does NOT work on its own — `src/` and `worker/src/` are put on the path by
`scripts/run_tests.py`, not by the test modules. Use either:

```bash
PYTHONPATH=src:worker/src python3 -m unittest src.tests.test_gb_<x> -v
./test.sh          # always works; the real gate
```

Every per-task "Run test" step below assumes one of these.

**Do not use a bare `.guestbook` class in new CSS or markup.**
`static/index.css` carries a pre-existing print rule,
`@media print{ .guestbook{display:none !important} }`. Task 4's page already
lives under `body.guestbook` and carries a scoped print override to undo it.
Task 6's landing cell must stay `.into-card--guestbook` — adding a bare
`.guestbook` there would silently blank it in print.

---

## Task 0: Make the guestbook test modules strict by pattern

**Why this is solo and first:** `scripts/run_tests.py` holds a `STRICT` tuple that every new test module appends to. If seven parallel tasks each append a line to the same tuple, every merge conflicts. Converting to a prefix rule means no later task ever edits this file.

**Files:**
- Modify: `scripts/run_tests.py:47-52` (the `STRICT` tuple) and its `sys.path` block in `main()`
- Modify: `pyproject.toml` (`[tool.pyright] extraPaths`)
- Create: `worker/.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: the guarantee that any `src/tests/test_gb_*.py` module is automatically held to 100% green, with no edit to `run_tests.py`.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_strict_pattern.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_strict_pattern -v`
Expected: FAIL — `ImportError: cannot import name 'STRICT_PREFIX'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/run_tests.py`, replace the `STRICT` tuple block with:

```python
# Modules that must be fully green. Two sources:
#   1. STRICT — explicit legacy list, from the Spotify work.
#   2. STRICT_PREFIX — anything named test_gb_*.py is strict automatically.
#
# The prefix rule exists so parallel guestbook tasks never edit this file.
# Seven worktrees each appending to a shared tuple conflicts every time;
# a prefix rule costs one edit here and zero afterwards.
STRICT: tuple[str, ...] = (
    "test_check_token_age",
    "test_render_listening",
    "test_fetch_listening",
)

STRICT_PREFIX = "test_gb_"


def is_strict_module(name: str) -> bool:
    """True when `name` must be held to 100% green with no baseline forgiveness."""
    return name in STRICT or name.startswith(STRICT_PREFIX)


def _strict_modules() -> list[str]:
    """Explicit strict modules plus every discovered test_gb_* module."""
    found = sorted(p.stem for p in TESTS_DIR.glob(f"{STRICT_PREFIX}*.py"))
    return list(STRICT) + found
```

Then in `main()`, change the strict loop's iterable from `STRICT` to `_strict_modules()`:

```python
    for name in _strict_modules():
```

- [ ] **Step 3b: Put `worker/src` on the test path**

The guestbook modules import each other by bare name (`from normalize import ...`), exactly as `scripts/*.py` already do. This is **not** a style choice — it is forced by the runtime. In the deployed Worker, `wrangler.toml` sets `main = "src/entry.py"`, which makes `worker/src` the module root. An import of `worker.src.matching` resolves at test time (repo root is on the path) and then **fails on cold start in production**, because there is no `worker/worker/src/` to find. Bare imports work in both places.

In `main()` in `scripts/run_tests.py`, add one line to the existing `sys.path` block and extend its comment:

```python
    # repo root so `from src.xxx import yyy` resolves (most test files use
    # this form); src/ for Gen_Content.* and bare-module imports (e.g.
    # `from markdown_to_blocks import ...`); scripts/ for the fetch and
    # token modules; worker/src/ for the guestbook policy modules, which
    # import each other bare because the deployed Worker roots itself at
    # worker/src (see wrangler.toml `main`).
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))
```

Then extend the type-checker paths in `pyproject.toml` so editors see the same layout the runtime does:

```toml
[tool.pyright]
extraPaths = ["src", "scripts", "worker/src"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest src.tests.test_gb_strict_pattern -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Verify the whole suite still gates correctly**

Run: `./test.sh`
Expected: exit 0. `full suite: 95 run, 11 failures, 6 errors` (5 new tests added). Baseline line unchanged at `11 failures, 9 errors`.

- [ ] **Step 6: Create the worker gitignore**

```bash
mkdir -p worker/src worker/data
cat > worker/.gitignore <<'EOF'
# wrangler build + auth artifacts, never committed
.wrangler/
node_modules/
.dev.vars
EOF
```

`.dev.vars` holds local secrets. Committing it would leak `ADMIN_TOKEN` and `RATE_SALT`.

- [ ] **Step 7: Commit**

```bash
git add scripts/run_tests.py pyproject.toml \
        src/tests/test_gb_strict_pattern.py worker/.gitignore
git commit -m "Make test_gb_* modules strict by pattern

Seven parallel guestbook tasks would each append to the shared STRICT
tuple and conflict on every merge. A prefix rule costs one edit now and
zero afterwards."
```

---

## Task 1: Text normalization and candidate generation

**Files:**
- Create: `worker/src/normalize.py`
- Create: `src/tests/test_gb_normalize.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `normalize(text: str) -> str`
  - `candidates(text: str) -> frozenset[str]`
  - `strip_nonalnum(text: str) -> str`
  - Constants `ZERO_WIDTH: str`, `CONFUSABLES: dict[str, str]`, `DELEET: dict[str, str]`

  Tasks 5 and 7 import all of these.

**Design note for the implementer:** every transform is **additive**. `candidates()` returns a set that always includes the plain normalized form. Nothing is destructively rewritten, because a destructive deleet pass would mangle numeric terms into nonsense before they could be matched.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_normalize.py`:

```python
"""Normalization is the foundation of the whole content policy.

Every evasion technique the filter defends against is defeated here or
not at all, so this module carries the heaviest hostile battery.
"""
import unittest

from normalize import (
    CONFUSABLES,
    DELEET,
    ZERO_WIDTH,
    candidates,
    normalize,
    strip_nonalnum,
)


class TestNormalize(unittest.TestCase):
    def test_casefolds(self):
        self.assertEqual(normalize("HELLO"), "hello")

    def test_strips_combining_marks(self):
        self.assertEqual(normalize("nïgger"), "nigger")

    def test_strips_zero_width_chars(self):
        self.assertEqual(normalize("he​llo"), "hello")

    def test_strips_soft_hyphen(self):
        self.assertEqual(normalize("he­llo"), "hello")

    def test_maps_cyrillic_confusables(self):
        # Cyrillic а е о and с, visually identical to Latin.
        self.assertEqual(normalize("аеос"), "aeoc")

    def test_maps_greek_confusables(self):
        self.assertEqual(normalize("αο"), "ao")

    def test_nfkd_folds_fullwidth(self):
        self.assertEqual(normalize("ｈｅｌｌｏ"), "hello")

    def test_empty_string(self):
        self.assertEqual(normalize(""), "")

    def test_whitespace_preserved_between_words(self):
        self.assertEqual(normalize("a b"), "a b")

    def test_is_idempotent(self):
        once = normalize("Ｎïg​ger")
        self.assertEqual(normalize(once), once)


class TestStripNonalnum(unittest.TestCase):
    def test_removes_spaces_and_punctuation(self):
        self.assertEqual(strip_nonalnum("n i.g-g_e r"), "nigg
er".replace("\n", ""))

    def test_keeps_digits(self):
        self.assertEqual(strip_nonalnum("a1b2"), "a1b2")

    def test_empty(self):
        self.assertEqual(strip_nonalnum(""), "")


class TestCandidates(unittest.TestCase):
    def test_always_includes_plain_normalized_form(self):
        self.assertIn("hello", candidates("HELLO"))

    def test_includes_deleet_variant(self):
        self.assertIn("nigger", candidates("n1gg3r"))

    def test_includes_separator_stripped_variant(self):
        self.assertIn("nigger", candidates("n i g g e r"))

    def test_collapses_long_runs_to_one(self):
        self.assertIn("fuck", candidates("fuuuuck"))

    def test_preserves_genuine_doubles(self):
        # 'ass' must survive: a collapse-to-1 rule alone would destroy it.
        self.assertIn("ass", candidates("ass"))

    def test_collapse_to_two_variant_exists(self):
        self.assertIn("baall", candidates("baaaall"))

    def test_deleet_does_not_destroy_the_original(self):
        # 1488 must still be checkable as digits, not only as 'ibbb'.
        self.assertIn("1488", candidates("1488"))

    def test_combined_evasion_deleet_plus_spacing(self):
        self.assertIn("nigger", candidates("n 1 g g 3 r"))

    def test_empty_input_yields_empty_candidate(self):
        self.assertIn("", candidates(""))

    def test_returns_frozenset(self):
        self.assertIsInstance(candidates("x"), frozenset)

    def test_large_input_does_not_explode(self):
        # 10KB of text: candidate count is bounded by the number of
        # transforms, never by input length.
        self.assertLessEqual(len(candidates("a b " * 2500)), 16)


class TestTables(unittest.TestCase):
    def test_deleet_maps_digits_to_letters(self):
        self.assertEqual(DELEET["3"], "e")
        self.assertEqual(DELEET["@"], "a")

    def test_confusables_are_single_chars(self):
        for src, dst in CONFUSABLES.items():
            self.assertEqual(len(src), 1)
            self.assertEqual(len(dst), 1)

    def test_zero_width_contains_zwsp(self):
        self.assertIn("​", ZERO_WIDTH)
```

Note the `test_removes_spaces_and_punctuation` assertion is written awkwardly to avoid a literal slur in source; simplify it to `self.assertEqual(strip_nonalnum("a b.c-d_e"), "abcde")` and drop the odd construction. Use benign inputs throughout — the real denylist is never needed to prove this module correct.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_normalize -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'normalize'`

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/normalize.py`:

```python
"""Text normalization for the content policy.

Pure functions. Stdlib only. No I/O, no network, no Cloudflare.

A naive denylist is beaten by leetspeak, accents, homoglyphs, zero-width
joiners, spacing, and repeated characters. Rather than pick one canonical
form and hope, `candidates()` returns every plausible reading of the input
so the matcher can check them all. Transforms are ADDITIVE: the plain
normalized form is always in the set, so a destructive deleet pass can
never mangle a numeric term out of existence before it is matched.
"""
import unicodedata

# Zero-width and invisible characters used to break up words.
ZERO_WIDTH = "​‌‍﻿­"

# Non-Latin characters that render identically to Latin ones. NFKD does
# not fold these — Cyrillic 'а' is a genuinely different letter, not a
# decomposition of 'a' — so they need an explicit table.
CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "і": "i", "ѕ": "s",
    "һ": "h", "ԁ": "d", "ɡ": "g",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v",
    "τ": "t", "Β": "b", "Κ": "k",
}

DELEET = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
    "|": "l", "+": "t",
}

_ZW_TABLE = str.maketrans("", "", ZERO_WIDTH)
_CONFUSABLE_TABLE = str.maketrans(CONFUSABLES)
_DELEET_TABLE = str.maketrans(DELEET)


def normalize(text: str) -> str:
    """Fold `text` to a comparable base form.

    NFKD, drop combining marks, drop invisibles, map confusables, casefold.
    Idempotent.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    cleaned = without_marks.translate(_ZW_TABLE)
    latin = cleaned.translate(_CONFUSABLE_TABLE)
    return latin.casefold()


def strip_nonalnum(text: str) -> str:
    """Drop everything that is not a letter or digit."""
    return "".join(c for c in text if c.isalnum())


def _collapse(text: str, keep: int) -> str:
    """Collapse runs of the same character down to at most `keep`."""
    out: list[str] = []
    run_char = ""
    run_len = 0
    for char in text:
        if char == run_char:
            run_len += 1
        else:
            run_char, run_len = char, 1
        if run_len <= keep:
            out.append(char)
    return "".join(out)


def candidates(text: str) -> frozenset[str]:
    """Every plausible reading of `text`, for the matcher to check.

    Bounded: the result size depends on the number of transforms, never on
    input length.
    """
    base = normalize(text)
    forms = {base, base.translate(_DELEET_TABLE)}

    # Collapse both to 1 (catches 'fuuuck') and to 2 (preserves 'ass').
    for form in list(forms):
        forms.add(_collapse(form, 1))
        forms.add(_collapse(form, 2))

    # Separator-stripped variants of everything above.
    for form in list(forms):
        forms.add(strip_nonalnum(form))

    return frozenset(forms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest src.tests.test_gb_normalize -v`
Expected: PASS, all tests

- [ ] **Step 5: Drive mutation score to 100%**

```bash
find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
```

Mutate by hand and confirm each is killed. Every one of these MUST fail the suite:

| Mutation | Must be killed by |
|---|---|
| `!= "Mn"` → `== "Mn"` | `test_strips_combining_marks` |
| `_collapse(form, 1)` → `_collapse(form, 2)` | `test_collapses_long_runs_to_one` |
| `_collapse(form, 2)` → `_collapse(form, 1)` | `test_collapse_to_two_variant_exists` |
| `run_len <= keep` → `run_len < keep` | `test_preserves_genuine_doubles` |
| drop `forms.add(base.translate(_DELEET_TABLE))` | `test_includes_deleet_variant` |
| drop the strip_nonalnum loop | `test_includes_separator_stripped_variant` |
| `.casefold()` → identity | `test_casefolds` |
| drop `_CONFUSABLE_TABLE` translate | `test_maps_cyrillic_confusables` |

If any mutant survives, add the test that kills it before moving on.

- [ ] **Step 6: Run the full gate**

Run: `./test.sh`
Expected: exit 0, `test_gb_normalize` green, no new baseline failures.

- [ ] **Step 7: Commit**

```bash
git add worker/src/normalize.py src/tests/test_gb_normalize.py
git commit -m "Add text normalization and candidate generation

Additive transforms: the plain normalized form is always in the candidate
set, so a destructive deleet pass can never mangle a numeric term before
it is matched. Collapse runs to both 1 and 2 so 'fuuuck' folds while
'ass' survives."
```

---

## Task 2: Profanity swap

**Files:**
- Create: `worker/src/swaps.py`
- Create: `worker/data/swaps.txt`
- Create: `src/tests/test_gb_swaps.py`

**Interfaces:**
- Consumes: nothing (deliberately independent of `normalize` — see design note)
- Produces:
  - `load_swaps(path: str) -> dict[str, str]`
  - `apply_swaps(text: str, swaps: Mapping[str, str]) -> tuple[str, bool]`

  Task 7 imports both.

**Design note:** swapping is **not** detection and must not use `candidates()`. Detection asks "does any reading of this contain a term"; swapping must rewrite a specific span inside the original text while leaving everything else byte-identical. Feeding it normalized text would return normalized output and destroy the user's message. Match case-insensitively on word boundaries against the literal forms in `swaps.txt`, and preserve the original case pattern.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_swaps.py`:

```python
"""Profanity is permitted and stored raw; only the rendering is softened.

The swap must never alter anything it did not match — this is the user's
message, not ours.
"""
import tempfile
import unittest
from pathlib import Path

from swaps import apply_swaps, load_swaps

SWAPS = {"fuck": "flip", "shit": "shoot", "damn": "dang"}


class TestApplySwaps(unittest.TestCase):
    def test_swaps_lowercase(self):
        self.assertEqual(apply_swaps("oh fuck", SWAPS), ("oh flip", True))

    def test_preserves_all_caps(self):
        self.assertEqual(apply_swaps("OH FUCK", SWAPS), ("OH FLIP", True))

    def test_preserves_title_case(self):
        self.assertEqual(apply_swaps("Fuck off", SWAPS), ("Flip off", True))

    def test_mixed_case_falls_back_to_replacement_as_written(self):
        result, _ = apply_swaps("FuCk", SWAPS)
        self.assertEqual(result.lower(), "flip")

    def test_reports_false_when_nothing_matched(self):
        self.assertEqual(apply_swaps("hello there", SWAPS), ("hello there", False))

    def test_leaves_unmatched_text_byte_identical(self):
        original = "Hello,   World! — café naïve  "
        self.assertEqual(apply_swaps(original, SWAPS), (original, False))

    def test_swaps_multiple_occurrences(self):
        self.assertEqual(
            apply_swaps("fuck fuck", SWAPS), ("flip flip", True)
        )

    def test_swaps_multiple_distinct_terms(self):
        result, swapped = apply_swaps("fuck this shit", SWAPS)
        self.assertEqual(result, "flip this shoot")
        self.assertTrue(swapped)

    def test_respects_word_boundaries(self):
        # Scunthorpe class: a term inside a longer word is not a match.
        self.assertEqual(
            apply_swaps("shitake mushrooms", SWAPS),
            ("shitake mushrooms", False),
        )

    def test_matches_term_adjacent_to_punctuation(self):
        self.assertEqual(apply_swaps("fuck!", SWAPS), ("flip!", True))

    def test_empty_text(self):
        self.assertEqual(apply_swaps("", SWAPS), ("", False))

    def test_empty_swap_map(self):
        self.assertEqual(apply_swaps("fuck", {}), ("fuck", False))

    def test_does_not_rewrite_case_of_untouched_words(self):
        result, _ = apply_swaps("HELLO fuck WORLD", SWAPS)
        self.assertEqual(result, "HELLO flip WORLD")

    def test_token_count_is_preserved(self):
        text = "one fuck three"
        result, _ = apply_swaps(text, SWAPS)
        self.assertEqual(len(result.split()), len(text.split()))


class TestLoadSwaps(unittest.TestCase):
    def _write(self, body: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        return handle.name

    def test_parses_arrow_pairs(self):
        path = self._write("fuck = flip\nshit = shoot\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip", "shit": "shoot"})

    def test_ignores_comments_and_blanks(self):
        path = self._write("# a comment\n\nfuck = flip\n\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_lowercases_keys(self):
        path = self._write("FUCK = flip\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_tolerates_missing_file(self):
        self.assertEqual(load_swaps("/nonexistent/swaps.txt"), {})

    def test_skips_malformed_lines_without_raising(self):
        path = self._write("fuck = flip\ngarbage line\n")
        self.assertEqual(load_swaps(path), {"fuck": "flip"})

    def test_real_swaps_file_parses(self):
        real = Path(__file__).resolve().parents[2] / "worker" / "data" / "swaps.txt"
        self.assertGreater(len(load_swaps(str(real))), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_swaps -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swaps'`

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/swaps.py`:

```python
"""Render-time profanity softening.

Profanity is permitted and stored raw. This module rewrites it for display
only, so the policy stays reversible and the original is never lost.

Deliberately does NOT use normalize.candidates(). Detection asks whether
any reading of a string contains a term; swapping must rewrite one span
inside the user's own text and leave every other byte alone. Normalized
input would produce normalized output and destroy their message.
"""
import re
from collections.abc import Mapping

_COMMENT = "#"
_SEPARATOR = "="


def load_swaps(path: str) -> dict[str, str]:
    """Parse `term = replacement` lines. Missing file yields {}."""
    swaps: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return swaps

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(_COMMENT):
            continue
        if _SEPARATOR not in stripped:
            continue
        term, _, replacement = stripped.partition(_SEPARATOR)
        term, replacement = term.strip(), replacement.strip()
        if term and replacement:
            swaps[term.casefold()] = replacement
    return swaps


def _match_case(original: str, replacement: str) -> str:
    """Reshape `replacement` to the case pattern of `original`."""
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def apply_swaps(text: str, swaps: Mapping[str, str]) -> tuple[str, bool]:
    """Return (display_text, did_swap).

    Matches on word boundaries so 'shitake' is untouched. Every byte that
    is not part of a match is preserved exactly.
    """
    if not text or not swaps:
        return text, False

    # Longest terms first so a term containing another is matched whole.
    ordered = sorted(swaps, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(term) for term in ordered) + r")\b",
        re.IGNORECASE,
    )

    did_swap = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal did_swap
        did_swap = True
        found = match.group(0)
        return _match_case(found, swaps[found.casefold()])

    return pattern.sub(substitute, text), did_swap
```

- [ ] **Step 4: Create the swap wordlist**

Create `worker/data/swaps.txt`. This file is plaintext on purpose — a list of mild profanity and comic replacements is not something that needs hiding, unlike the denylist in Task 5.

```
# Profanity is allowed on this site. This file only softens how it RENDERS.
# Format: term = replacement
# Replacements are shown by default; the reader can reveal the original.
# Tune freely — Salamanders/Nocturne flavour fits the site's theme.

fuck = flip
fucking = flipping
shit = shoot
bullshit = bullhockey
bitch = bantha
bastard = blackguard
asshole = ashhole
dickhead = drakehead
cunt = crucible
piss = puddle
damn = dang
goddamn = throne-cursed
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest src.tests.test_gb_swaps -v`
Expected: PASS, all tests

- [ ] **Step 6: Drive mutation score to 100%**

```bash
find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
```

| Mutation | Must be killed by |
|---|---|
| drop `\b` from the pattern | `test_respects_word_boundaries` |
| `key=len, reverse=True` → `reverse=False` | **Not killed by an `ass`/`asshole` pair** — verified empirically. `\b` alone already disambiguates plain-alphabetic prefix overlaps, so `re.findall` returns the same result either way. A discriminating pair needs a non-word character in the longer term exactly where the shorter one ends, e.g. `cat` vs `cat-nap`: the hyphen satisfies `\b` for the short match too. |
| `original.isupper()` → `original.islower()` | `test_preserves_all_caps` |
| `capitalize()` → `upper()` | `test_preserves_title_case` |
| `did_swap = True` → `did_swap = False` | `test_swaps_lowercase` |
| `if not text or not swaps` → `if not text` | `test_empty_swap_map` |
| `term.casefold()` → `term` in `load_swaps` | `test_lowercases_keys` |

- [ ] **Step 7: Run the full gate and commit**

```bash
./test.sh
git add worker/src/swaps.py worker/data/swaps.txt src/tests/test_gb_swaps.py
git commit -m "Add render-time profanity swap

Stored text stays raw; only the display is softened, so the policy is
reversible. Deliberately independent of normalize(): swapping rewrites a
span inside the user's own text and must leave every other byte alone."
```

---

## Task 3: D1 schema and Worker configuration

**Files:**
- Create: `worker/schema.sql`
- Create: `worker/wrangler.toml`
- Create: `worker/README.md`

**Interfaces:**
- Consumes: nothing
- Produces: the `entries` table contract that Tasks 8 and 9 query, and the `wrangler.toml` that Task 8 appends bindings to.

**No tests.** This task produces configuration and SQL, verified by applying it to a real local D1 instance in Step 3 rather than by unit tests.

- [ ] **Step 1: Write the schema**

Create `worker/schema.sql`:

```sql
-- Guestbook storage. See specs/2026-08-20-guestbook-design.md section 5.
--
-- `message` holds RAW text exactly as typed. The profanity swap is a
-- render-time transform, never a write-time one, so the policy stays
-- reversible and nothing the visitor wrote is ever lost.
--
-- `ip_hash` is sha256(RATE_SALT || ip) truncated to 32 hex chars. Rate
-- limiting works without the site ever holding a visitor's address.
--
-- `hidden` is a soft delete. Blocked entries are stored hidden rather
-- than destroyed so filter misfires are auditable instead of invisible.

CREATE TABLE IF NOT EXISTS entries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT    NOT NULL,
  message      TEXT    NOT NULL,
  created_at   TEXT    NOT NULL,
  ip_hash      TEXT    NOT NULL,
  hidden       INTEGER NOT NULL DEFAULT 0,
  block_reason TEXT
);

-- Serves the public read: WHERE hidden = 0 ORDER BY id DESC LIMIT ?
CREATE INDEX IF NOT EXISTS idx_entries_visible
  ON entries (hidden, id DESC);

-- Serves the rate-limit count: WHERE ip_hash = ? AND created_at > ?
CREATE INDEX IF NOT EXISTS idx_entries_ip
  ON entries (ip_hash, created_at);
```

- [ ] **Step 2: Write the Worker configuration**

Create `worker/wrangler.toml`:

```toml
name = "guestbook"
main = "src/entry.py"
compatibility_date = "2026-08-01"

# Python Workers are in open beta and require this flag. See
# specs/2026-08-20-guestbook-design.md section 12 for the accepted risk.
compatibility_flags = ["python_workers"]

# Task 8 appends [[d1_databases]] and the vars block here.
```

- [ ] **Step 3: Create the database and apply the schema**

These are one-time, run by hand. Requires `npx wrangler login` first.

```bash
cd worker
npx wrangler d1 create guestbook
```

Copy the printed `database_id` — Task 8 needs it.

```bash
npx wrangler d1 execute guestbook --local --file=./schema.sql
npx wrangler d1 execute guestbook --remote --file=./schema.sql
```

- [ ] **Step 4: Verify the schema applied**

```bash
npx wrangler d1 execute guestbook --local \
  --command="SELECT name FROM sqlite_master WHERE type='table';"
```

Expected: a row for `entries`.

```bash
npx wrangler d1 execute guestbook --local \
  --command="INSERT INTO entries (name, message, created_at, ip_hash) VALUES ('t','t','2026-08-20T00:00:00Z','x'); SELECT hidden, block_reason FROM entries;"
```

Expected: `hidden = 0`, `block_reason = NULL` — confirms the defaults. Then clean up:

```bash
npx wrangler d1 execute guestbook --local --command="DELETE FROM entries;"
```

- [ ] **Step 5: Write the setup README**

Create `worker/README.md`:

```markdown
# Guestbook Worker

Python Cloudflare Worker + D1 behind `api.bretzanotelli.work`.
Design: `../specs/2026-08-20-guestbook-design.md`

## Layout

| Path | Responsibility |
|---|---|
| `src/normalize.py` | Text folding + candidate generation. Pure. |
| `src/matching.py` | Hashed denylist matching. Pure. |
| `src/swaps.py` | Render-time profanity swap. Pure. |
| `src/policy.py` | Orchestration: check_name / check_message. Pure. |
| `src/entry.py` | HTTP routing, D1, rate limiting. Thin shell. |
| `data/` | Wordlists. `blocked.txt` is SHA-256 digests only. |

The four pure modules import stdlib only and are tested by the repo's
normal `./test.sh` — no wrangler, no network, no Cloudflare account.

## First-time setup

```bash
npx wrangler login
npx wrangler d1 create guestbook          # copy the database_id
npx wrangler d1 execute guestbook --local  --file=./schema.sql
npx wrangler d1 execute guestbook --remote --file=./schema.sql
```

## Secrets

Never committed. `.dev.vars` is gitignored.

| Secret | Purpose |
|---|---|
| `ADMIN_TOKEN` | Bearer token for `/admin/*` |
| `RATE_SALT` | Salt for `ip_hash`; rotating it resets rate-limit history |

```bash
npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put RATE_SALT
```

## Local development

```bash
npx wrangler dev
```
```

- [ ] **Step 6: Commit**

```bash
git add worker/schema.sql worker/wrangler.toml worker/README.md
git commit -m "Add D1 schema and Worker configuration

Soft-delete via hidden rather than DELETE, so blocked entries stay
auditable. ip_hash is salted and truncated so rate limiting works without
storing visitor addresses."
```

---

## Task 4: Guestbook page — template, styles, form, and build wiring

**REQUIRED SUB-SKILL: `frontend-design:frontend-design`.** Invoke it before writing any markup or CSS. The site has a strong existing visual identity — a forge palette (`--soot`, `--ash`, `--iron`, `--flame`, `--copper`), Bricolage Grotesque / Literata / Departure Mono, and a hard-edged 1px-gutter grid. The guestbook page must read as part of that site, not as a bolted-on form.

**Files:**
- Create: `guestbook.html` (template, repo root — matches `titlepage.html` convention)
- Create: `static/guestbook.css`
- Create: `static/guestbook.js`
- Create: `src/Gen_Content/generate_guestbook_page.py`
- Modify: `src/main.py` (add the generation call after the landing page block)
- Create: `src/tests/test_gb_page.py`

**Interfaces:**
- Consumes: the JSON API contract from the spec §5. The Worker does not exist yet; build against the contract.
- Produces: `generate_guestbook_page(template_path, dest_path, site_config)` — called by `src/main.py`. Also produces the DOM contract Task 6 does **not** share (the landing cell is a separate, simpler widget).

**API contract to build against:**

```
GET  https://api.bretzanotelli.work/entries?limit=25
  -> { "entries": [ { "id": 41, "name": "...", "message_display": "...",
                      "message_raw": "...", "has_swap": true,
                      "created_at": "2026-08-20T14:03:11Z" } ] }

POST https://api.bretzanotelli.work/entries
  body: { "name": "...", "message": "...", "website": "" }
  201 -> { "ok": true,  "entry": {...} }
  200 -> { "ok": true }                      honeypot; nothing stored
  400 -> { "ok": false, "code": "empty" | "name_too_long" |
                                "message_too_long" | "url_not_allowed" |
                                "blocked" }
  429 -> { "ok": false, "code": "rate_limited" }
```

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_page.py`:

```python
"""The guestbook page generator is templating only.

It must never touch the network — the build is offline by design.
"""
import tempfile
import unittest
from pathlib import Path

from Gen_Content.generate_guestbook_page import generate_guestbook_page

TEMPLATE = """<!doctype html>
<title>{{ Title }}</title>
<body class="guestbook">
<h1>{{ SiteTitle }}</h1>
<footer>{{ Year }} - {{ SiteAuthor }}</footer>
</body>
"""

CONFIG = {
    "title": "Guestbook",
    "site_title": "Bret Zanotelli",
    "site_author": "Bret Zanotelli",
    "description": "Sign the guestbook",
}


class TestGenerateGuestbookPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.template = Path(self.tmp) / "guestbook.html"
        self.template.write_text(TEMPLATE, encoding="utf-8")
        self.dest = Path(self.tmp) / "out" / "guestbook.html"

    def _generate(self):
        generate_guestbook_page(str(self.template), str(self.dest), CONFIG)
        return self.dest.read_text(encoding="utf-8")

    def test_writes_the_destination_file(self):
        self._generate()
        self.assertTrue(self.dest.exists())

    def test_creates_missing_parent_directories(self):
        self._generate()
        self.assertTrue(self.dest.parent.is_dir())

    def test_substitutes_title(self):
        self.assertIn("<title>Guestbook</title>", self._generate())

    def test_substitutes_site_author(self):
        self.assertIn("Bret Zanotelli", self._generate())

    def test_substitutes_year_with_four_digits(self):
        import datetime
        year = str(datetime.datetime.now(datetime.UTC).year)
        self.assertIn(year, self._generate())

    def test_leaves_no_unsubstituted_placeholders(self):
        self.assertNotIn("{{", self._generate())

    def test_missing_template_raises_oserror(self):
        with self.assertRaises(OSError):
            generate_guestbook_page(
                "/nonexistent/guestbook.html", str(self.dest), CONFIG
            )


class TestRealTemplate(unittest.TestCase):
    """Guards the contract between the shipped template and the frontend JS."""

    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.markup = (root / "guestbook.html").read_text(encoding="utf-8")

    def test_has_the_entries_mount_point(self):
        self.assertIn('id="gb-entries"', self.markup)

    def test_has_the_form(self):
        self.assertIn('id="gb-form"', self.markup)

    def test_has_the_honeypot_field(self):
        self.assertIn('name="website"', self.markup)

    def test_honeypot_is_hidden_from_assistive_tech(self):
        self.assertIn('aria-hidden="true"', self.markup)

    def test_honeypot_is_not_tabbable(self):
        self.assertIn('tabindex="-1"', self.markup)

    def test_has_an_aria_live_status_region(self):
        self.assertIn('aria-live="polite"', self.markup)

    def test_name_input_caps_at_40(self):
        self.assertIn('maxlength="40"', self.markup)

    def test_message_input_caps_at_500(self):
        self.assertIn('maxlength="500"', self.markup)

    def test_loads_the_guestbook_script(self):
        self.assertIn("guestbook.js", self.markup)

    def test_form_fields_have_labels(self):
        self.assertIn('<label for="gb-name"', self.markup)
        self.assertIn('<label for="gb-message"', self.markup)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_page -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Gen_Content.generate_guestbook_page'`

- [ ] **Step 3: Write the generator**

Create `src/Gen_Content/generate_guestbook_page.py`:

```python
"""Render the guestbook page template.

Templating only. This module never contacts the Worker — the build is
offline by design (see the plan's Global Constraints). Entries are fetched
by static/guestbook.js in the browser, not at build time.
"""
import datetime
import os


def generate_guestbook_page(template_path, dest_path, site_config=None):
    """Write the guestbook page to `dest_path`.

    Args:
        template_path: Path to guestbook.html template.
        dest_path: Destination path for the generated page.
        site_config: Optional dict with title/site_title/site_author/description.
    """
    config = {
        "title": "Guestbook",
        "site_title": "Bret Zanotelli",
        "site_author": "Bret Zanotelli",
        "description": "Sign the guestbook",
    }
    if site_config:
        config.update(site_config)

    with open(template_path, "r", encoding="utf-8") as handle:
        template = handle.read()

    current_year = datetime.datetime.now(datetime.UTC).year

    page_html = (
        template
        .replace("{{ Title }}", config["title"])
        .replace("{{ Description }}", config["description"])
        .replace("{{ Canonical }}", "/guestbook.html")
        .replace("{{ SiteTitle }}", config["site_title"])
        .replace("{{ SiteDescription }}", config["description"])
        .replace("{{ SiteAuthor }}", config["site_author"])
        .replace("{{ Year }}", str(current_year))
    )

    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as handle:
        handle.write(page_html)

    print(f"Guestbook page written to {dest_path}")
```

- [ ] **Step 4: Build the template and styles**

Invoke `frontend-design:frontend-design` now. Create `guestbook.html` mirroring the head, nav, and footer structure of `titlepage.html`, plus `static/guestbook.css`.

Required markup contract — the tests above and `guestbook.js` depend on every one of these:

```html
<section class="gb-sign">
  <form id="gb-form" novalidate>
    <label for="gb-name">Name</label>
    <input id="gb-name" name="name" type="text" maxlength="40" required>

    <label for="gb-message">Message</label>
    <textarea id="gb-message" name="message" maxlength="500" required></textarea>
    <p class="gb-counter"><span id="gb-count">0</span>/500</p>

    <!-- Honeypot. Bots fill it; humans never see it. Not display:none —
         some bots skip those. Positioned offscreen instead. -->
    <div class="gb-hp" aria-hidden="true">
      <label for="gb-website">Website</label>
      <input id="gb-website" name="website" type="text"
             tabindex="-1" autocomplete="off">
    </div>

    <button id="gb-submit" type="submit">Sign it</button>
  </form>

  <p id="gb-status" class="gb-status" aria-live="polite" role="status"></p>

  <div id="gb-bender" class="gb-bender" hidden>
    <img src="bender-reject.webp" alt="Bender from Futurama, pointing.">
    <p>Bite my shiny metal ass.</p>
  </div>
</section>

<section class="gb-wall">
  <ul id="gb-entries"></ul>
  <p id="gb-empty" class="gb-empty" hidden></p>
</section>

<script src="guestbook.js" defer></script>
```

CSS requirements:
- `.gb-hp` positioned offscreen (`position:absolute; left:-9999px`), **not** `display:none`.
- `@media (prefers-reduced-motion: reduce)` swaps the Bender animation for a static poster frame.
- Reuse the existing custom properties from `index.css`. Define no new colours.
- The reveal toggle for swapped messages must be a real `<button>`, not a `<div>`.

**Asset note:** `static/bender-reject.webp` is supplied by the site owner and is not created by this task. If it is absent, the build still succeeds and the image renders its `alt` text. Ship as animated WebP or MP4, not GIF.

- [ ] **Step 5: Write the frontend JS**

Create `static/guestbook.js`. Requirements:

- `API = "https://api.bretzanotelli.work"`.
- On load, `GET ${API}/entries?limit=25`; render into `#gb-entries`.
- Render `message_display`. When `has_swap` is true, append a `<button class="gb-reveal">show original</button>` that swaps the text to `message_raw` and back.
- **Escape all entry text.** Build nodes with `textContent`, never `innerHTML`. The Worker does not sanitise for HTML; the client must never inject.
- On fetch failure, reveal `#gb-empty` with an honest message. Never leave a spinner running.
- On submit: disable `#gb-submit`, POST JSON, then map `code` to copy:

| code | copy |
|---|---|
| *(201)* | "Signed. Thanks for stopping by." |
| `empty` | "Needs a name and a message." |
| `name_too_long` | "Name is over 40 characters." |
| `message_too_long` | "Message is over 500 characters." |
| `url_not_allowed` | "Links aren't allowed — say it in words." |
| `blocked` | *(show `#gb-bender`, hide the status line)* |
| `rate_limited` | "Slow down a moment, then try again." |
| *(network error)* | "Couldn't reach the guestbook. Try again shortly." |

- Re-enable the button in a `finally` block so a network error never leaves the form dead.
- Move focus to `#gb-status` after any response.
- Update `#gb-count` on every `input` event.

- [ ] **Step 6: Wire it into the build**

In `src/main.py`, add the import at the top with the others:

```python
from Gen_Content.generate_guestbook_page import generate_guestbook_page
```

Then, immediately after the landing-page `if/else` block and before the `if had_errors:` check, add:

```python
        # Guestbook page. Templating only — entries are fetched in the
        # browser, never at build time, so the build stays offline.
        guestbook_template = os.path.join(workspace_root, "guestbook.html")
        guestbook_html = os.path.join(docs_path, "guestbook.html")
        if os.path.exists(guestbook_template):
            log_message("Generating guestbook page...")
            try:
                generate_guestbook_page(
                    guestbook_template,
                    guestbook_html,
                    {
                        "title": "Guestbook",
                        "site_title": site_config["site_title"],
                        "site_author": site_config["site_author"],
                        "description": "Sign the guestbook.",
                    },
                )
                log_message("Guestbook page generated successfully")
            except Exception as e:  # noqa: BLE001 -- see fault-isolation note above
                had_errors = True
                log_message(f"ERROR generating guestbook page: {e}")
                import traceback
                log_message(traceback.format_exc())
        else:
            log_message("WARNING: guestbook.html template not found")
```

Note `site_config` is defined inside the landing-page `try:` block. Hoist its assignment above that block so this code can read it.

- [ ] **Step 7: Run tests and build**

```bash
python3 -m unittest src.tests.test_gb_page -v
./test.sh
./build.sh
```

Expected: tests pass; `docs/guestbook.html` exists; `grep -c "{{" docs/guestbook.html` returns 0.

- [ ] **Step 8: Commit**

```bash
git add guestbook.html static/guestbook.css static/guestbook.js \
        src/Gen_Content/generate_guestbook_page.py src/main.py \
        src/tests/test_gb_page.py
git commit -m "Add guestbook page, styles, form, and build wiring

Templating only — entries are fetched in the browser, never at build
time, so the build stays offline. Entry text is rendered via textContent;
the client never injects HTML."
```

---

## Task 5: Hashed denylist matching

**Files:**
- Create: `worker/src/matching.py`
- Create: `worker/data/allow.txt`
- Create: `worker/data/blocked.txt`
- Create: `scripts/hash_terms.py`
- Create: `src/tests/test_gb_matching.py`

**Interfaces:**
- Consumes: `normalize`, `candidates`, `strip_nonalnum` from `worker/src/normalize.py` (Task 1)
- Produces:
  - `digest(term: str) -> str`
  - `load_blocked(path: str) -> Blocklist`
  - `load_allow(path: str) -> frozenset[str]`
  - `contains_blocked(text: str, blocklist: Blocklist, allow: frozenset[str]) -> bool`
  - `Blocklist` — a frozen dataclass with fields `digests: frozenset[str]`, `minlen: int`, `maxlen: int`, `substr_minlen: int`

  Task 7 imports `load_blocked`, `load_allow`, `contains_blocked`, and `Blocklist`.

**The two-pass rule, which is the whole point of this module:**

1. Normalize, then **subtract allowlisted safe words** by word boundary.
2. Word-boundary scan over the remainder, using **every** term.
3. Separator-stripped substring scan, using **only terms of length ≥ `substr_minlen` (5)**.

Short terms are exactly the ones that appear innocently inside longer words. Once separators are stripped the word boundaries are gone, so a 3-character term would fire constantly on ordinary text — and no allowlist can enumerate every word in English. The allowlist must be subtracted **before** candidates are generated, or the aggressive pass will see the safe word anyway.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_matching.py`. Tests inject **benign fake terms** — the real denylist is never needed to prove the algorithm correct.

```python
"""Denylist matching, tested entirely with benign fake terms.

The real list is SHA-256 digests in worker/data/blocked.txt and is never
needed here: hashing 'zzblocked' proves the algorithm exactly as well as
hashing a slur would, and keeps this file readable.
"""
import tempfile
import unittest
from pathlib import Path

from matching import (
    Blocklist,
    contains_blocked,
    digest,
    load_allow,
    load_blocked,
)

# Fake terms. 'zzshort' is 7 chars; 'zzs' is 3 and only ever word-matched.
BLOCKED_TERMS = ["zzblocked", "zzhate", "zzs"]


def _blocklist(substr_minlen=5):
    return Blocklist(
        digests=frozenset(digest(t) for t in BLOCKED_TERMS),
        minlen=3,
        maxlen=9,
        substr_minlen=substr_minlen,
    )


NO_ALLOW = frozenset()


class TestDigest(unittest.TestCase):
    def test_is_stable(self):
        self.assertEqual(digest("abc"), digest("abc"))

    def test_normalizes_before_hashing(self):
        self.assertEqual(digest("ABC"), digest("abc"))

    def test_differs_between_terms(self):
        self.assertNotEqual(digest("abc"), digest("abd"))

    def test_is_hex_sha256(self):
        value = digest("abc")
        self.assertEqual(len(value), 64)
        int(value, 16)  # raises if not hex


class TestContainsBlocked(unittest.TestCase):
    def test_plain_hit(self):
        self.assertTrue(contains_blocked("you zzblocked thing", _blocklist(), NO_ALLOW))

    def test_clean_text_passes(self):
        self.assertFalse(contains_blocked("hello there friend", _blocklist(), NO_ALLOW))

    def test_case_insensitive(self):
        self.assertTrue(contains_blocked("ZZBLOCKED", _blocklist(), NO_ALLOW))

    def test_catches_leetspeak(self):
        self.assertTrue(contains_blocked("zzbl0cked", _blocklist(), NO_ALLOW))

    def test_catches_spaced_evasion(self):
        self.assertTrue(contains_blocked("z z b l o c k e d", _blocklist(), NO_ALLOW))

    def test_catches_punctuation_evasion(self):
        self.assertTrue(contains_blocked("z.z.b.l.o.c.k.e.d", _blocklist(), NO_ALLOW))

    def test_catches_repeat_evasion(self):
        self.assertTrue(contains_blocked("zzbloooocked", _blocklist(), NO_ALLOW))

    def test_catches_combining_mark_evasion(self):
        self.assertTrue(contains_blocked("zzblöcked", _blocklist(), NO_ALLOW))

    def test_empty_text_passes(self):
        self.assertFalse(contains_blocked("", _blocklist(), NO_ALLOW))

    def test_empty_blocklist_passes_everything(self):
        empty = Blocklist(frozenset(), 3, 9, 5)
        self.assertFalse(contains_blocked("zzblocked", empty, NO_ALLOW))


class TestShortTermsAreWordOnly(unittest.TestCase):
    """The substr_minlen rule. Without it, short terms fire on ordinary text."""

    def test_short_term_matches_as_a_whole_word(self):
        self.assertTrue(contains_blocked("what a zzs", _blocklist(), NO_ALLOW))

    def test_short_term_does_not_match_inside_a_longer_word(self):
        # 'zzs' is 3 chars, below substr_minlen, so the stripped pass skips it.
        self.assertFalse(contains_blocked("puzzsolver", _blocklist(), NO_ALLOW))

    def test_lowering_substr_minlen_would_catch_it(self):
        # Proves the guard is load-bearing, not incidental.
        self.assertTrue(
            contains_blocked("puzzsolver", _blocklist(substr_minlen=3), NO_ALLOW)
        )


class TestAllowlist(unittest.TestCase):
    """The Scunthorpe class. These must pass clean."""

    def test_allowlisted_word_containing_a_term_passes(self):
        allow = frozenset({"zzblockedford"})
        self.assertFalse(
            contains_blocked("greetings from zzblockedford", _blocklist(), allow)
        )

    def test_allowlist_is_subtracted_before_the_stripped_pass(self):
        # If subtraction happened after candidate generation, stripping
        # separators would re-expose the term inside the safe word.
        allow = frozenset({"zzblockedford"})
        self.assertFalse(
            contains_blocked("zzblockedford, england", _blocklist(), allow)
        )

    def test_allowlist_does_not_hide_a_genuine_hit_elsewhere(self):
        allow = frozenset({"zzblockedford"})
        self.assertTrue(
            contains_blocked("zzblockedford and zzhate", _blocklist(), allow)
        )

    def test_allowlist_matching_is_case_insensitive(self):
        allow = frozenset({"zzblockedford"})
        self.assertFalse(
            contains_blocked("ZZBLOCKEDFORD", _blocklist(), allow)
        )


class TestLoaders(unittest.TestCase):
    def _write(self, body):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        return handle.name

    def test_load_blocked_parses_header_and_digests(self):
        path = self._write(
            "# minlen=3 maxlen=14 substr_minlen=5\n" + digest("zzblocked") + "\n"
        )
        result = load_blocked(path)
        self.assertEqual(result.minlen, 3)
        self.assertEqual(result.maxlen, 14)
        self.assertEqual(result.substr_minlen, 5)
        self.assertIn(digest("zzblocked"), result.digests)

    def test_load_blocked_ignores_blank_lines(self):
        path = self._write(
            "# minlen=3 maxlen=14 substr_minlen=5\n\n" + digest("x") + "\n\n"
        )
        self.assertEqual(len(load_blocked(path).digests), 1)

    def test_load_blocked_tolerates_missing_file(self):
        result = load_blocked("/nonexistent/blocked.txt")
        self.assertEqual(result.digests, frozenset())

    def test_load_allow_lowercases_and_strips(self):
        path = self._write("# comment\n  Scunthorpe  \n\nAssassin\n")
        self.assertEqual(load_allow(path), frozenset({"scunthorpe", "assassin"}))

    def test_load_allow_tolerates_missing_file(self):
        self.assertEqual(load_allow("/nonexistent/allow.txt"), frozenset())

    def test_real_allow_file_parses(self):
        root = Path(__file__).resolve().parents[2]
        self.assertGreater(len(load_allow(str(root / "worker" / "data" / "allow.txt"))), 0)

    def test_real_blocked_file_has_a_valid_header(self):
        root = Path(__file__).resolve().parents[2]
        result = load_blocked(str(root / "worker" / "data" / "blocked.txt"))
        self.assertGreaterEqual(result.substr_minlen, 5)
        self.assertGreaterEqual(result.minlen, 1)


class TestScunthorpeCorpus(unittest.TestCase):
    """Real words that trip naive filters. All must pass with the real lists."""

    CORPUS = [
        "Scunthorpe", "Cockburn", "assassin", "analysis", "classic",
        "shiitake", "Lipschitz", "Sussex", "Uranus", "bass", "pass",
        "grass", "Weiner", "Kuntz", "Dickinson", "Hoare", "Bumgarner",
        "therapist", "Matsushita", "Penistone", "cumulative", "titles",
    ]

    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        data = root / "worker" / "data"
        self.blocklist = load_blocked(str(data / "blocked.txt"))
        self.allow = load_allow(str(data / "allow.txt"))

    def test_no_real_word_is_blocked(self):
        for word in self.CORPUS:
            with self.subTest(word=word):
                self.assertFalse(
                    contains_blocked(word, self.blocklist, self.allow),
                    f"{word!r} was blocked — this is the Scunthorpe bug",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_matching -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'matching'`

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/matching.py`:

```python
"""Hashed denylist matching.

Pure functions. Stdlib only.

The repo is public, so the denylist ships as SHA-256 digests rather than
plaintext. Matching hashes each candidate token (and, for longer terms,
each bounded substring) and tests membership.

Two passes, with deliberately different minimum lengths:

  1. Word-boundary pass, using every term.
  2. Separator-stripped substring pass, using only terms of length
     >= substr_minlen.

Short terms are the ones that appear innocently inside longer words. Once
separators are stripped the word boundaries are gone, so a 3-character
term would fire constantly on ordinary text, and no allowlist can
enumerate every word in English.
"""
import hashlib
import re
from dataclasses import dataclass

from normalize import candidates, normalize, strip_nonalnum

_COMMENT = "#"
_HEADER_KEYS = ("minlen", "maxlen", "substr_minlen")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Blocklist:
    """Digests plus the length bounds needed to drive the substring pass."""

    digests: frozenset[str]
    minlen: int
    maxlen: int
    substr_minlen: int


def digest(term: str) -> str:
    """SHA-256 hex of the normalized term."""
    return hashlib.sha256(normalize(term).encode("utf-8")).hexdigest()


def _digest_raw(text: str) -> str:
    """Hash text that is already normalized, skipping a redundant fold."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_blocked(path: str) -> Blocklist:
    """Read the digest file. Missing file yields an empty blocklist."""
    bounds = {"minlen": 3, "maxlen": 14, "substr_minlen": 5}
    digests: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return Blocklist(frozenset(), bounds["minlen"], bounds["maxlen"],
                         bounds["substr_minlen"])

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT):
            for key in _HEADER_KEYS:
                match = re.search(rf"\b{key}=(\d+)", stripped)
                if match:
                    bounds[key] = int(match.group(1))
            continue
        digests.add(stripped.lower())

    return Blocklist(frozenset(digests), bounds["minlen"], bounds["maxlen"],
                     bounds["substr_minlen"])


def load_allow(path: str) -> frozenset[str]:
    """Read the plaintext false-positive allowlist."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return frozenset()

    return frozenset(
        normalize(line.strip())
        for line in lines
        if line.strip() and not line.strip().startswith(_COMMENT)
    )


def _subtract_allowed(text: str, allow: frozenset[str]) -> str:
    """Remove allowlisted words by word boundary, before candidates exist.

    Order matters: doing this after candidate generation would let the
    separator-stripped pass see the safe word anyway.
    """
    if not allow:
        return text
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(word) for word in sorted(allow, key=len, reverse=True)) + r")\b"
    )
    return pattern.sub(" ", text)


def contains_blocked(
    text: str, blocklist: Blocklist, allow: frozenset[str]
) -> bool:
    """True when any reading of `text` contains a blocked term."""
    if not text or not blocklist.digests:
        return False

    cleaned = _subtract_allowed(normalize(text), allow)

    for form in candidates(cleaned):
        # Pass 1: whole words, every term length.
        for word in _WORD.findall(form):
            if blocklist.minlen <= len(word) <= blocklist.maxlen:
                if _digest_raw(word) in blocklist.digests:
                    return True

        # Pass 2: bounded substrings of the stripped form, longer terms only.
        stripped = strip_nonalnum(form)
        low = max(blocklist.substr_minlen, 1)
        for size in range(low, blocklist.maxlen + 1):
            for start in range(0, len(stripped) - size + 1):
                if _digest_raw(stripped[start:start + size]) in blocklist.digests:
                    return True

    return False
```

- [ ] **Step 4: Write the allowlist**

Create `worker/data/allow.txt`:

```
# False-positive allowlist. Real words and names that contain a flagged
# substring. Subtracted from the text BEFORE candidate generation, so the
# separator-stripped pass never sees them.
#
# Add to this file whenever `guestbook_admin.py --review` shows a real
# person was caught. That is the feedback loop; use it.

scunthorpe
penistone
cockburn
cockburns
assassin
assassinate
assassination
analysis
analyse
analyze
analyst
classic
classical
class
classes
bass
pass
passage
grass
mass
massive
sussex
essex
middlesex
shiitake
lipschitz
uranus
therapist
matsushita
cumulative
cumulate
titles
dickinson
dickens
weiner
weber
kuntz
kunz
hoare
bumgarner
hancock
babcock
peacock
leacock
woodcock
adcock
glasscock
```

- [ ] **Step 5: Write the digest tool and generate the denylist**

Create `scripts/hash_terms.py`:

```python
#!/usr/bin/env python3
"""Turn a plaintext term list into the SHA-256 digest file the Worker loads.

The repo is public. The plaintext input is NEVER committed — write it to a
path outside the repo, run this, commit only the output.

Usage:
    python3 scripts/hash_terms.py ~/terms.txt worker/data/blocked.txt
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The policy modules import each other bare, matching the layout the
# deployed Worker roots itself at. See scripts/run_tests.py.
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from matching import digest  # noqa: E402
from normalize import normalize  # noqa: E402

SUBSTR_MINLEN = 5


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    source, dest = Path(sys.argv[1]), Path(sys.argv[2])

    if source.resolve().is_relative_to(REPO_ROOT):
        print(f"ERROR: {source} is inside the repo. The plaintext term "
              "list must never be committed. Move it elsewhere.")
        return 1

    terms = [
        normalize(line.strip())
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not terms:
        print("ERROR: no terms found")
        return 1

    lengths = [len(t) for t in terms]
    header = (f"# minlen={min(lengths)} maxlen={max(lengths)} "
              f"substr_minlen={SUBSTR_MINLEN}")

    lines = [header, "# Generated by scripts/hash_terms.py. Do not edit by hand."]
    lines += sorted({digest(term) for term in terms})

    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines) - 2} digests to {dest} ({header})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Now build the real list. Write the plaintext terms to a path **outside the repo**, covering the categories from spec §6.1 — racial, LGBTQIA+ (including transphobic), antisemitic, ableist, and their coded and tertiary variants. Then:

```bash
python3 scripts/hash_terms.py ~/gb-terms.txt worker/data/blocked.txt
shred -u ~/gb-terms.txt   # or delete it; it must not persist in the repo
head -2 worker/data/blocked.txt
```

Expected: a header line, then a generated-by line. Confirm with `git status` that only `worker/data/blocked.txt` is staged.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest src.tests.test_gb_matching -v`
Expected: PASS. **If `TestScunthorpeCorpus` fails, do not weaken the test** — add the word to `allow.txt`. That test is the whole safety net.

- [ ] **Step 7: Drive mutation score to 100%**

```bash
find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
```

| Mutation | Must be killed by |
|---|---|
| `low = max(substr_minlen, 1)` → `low = 1` | `test_short_term_does_not_match_inside_a_longer_word` |
| `_subtract_allowed` before → after candidates | `test_allowlist_is_subtracted_before_the_stripped_pass` |
| drop `\b` in `_subtract_allowed` | `test_allowlist_does_not_hide_a_genuine_hit_elsewhere` |
| `minlen <= len(word)` → `<` | add a term of exactly `minlen` if not killed |
| `len(word) <= maxlen` → `<` | add a term of exactly `maxlen` if not killed |
| `return True` → `return False` in pass 1 | `test_short_term_matches_as_a_whole_word` |
| `return True` → `return False` in pass 2 | `test_catches_spaced_evasion` |
| `not blocklist.digests` guard removed | `test_empty_blocklist_passes_everything` |

- [ ] **Step 8: Run the full gate and commit**

```bash
./test.sh
git add worker/src/matching.py worker/data/allow.txt worker/data/blocked.txt \
        scripts/hash_terms.py src/tests/test_gb_matching.py
git commit -m "Add hashed denylist matching with Scunthorpe guard

Two passes at different minimum lengths: word-boundary uses every term,
separator-stripped uses only terms >= 5 chars. Short terms appear
innocently inside longer words, and once separators are stripped there
are no boundaries left to protect them.

Allowlist is subtracted BEFORE candidate generation, or the stripped pass
would re-expose the term inside the safe word.

Denylist ships as SHA-256 digests; this repo is public."
```

---

## Task 6: Landing page guestbook cell

**REQUIRED SUB-SKILL: `frontend-design:frontend-design`.** The blackout fallback is a deliberate design state, not an error state — the palette is already a forge, so a cooled card must read as intentional. Treat it as a visual design problem.

**Files:**
- Modify: `titlepage.html` — the `.into-grid` block, adding a 4th card immediately after the `<h3>Cooking</h3>` article. (Do not trust a line number here: `origin/main` commit `181206e` already shifted this block once. Anchor on the Cooking heading.)
- Modify: `static/landing.css` (append `.into-card--guestbook` rules)
- Create: `static/guestbook-cell.js`
- Modify: `src/Gen_Content/generate_landing_page.py` (add the Guestbook link to `PageLinks`)
- Create: `src/tests/test_gb_cell.py`

**Interfaces:**
- Consumes: the `GET /entries?limit=1` contract (spec §5). Independent of all Worker tasks.
- Produces: nothing other tasks consume.

**Layout note:** `.into-grid` is `repeat(auto-fit, minmax(190px, 1fr))`. A 4th card flows in with **no change to the grid rule**. Do not rewrite the grid.

**The three-layer fallback — the point of this task:**

```
1. fetch OK    -> render latest signature, write cache
2. fetch fails -> read localStorage cache, render last known good
3. no cache    -> blacked-out card
```

Cache rules, all mandatory:
- Key `gb_cache`, holding the current entry and one previous.
- **`message_display` only. Never `message_raw`.** A hidden entry must not resurface unswapped from a stale cache.
- 24h TTL so a moderated entry self-evicts.
- Every read and write wrapped in `try/catch` — private browsing throws on access.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_cell.py`:

```python
"""Guards the landing-page cell contract and the PageLinks entry.

The fallback behaviour itself is JS; these tests pin the markup and build
contract that the JS depends on, so a template edit cannot silently break it.
"""
import re
import tempfile
import unittest
from pathlib import Path

from Gen_Content.generate_landing_page import generate_landing_page

ROOT = Path(__file__).resolve().parents[2]


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


class TestLandingCss(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "static" / "landing.css").read_text(encoding="utf-8")

    def test_styles_the_guestbook_card(self):
        self.assertIn(".into-card--guestbook", self.css)

    def test_defines_the_blackout_state(self):
        self.assertIn("is-cold", self.css)

    def test_does_not_rewrite_the_grid_template(self):
        # The auto-fit grid already absorbs a 4th card. Rewriting it is a
        # regression, not a fix.
        self.assertIn("repeat(auto-fit,minmax(190px,1fr))",
                      self.css.replace(" ", ""))


class TestPageLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.content = Path(self.tmp) / "content"
        self.content.mkdir()
        (self.content / "aboutme.md").write_text("# About Me\n", encoding="utf-8")
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

    def test_no_unsubstituted_placeholders_remain(self):
        self.assertNotIn("{{", self._generate())

    def test_existing_pages_still_render(self):
        self.assertIn('href="aboutme.html"', self._generate())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_cell -v`
Expected: FAIL — `AssertionError: 'into-card--guestbook' not found`

- [ ] **Step 3: Add the card to the template**

In `titlepage.html`, immediately after the Cooking `</article>` and before the closing `</div>` of `.into-grid`:

```html
              <article class="into-card into-card--guestbook" id="gb-latest">
                <h3>Guestbook</h3>
                <p class="into-note">
                  <a href="guestbook.html">Sign it &rarr;</a>
                </p>
              </article>
```

And before `</body>`, alongside any other scripts:

```html
    <script src="guestbook-cell.js" defer></script>
```

The static markup is the layer-3 state made visible: if JS never runs, the card is still a working link to the guestbook.

- [ ] **Step 4: Add the styles**

Append to `static/landing.css`, after the existing `.into-note` rule. Use `frontend-design:frontend-design` to make the cold state read as deliberate:

```css
/* ── guestbook cell ─────────────────────────────────────── */
/* Layer 3 of the fallback. A cooled forge, not a broken box:
   when there is nothing to show, the card goes dark on purpose. */
body.landing .into-card--guestbook .gb-sig{
  margin:0;
  font-size:.95rem;
  line-height:1.6;
}

body.landing .into-card--guestbook .gb-who{
  color:var(--flame);
  font-style:normal;
}

body.landing .into-card--guestbook.is-cold{
  background:var(--soot);
  color:var(--iron);
}

body.landing .into-card--guestbook.is-cold h3{
  color:var(--iron);
}
```

Define no new colour values. Reuse the existing custom properties.

- [ ] **Step 5: Write the cell script**

Create `static/guestbook-cell.js`. Requirements, all load-bearing:

```javascript
const API = "https://api.bretzanotelli.work";
const CACHE_KEY = "gb_cache";
const TTL_MS = 24 * 60 * 60 * 1000;
```

- `readCache()` and `writeCache()` **both wrapped in try/catch**. Private browsing throws on `localStorage` access; an uncaught throw takes out the whole card.
- `writeCache` stores at most 2 entries, each `{ name, message_display, created_at, cachedAt }`. **Never `message_raw`.**
- `readCache` discards entries older than `TTL_MS`.
- Render via `textContent`, never `innerHTML`.
- On fetch failure with a usable cache: render the cached entry.
- On fetch failure with no usable cache: add `is-cold` to the card and leave the static "Sign it →" link in place.
- Never render a spinner that can outlive the request.

- [ ] **Step 6: Add the Guestbook link to PageLinks**

`PageLinks` is generated from `content/*.md`, and the guestbook is not a markdown page, so it needs an explicit entry. In `generate_landing_page.py`, inside the `if md_files or has_dev_diary:` block, immediately after the Dev Diary append:

```python
        # The guestbook is generated from guestbook.html, not from a
        # markdown file, so it is not discovered by the scan above.
        page_links_html.append(
            '              <li><a href="guestbook.html">Guestbook</a></li>'
        )
```

- [ ] **Step 7: Run tests and build**

```bash
python3 -m unittest src.tests.test_gb_cell -v
./test.sh
./build.sh
grep -c "into-card--guestbook" docs/index.html   # expect 1
grep -c "{{" docs/index.html                      # expect 0
```

- [ ] **Step 8: Verify the fallback by hand**

Open `docs/index.html` in a browser with devtools:

1. **Offline** (devtools → Network → Offline), hard reload. Expect the blacked-out card, no console errors, no spinner.
2. Block `localStorage` (devtools → Application → clear site data, then a private window). Expect the blacked-out card, still no errors.

Both must degrade silently. A console error here means the try/catch is missing or misplaced.

- [ ] **Step 9: Commit**

```bash
git add titlepage.html static/landing.css static/guestbook-cell.js \
        src/Gen_Content/generate_landing_page.py src/tests/test_gb_cell.py
git commit -m "Add landing-page guestbook cell with three-layer fallback

live -> localStorage cache -> blacked-out card. The blackout is a design
state, not an error state: the palette is already a forge, so a cooled
card reads as intentional.

Cache holds message_display only, never message_raw, so a hidden entry
cannot resurface unswapped. Every localStorage access is wrapped —
private browsing throws."
```

---

## Task 7: Policy orchestration

**Files:**
- Create: `worker/src/policy.py`
- Create: `src/tests/test_gb_policy.py`

**Interfaces:**
- Consumes:
  - `apply_swaps` from `worker/src/swaps.py` (Task 2)
  - `Blocklist`, `contains_blocked` from `worker/src/matching.py` (Task 5)
  - `worker/src/normalize.py` only transitively, via `matching.py`. `policy.py` does not import it directly.
- Produces:
  - `MAX_NAME: int = 40`, `MAX_MESSAGE: int = 500`
  - `Verdict` — frozen dataclass with `ok: bool`, `code: str | None`, `display: str | None`, `has_swap: bool`
  - `contains_url(text: str) -> bool`
  - `check_name(name, *, blocklist, allow) -> Verdict`
  - `check_message(message, *, blocklist, allow, swaps) -> Verdict`

  Task 8 imports all of these.

**Policy rules, from spec §6:**
- **Name:** slur check, URL check, length cap. **No profanity check, no joke-name list.** `James Cockburn`, `Dixie Normus`, and `Mike Hawk` all pass — this is intended.
- **Message:** slur check (block), URL check (block), length cap, profanity swap (render).
- Precedence: empty → too long → URL → blocked.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_gb_policy.py`:

```python
"""Policy orchestration: the order of checks and the codes they return."""
import unittest

from matching import Blocklist, digest
from policy import (
    MAX_MESSAGE,
    MAX_NAME,
    Verdict,
    check_message,
    check_name,
    contains_url,
)

BLOCKLIST = Blocklist(
    digests=frozenset({digest("zzblocked")}), minlen=3, maxlen=9, substr_minlen=5
)
ALLOW = frozenset()
SWAPS = {"fuck": "flip"}


class TestContainsUrl(unittest.TestCase):
    def test_detects_http(self):
        self.assertTrue(contains_url("see http://x.com"))

    def test_detects_https(self):
        self.assertTrue(contains_url("see https://x.com"))

    def test_detects_www(self):
        self.assertTrue(contains_url("see www.example.com"))

    def test_detects_bare_domain(self):
        self.assertTrue(contains_url("visit example.com today"))

    def test_detects_scheme_case_insensitively(self):
        self.assertTrue(contains_url("HTTP://X.COM"))

    def test_allows_ordinary_prose(self):
        self.assertFalse(contains_url("hello there, nice site"))

    def test_allows_a_sentence_ending_in_a_period(self):
        self.assertFalse(contains_url("I like it. A lot."))

    def test_allows_decimals(self):
        self.assertFalse(contains_url("version 3.12 is good"))

    def test_allows_an_ellipsis(self):
        self.assertFalse(contains_url("well...maybe"))


class TestCheckName(unittest.TestCase):
    def _check(self, name):
        return check_name(name, blocklist=BLOCKLIST, allow=ALLOW)

    def test_accepts_an_ordinary_name(self):
        self.assertTrue(self._check("Bret").ok)

    def test_rejects_empty(self):
        self.assertEqual(self._check("").code, "empty")

    def test_rejects_whitespace_only(self):
        self.assertEqual(self._check("   ").code, "empty")

    def test_accepts_exactly_max_length(self):
        self.assertTrue(self._check("a" * MAX_NAME).ok)

    def test_rejects_one_over_max_length(self):
        self.assertEqual(self._check("a" * (MAX_NAME + 1)).code, "name_too_long")

    def test_rejects_a_url(self):
        self.assertEqual(self._check("www.spam.com").code, "url_not_allowed")

    def test_rejects_a_slur(self):
        self.assertEqual(self._check("zzblocked").code, "blocked")

    def test_accepts_a_real_unfortunate_surname(self):
        # The whole point of names being slur-checked only.
        self.assertTrue(self._check("James Cockburn").ok)

    def test_accepts_a_joke_name(self):
        # Joke names are permitted by design. See spec 6.4.
        self.assertTrue(self._check("Mike Hawk").ok)

    def test_accepts_profanity_in_a_name(self):
        # Names are NOT profanity-checked.
        self.assertTrue(self._check("Fuckface McGee").ok)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(self._check("  Bret  ").display, "Bret")

    def test_length_is_measured_after_stripping(self):
        self.assertTrue(self._check("  " + "a" * MAX_NAME + "  ").ok)


class TestCheckMessage(unittest.TestCase):
    def _check(self, message):
        return check_message(
            message, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
        )

    def test_accepts_an_ordinary_message(self):
        self.assertTrue(self._check("nice site").ok)

    def test_rejects_empty(self):
        self.assertEqual(self._check("").code, "empty")

    def test_accepts_exactly_max_length(self):
        self.assertTrue(self._check("a" * MAX_MESSAGE).ok)

    def test_rejects_one_over_max_length(self):
        self.assertEqual(
            self._check("a" * (MAX_MESSAGE + 1)).code, "message_too_long"
        )

    def test_rejects_a_url(self):
        self.assertEqual(self._check("buy at spam.com").code, "url_not_allowed")

    def test_rejects_a_slur(self):
        self.assertEqual(self._check("you zzblocked").code, "blocked")

    def test_swaps_profanity_and_flags_it(self):
        verdict = self._check("hey fuck you")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.display, "hey flip you")
        self.assertTrue(verdict.has_swap)

    def test_clean_message_reports_no_swap(self):
        self.assertFalse(self._check("hey there").has_swap)

    def test_display_is_none_when_rejected(self):
        self.assertIsNone(self._check("zzblocked").display)


class TestPrecedence(unittest.TestCase):
    """Order matters: the visitor should see the most actionable error."""

    def test_too_long_beats_url(self):
        verdict = check_message(
            "spam.com " + "a" * MAX_MESSAGE,
            blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS,
        )
        self.assertEqual(verdict.code, "message_too_long")

    def test_url_beats_blocked(self):
        verdict = check_message(
            "zzblocked spam.com", blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
        )
        self.assertEqual(verdict.code, "url_not_allowed")

    def test_empty_beats_everything(self):
        verdict = check_message(
            "   ", blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
        )
        self.assertEqual(verdict.code, "empty")


class TestVerdict(unittest.TestCase):
    def test_is_immutable(self):
        verdict = Verdict(ok=True, code=None, display="x", has_swap=False)
        with self.assertRaises(Exception):
            verdict.ok = False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest src.tests.test_gb_policy -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy'`

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/policy.py`:

```python
"""Content policy orchestration.

Pure functions. Stdlib only. Wordlists are injected, never read here.

Names are checked for slurs, URLs, and length ONLY. No profanity check and
no joke-name list: 'James Cockburn' is a real surname and 'Mike Hawk' is a
joke the site owner finds funny. Blocking either costs more than it saves.
See specs/2026-08-20-guestbook-design.md section 6.4.
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass

from matching import Blocklist, contains_blocked
from swaps import apply_swaps

MAX_NAME = 40
MAX_MESSAGE = 500

# Scheme, www., or a bare domain with a known-ish TLD shape. Deliberately
# broad: a false positive costs the visitor a rephrase, while a miss hands
# a link spammer the payload the whole policy exists to deny.
_URL = re.compile(
    r"(https?://)"
    r"|(\bwww\.[a-z0-9-]+)"
    r"|(\b[a-z0-9-]+\.[a-z]{2,63}\b(?![.\d]))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Verdict:
    """Outcome of a policy check.

    `display` carries the render-ready text when ok, and None when not.
    """

    ok: bool
    code: str | None
    display: str | None
    has_swap: bool


def contains_url(text: str) -> bool:
    """True when `text` contains anything that reads as a link."""
    return bool(_URL.search(text))


def check_name(name: str, *, blocklist: Blocklist, allow: frozenset[str]) -> Verdict:
    """Validate a submitted name. Slurs, URLs, and length only."""
    cleaned = name.strip()

    if not cleaned:
        return Verdict(False, "empty", None, False)
    if len(cleaned) > MAX_NAME:
        return Verdict(False, "name_too_long", None, False)
    if contains_url(cleaned):
        return Verdict(False, "url_not_allowed", None, False)
    if contains_blocked(cleaned, blocklist, allow):
        return Verdict(False, "blocked", None, False)

    return Verdict(True, None, cleaned, False)


def check_message(
    message: str,
    *,
    blocklist: Blocklist,
    allow: frozenset[str],
    swaps: Mapping[str, str],
) -> Verdict:
    """Validate a submitted message and produce its display form.

    The returned `display` is the swapped text. The RAW message is what the
    caller stores; this function never rewrites what gets persisted.
    """
    cleaned = message.strip()

    if not cleaned:
        return Verdict(False, "empty", None, False)
    if len(cleaned) > MAX_MESSAGE:
        return Verdict(False, "message_too_long", None, False)
    if contains_url(cleaned):
        return Verdict(False, "url_not_allowed", None, False)
    if contains_blocked(cleaned, blocklist, allow):
        return Verdict(False, "blocked", None, False)

    display, has_swap = apply_swaps(cleaned, swaps)
    return Verdict(True, None, display, has_swap)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest src.tests.test_gb_policy -v`
Expected: PASS, all tests

- [ ] **Step 5: Drive mutation score to 100%**

```bash
find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
```

| Mutation | Must be killed by |
|---|---|
| `> MAX_NAME` → `>= MAX_NAME` | `test_accepts_exactly_max_length` |
| `> MAX_MESSAGE` → `>= MAX_MESSAGE` | `test_accepts_exactly_max_length` |
| `MAX_NAME = 40` → `41` | `test_rejects_one_over_max_length` |
| `MAX_MESSAGE = 500` → `501` | `test_rejects_one_over_max_length` |
| swap the URL and blocked checks | `test_url_beats_blocked` |
| move the empty check below the length check | `test_empty_beats_everything` |
| add a `contains_blocked` profanity check to `check_name` | `test_accepts_profanity_in_a_name` |
| `name.strip()` → `name` | `test_strips_surrounding_whitespace` |
| `has_swap` hardcoded `False` | `test_swaps_profanity_and_flags_it` |

- [ ] **Step 6: Run the full gate and commit**

```bash
./test.sh
git add worker/src/policy.py src/tests/test_gb_policy.py
git commit -m "Add content policy orchestration

Names are slur/URL/length checked only — no profanity check and no
joke-name list, so 'James Cockburn' and 'Mike Hawk' both post.

check_message returns the display form; the caller stores the raw text.
This function never rewrites what gets persisted."
```

---

## Task 8: Worker HTTP layer

**Files:**
- Create: `worker/src/entry.py`
- Modify: `worker/wrangler.toml` (append the D1 binding and vars)

**Interfaces:**
- Consumes: `check_name`, `check_message` from `policy.py` (Task 7); `load_blocked`, `load_allow` from `matching.py` (Task 5); `apply_swaps`, `load_swaps` from `swaps.py` (Task 2); `schema.sql` (Task 3)
- Produces: the live API. Task 9 calls the `/admin/*` routes.

**This module is deliberately thin.** It holds no branching policy — that all lives in the pure modules, which are already tested to 100% mutation. Route behaviour is smoke-tested against `wrangler dev` rather than unit-tested, and that is only acceptable *because* there is no logic here to get wrong. If you find yourself adding an `if` about content, it belongs in `policy.py`.

- [ ] **Step 1: Add the bindings**

Append to `worker/wrangler.toml`, substituting the `database_id` printed in Task 3:

```toml
[[d1_databases]]
binding = "DB"
database_name = "guestbook"
database_id = "PASTE_THE_ID_FROM_TASK_3"

[vars]
ALLOWED_ORIGIN = "https://bretzanotelli.work"

[[routes]]
pattern = "api.bretzanotelli.work/*"
zone_name = "bretzanotelli.work"
```

- [ ] **Step 2: Write the Worker**

Create `worker/src/entry.py`:

```python
"""Guestbook HTTP layer.

A thin shell. Every decision about content lives in the pure policy
modules, which are tested to 100% mutation by the repo's normal suite.
Nothing here branches on what a message says — if you are adding an `if`
about content, it belongs in policy.py.
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from workers import Response

from matching import load_allow, load_blocked
from policy import check_message, check_name
from swaps import apply_swaps, load_swaps

_DATA = Path(__file__).resolve().parent.parent / "data"

# Loaded once per isolate, not per request.
BLOCKLIST = load_blocked(str(_DATA / "blocked.txt"))
ALLOW = load_allow(str(_DATA / "allow.txt"))
SWAPS = load_swaps(str(_DATA / "swaps.txt"))

MAX_BODY = 4096
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

BURST_WINDOW = timedelta(minutes=10)
BURST_MAX = 3
DAILY_WINDOW = timedelta(hours=24)
DAILY_MAX = 10


def _cors(env):
    return {
        "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json",
    }


def _json(env, payload, status=200):
    return Response(json.dumps(payload), status=status, headers=_cors(env))


def _ip_hash(request, env) -> str:
    ip = request.headers.get("cf-connecting-ip") or "unknown"
    salted = (env.RATE_SALT + ip).encode("utf-8")
    return hashlib.sha256(salted).hexdigest()[:32]


def verify_challenge(request) -> bool:
    """Bot-verification seam. Hardcoded open.

    To enable Cloudflare Turnstile: read the `cf-turnstile-response` field
    from the parsed body, POST it with env.TURNSTILE_SECRET to
    https://challenges.cloudflare.com/turnstile/v0/siteverify, and return
    the `success` field. Nothing else in this file changes.
    """
    return True


def _is_admin(request, env) -> bool:
    header = request.headers.get("authorization") or ""
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    return hmac.compare_digest(header[len(prefix):], env.ADMIN_TOKEN)


async def _rate_limited(env, ip_hash) -> bool:
    now = datetime.now(UTC)
    for window, cap in ((BURST_WINDOW, BURST_MAX), (DAILY_WINDOW, DAILY_MAX)):
        since = (now - window).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = await (
            env.DB.prepare(
                "SELECT COUNT(*) AS n FROM entries "
                "WHERE ip_hash = ? AND created_at > ?"
            )
            .bind(ip_hash, since)
            .first()
        )
        if row and row["n"] >= cap:
            return True
    return False


async def _list_entries(env, limit, include_hidden=False):
    sql = (
        "SELECT id, name, message, created_at, hidden, block_reason "
        "FROM entries "
        + ("" if include_hidden else "WHERE hidden = 0 ")
        + "ORDER BY id DESC LIMIT ?"
    )
    result = await env.DB.prepare(sql).bind(limit).all()
    return result.results or []


async def _get_entries(request, env):
    query = parse_qs(urlparse(request.url).query)
    raw_limit = (query.get("limit") or [None])[0]
    try:
        limit = int(raw_limit) if raw_limit else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    rows = await _list_entries(env, limit)
    entries = []
    for row in rows:
        # Rendering applies the swap and NOTHING else.
        #
        # Re-running the full policy here would be a trap: if the denylist
        # later grows, a stored entry could start failing the check and
        # fall through to raw text -- serving the unswapped slur, the exact
        # opposite of what blocking is for. Deciding an entry should
        # disappear is moderation's job, not the read path's.
        display, has_swap = apply_swaps(row["message"], SWAPS)
        entries.append({
            "id": row["id"],
            "name": row["name"],
            "message_display": display,
            "message_raw": row["message"],
            "has_swap": has_swap,
            "created_at": row["created_at"],
        })
    return _json(env, {"entries": entries})


async def _post_entry(request, env):
    raw = await request.text()
    if len(raw) > MAX_BODY:
        return _json(env, {"ok": False, "code": "message_too_long"}, 400)

    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return _json(env, {"ok": False, "code": "empty"}, 400)

    # Honeypot. Bots fill it. The response is indistinguishable from
    # success so they never learn they were caught.
    if (body.get("website") or "").strip():
        return _json(env, {"ok": True})

    if not verify_challenge(request):
        return _json(env, {"ok": False, "code": "blocked"}, 400)

    raw_name = str(body.get("name") or "").strip()
    raw_message = str(body.get("message") or "").strip()

    name_verdict = check_name(raw_name, blocklist=BLOCKLIST, allow=ALLOW)
    msg_verdict = check_message(
        raw_message, blocklist=BLOCKLIST, allow=ALLOW, swaps=SWAPS
    )

    ip_hash = _ip_hash(request, env)
    if await _rate_limited(env, ip_hash):
        return _json(env, {"ok": False, "code": "rate_limited"}, 429)

    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # A slur in EITHER field is stored hidden rather than destroyed, so a
    # filter misfire is auditable instead of invisible. Spec sections 3,
    # 7, and 11. The name is checked too: 'blocked' must not be able to
    # slip through by being in the name field instead of the message.
    if "blocked" in (name_verdict.code, msg_verdict.code):
        await (
            env.DB.prepare(
                "INSERT INTO entries "
                "(name, message, created_at, ip_hash, hidden, block_reason) "
                "VALUES (?, ?, ?, ?, 1, 'slur')"
            )
            .bind(raw_name, raw_message, created_at, ip_hash)
            .run()
        )
        return _json(env, {"ok": False, "code": "blocked"}, 400)

    # Every other rejection is a formatting problem the visitor can fix
    # themselves. Nothing is stored: there is no misfire to audit.
    if not name_verdict.ok:
        return _json(env, {"ok": False, "code": name_verdict.code}, 400)
    if not msg_verdict.ok:
        return _json(env, {"ok": False, "code": msg_verdict.code}, 400)

    await (
        env.DB.prepare(
            "INSERT INTO entries "
            "(name, message, created_at, ip_hash, hidden) "
            "VALUES (?, ?, ?, ?, 0)"
        )
        .bind(name_verdict.display, raw_message, created_at, ip_hash)
        .run()
    )

    return _json(env, {"ok": True, "entry": {
        "name": name_verdict.display,
        "message_display": msg_verdict.display,
        "message_raw": raw_message,
        "has_swap": msg_verdict.has_swap,
        "created_at": created_at,
    }}, 201)


async def _admin(request, env, path):
    if not _is_admin(request, env):
        return _json(env, {"ok": False, "code": "unauthorized"}, 401)

    if path == "/admin/entries":
        rows = await _list_entries(env, MAX_LIMIT, include_hidden=True)
        return _json(env, {"entries": [dict(r) for r in rows]})

    parts = path.strip("/").split("/")
    # admin / entries / <id> / <action>
    if len(parts) == 4 and parts[1] == "entries":
        entry_id, action = parts[2], parts[3]
        if action in ("hide", "unhide"):
            hidden = 1 if action == "hide" else 0
            reason = "manual" if hidden else None
            await (
                env.DB.prepare(
                    "UPDATE entries SET hidden = ?, block_reason = ? WHERE id = ?"
                )
                .bind(hidden, reason, entry_id)
                .run()
            )
            return _json(env, {"ok": True})

    return _json(env, {"ok": False, "code": "not_found"}, 404)


async def on_fetch(request, env):
    path = urlparse(request.url).path
    method = request.method

    if method == "OPTIONS":
        return Response("", status=204, headers=_cors(env))

    if path.startswith("/admin"):
        return await _admin(request, env, path)

    if path == "/entries":
        if method == "GET":
            return await _get_entries(request, env)
        if method == "POST":
            return await _post_entry(request, env)

    return _json(env, {"ok": False, "code": "not_found"}, 404)
```

- [ ] **Step 3: Set the local secrets**

```bash
cd worker
cat > .dev.vars <<'EOF'
ADMIN_TOKEN=local-dev-token-not-a-real-secret
RATE_SALT=local-dev-salt-not-a-real-secret
EOF
```

Confirm it is ignored: `git check-ignore -v worker/.dev.vars` must print a match.

- [ ] **Step 4: Smoke-test every route against wrangler dev**

```bash
cd worker && npx wrangler dev
```

In a second terminal, each of these must produce the stated result:

```bash
API=http://localhost:8787

# 1. Clean submission -> 201
curl -s -o /dev/null -w '%{http_code}\n' -X POST $API/entries \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bret","message":"nice site","website":""}'
# expect 201

# 2. Read it back
curl -s "$API/entries?limit=5"
# expect the entry, with message_display == message_raw and has_swap false

# 3. Profanity -> stored raw, swapped on read
curl -s -X POST $API/entries -H 'Content-Type: application/json' \
  -d '{"name":"Friend","message":"hey fuck you","website":""}'
curl -s "$API/entries?limit=1"
# expect message_display "hey flip you", message_raw "hey fuck you",
# has_swap true

# 4. Honeypot -> 200, nothing stored
curl -s -X POST $API/entries -H 'Content-Type: application/json' \
  -d '{"name":"Bot","message":"spam","website":"http://spam.com"}'
curl -s "$API/entries?limit=50" | grep -c '"name":"Bot"'
# expect 0

# 5. URL -> 400 url_not_allowed
curl -s -X POST $API/entries -H 'Content-Type: application/json' \
  -d '{"name":"X","message":"buy at spam.com","website":""}'

# 6. Real surname -> 201, NOT blocked
curl -s -o /dev/null -w '%{http_code}\n' -X POST $API/entries \
  -H 'Content-Type: application/json' \
  -d '{"name":"James Cockburn","message":"hello","website":""}'
# expect 201

# 7. Rate limit -> 4th rapid submission is 429
for i in 1 2 3 4; do
  curl -s -o /dev/null -w '%{http_code} ' -X POST $API/entries \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"R$i\",\"message\":\"m$i\",\"website\":\"\"}"
done; echo
# expect the 4th to be 429

# 8. Admin without a token -> 401
curl -s -o /dev/null -w '%{http_code}\n' $API/admin/entries
# expect 401

# 9. Admin with the token -> 200
curl -s $API/admin/entries \
  -H 'Authorization: Bearer local-dev-token-not-a-real-secret' | head -c 200

# 10. Wrong method -> 404
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE $API/entries
# expect 404

# 11. Slur in the NAME field (not the message) -> 400 blocked, stored hidden.
#     Substitute a real term from the denylist for <TERM>.
curl -s -X POST $API/entries -H 'Content-Type: application/json' \
  -d '{"name":"<TERM>","message":"hello","website":""}'
# expect {"ok":false,"code":"blocked"}
```

Also confirm the blocked path: submit a term from the real denylist, expect `400 blocked`, then check it landed hidden:

```bash
npx wrangler d1 execute guestbook --local \
  --command="SELECT id, hidden, block_reason FROM entries WHERE hidden = 1;"
# expect at least one row with block_reason = 'slur'
```

- [ ] **Step 5: Reset local data and commit**

```bash
npx wrangler d1 execute guestbook --local --command="DELETE FROM entries;"
cd ..
git add worker/src/entry.py worker/wrangler.toml
git commit -m "Add Worker HTTP layer

A thin shell over the pure policy modules. Holds no branching about
content — that is all in policy.py, tested to 100% mutation.

Honeypot returns a response indistinguishable from success so bots never
learn they were caught. Blocked entries are stored hidden rather than
destroyed. Admin token compared with hmac.compare_digest."
```

---

## Task 9: Moderation CLI

**Files:**
- Create: `scripts/guestbook_admin.py`

**Interfaces:**
- Consumes: the `/admin/*` routes (Task 8). Built against the documented contract, so it can be written in parallel with Task 8.
- Produces: nothing other tasks consume.

**Standalone, like `scripts/spotify_auth.py`:** stdlib only, no `src/` imports, runnable on any machine with Python.

`--review` is the feedback loop for the filter. If real people are being caught by a Scunthorpe-class bug, this is the only place it becomes visible instead of silent. When it shows one, add the word to `worker/data/allow.txt` — do not weaken the filter.

- [ ] **Step 1: Write the script**

Create `scripts/guestbook_admin.py`:

```python
#!/usr/bin/env python3
"""Guestbook moderation.

Standalone: stdlib only, no src/ imports, runs anywhere.

    export GUESTBOOK_ADMIN_TOKEN=...
    python3 scripts/guestbook_admin.py --list
    python3 scripts/guestbook_admin.py --review
    python3 scripts/guestbook_admin.py --hide 41
    python3 scripts/guestbook_admin.py --unhide 41

--review shows entries the FILTER blocked. It is the only place a
Scunthorpe-class misfire becomes visible. When it shows a real person,
add their word to worker/data/allow.txt — do not weaken the filter.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("GUESTBOOK_API", "https://api.bretzanotelli.work")
TOKEN_VAR = "GUESTBOOK_ADMIN_TOKEN"


def _call(path, method="GET"):
    token = os.environ.get(TOKEN_VAR)
    if not token:
        print(f"ERROR: {TOKEN_VAR} is not set", file=sys.stderr)
        raise SystemExit(2)

    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"ERROR: {exc.code} {exc.reason} for {path}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"ERROR: could not reach {API}: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from exc


def _print(entries):
    if not entries:
        print("(none)")
        return
    for entry in entries:
        flag = "HIDDEN" if entry.get("hidden") else "live  "
        reason = entry.get("block_reason") or ""
        print(f"[{entry['id']:>5}] {flag} {reason:<7} "
              f"{entry['created_at']}  {entry['name']}")
        print(f"          {entry['message']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="show live entries")
    group.add_argument("--review", action="store_true",
                       help="show entries the filter blocked")
    group.add_argument("--all", action="store_true",
                       help="show everything, hidden included")
    group.add_argument("--hide", metavar="ID", help="hide an entry")
    group.add_argument("--unhide", metavar="ID", help="restore an entry")
    args = parser.parse_args()

    if args.hide:
        _call(f"/admin/entries/{args.hide}/hide", "POST")
        print(f"Hid entry {args.hide}")
        return 0

    if args.unhide:
        _call(f"/admin/entries/{args.unhide}/unhide", "POST")
        print(f"Restored entry {args.unhide}")
        return 0

    entries = _call("/admin/entries").get("entries", [])

    if args.list:
        _print([e for e in entries if not e.get("hidden")])
    elif args.review:
        blocked = [e for e in entries if e.get("block_reason") == "slur"]
        _print(blocked)
        if blocked:
            print("\nIf any of these are real people, add the word to "
                  "worker/data/allow.txt. Do not weaken the filter.")
    else:
        _print(entries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify against wrangler dev**

With `npx wrangler dev` running and a few entries submitted (including one blocked):

```bash
export GUESTBOOK_API=http://localhost:8787
export GUESTBOOK_ADMIN_TOKEN=local-dev-token-not-a-real-secret

python3 scripts/guestbook_admin.py --list      # live entries only
python3 scripts/guestbook_admin.py --review    # the blocked one
python3 scripts/guestbook_admin.py --all       # both
python3 scripts/guestbook_admin.py --hide 1
python3 scripts/guestbook_admin.py --list      # entry 1 gone
python3 scripts/guestbook_admin.py --unhide 1
python3 scripts/guestbook_admin.py --list      # entry 1 back
```

Then confirm the failure paths are clean, not tracebacks:

```bash
unset GUESTBOOK_ADMIN_TOKEN
python3 scripts/guestbook_admin.py --list      # expect "ERROR: ... not set", exit 2

export GUESTBOOK_ADMIN_TOKEN=wrong
python3 scripts/guestbook_admin.py --list      # expect "ERROR: 401", exit 1

export GUESTBOOK_API=http://localhost:9999
python3 scripts/guestbook_admin.py --list      # expect "could not reach", exit 1
```

- [ ] **Step 3: Lint and commit**

```bash
ruff check scripts/guestbook_admin.py
chmod +x scripts/guestbook_admin.py
git add scripts/guestbook_admin.py
git commit -m "Add guestbook moderation CLI

--review surfaces filter-blocked entries. It is the only place a
Scunthorpe-class misfire becomes visible rather than silent; the fix for
one is a line in allow.txt, never a weaker filter."
```

---

## Task 10: Deploy and verify live

**Files:**
- Modify: `worker/README.md` (append the deploy runbook)

**Interfaces:**
- Consumes: everything.
- Produces: a live guestbook.

- [ ] **Step 1: Set the production secrets**

Generate real values — do not reuse the dev ones:

```bash
cd worker
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # ADMIN_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # RATE_SALT

npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put RATE_SALT
```

Store both in a password manager. `RATE_SALT` cannot be recovered, and rotating it resets all rate-limit history.

- [ ] **Step 2: Deploy**

```bash
npx wrangler deploy
```

- [ ] **Step 3: Add the DNS record**

In the Cloudflare dashboard for `bretzanotelli.work`, confirm the Worker route `api.bretzanotelli.work/*` is bound. If `api` has no DNS record, add a proxied (orange-cloud) `AAAA` record for `api` pointing at `100::`; the Worker route intercepts before it resolves.

- [ ] **Step 4: Verify the live API**

```bash
API=https://api.bretzanotelli.work

curl -s "$API/entries?limit=5"
# expect {"entries":[]}

curl -s -o /dev/null -w '%{http_code}\n' -X POST $API/entries \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bret","message":"first","website":""}'
# expect 201

curl -s -I "$API/entries" | grep -i access-control-allow-origin
# expect https://bretzanotelli.work — NOT a wildcard
```

- [ ] **Step 5: Build and deploy the site**

```bash
cd .. && ./build.sh
git add docs/
git commit -m "Build site with guestbook"
```

- [ ] **Step 6: Verify end to end in a browser**

On the live site, confirm each:

1. `bretzanotelli.work` — the guestbook cell shows the live signature.
2. `bretzanotelli.work/guestbook.html` — entries render; signing one makes it appear.
3. Submit profanity — the swapped form shows, and "show original" reveals the raw text.
4. Submit a message containing a link — the URL error appears.
5. Submit a slur — the Bender panel appears. Then `python3 scripts/guestbook_admin.py --review` lists it.
6. Sign four times rapidly — the fourth is rate-limited.
7. Devtools → Network → Offline, reload the landing page — the cached signature or the blacked-out card, and **no console errors**.
8. Disable JS entirely — the landing card still shows a working "Sign it →" link.

- [ ] **Step 7: Append the runbook**

Add to `worker/README.md`:

```markdown
## Deploy

```bash
cd worker && npx wrangler deploy
```

## Moderation

```bash
export GUESTBOOK_ADMIN_TOKEN=...
python3 ../scripts/guestbook_admin.py --review   # filter-blocked entries
python3 ../scripts/guestbook_admin.py --hide 41
```

`--review` is the filter's feedback loop. If it shows a real person was
caught, add the word to `data/allow.txt` and redeploy. Never weaken the
matcher to fix one false positive.

## Updating the denylist

The plaintext term list is NEVER committed. Keep it outside the repo:

```bash
python3 ../scripts/hash_terms.py ~/gb-terms.txt data/blocked.txt
npx wrangler deploy
```

## Known limits

- Python Workers are in open beta. The logic worth protecting lives in the
  four pure modules and is portable to any runtime.
- "Punching down" is not encodable. The filter enforces the slur rule; the
  owner enforces the rest with `--hide`.
- Coded and tertiary terms evolve faster than a static list. `--review` is
  the backstop.
```

- [ ] **Step 8: Commit and merge**

```bash
git add worker/README.md
git commit -m "Add deploy and moderation runbook"
./test.sh   # final gate: all test_gb_* green, no new baseline failures
```

---

## Post-Implementation

- [ ] Enable `https_enforced` on the GitHub Pages config (spec §12). Currently `false`; Cloudflare terminates TLS so it is not exploitable, but it should be on.
- [ ] Write the live now-playing spec. One route on this Worker, reusing the `user-read-currently-playing` scope already granted in the Spotify work.
- [ ] Workshop Turnstile via the `verify_challenge` seam in `entry.py`.
- [ ] Supply `static/bender-reject.webp` if it was not ready during Task 4.
- [x] ~~Delete `MIGRATION_NOTES.txt`~~ — done by Bret in `origin/main` commit `181206e`.
