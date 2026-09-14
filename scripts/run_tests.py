#!/usr/bin/env python3
"""Run the unittest suite and gate on a recorded baseline.

The suite carries pre-existing failures unrelated to current work (see
specs/2026-08-09-spotify-listening-design.md section 12). Fixing them is a
separate cleanup. This runner therefore enforces two independent rules:

  1. No NEW failures: total failures/errors must not exceed BASELINE.
  2. Strict modules must be 100% green, no baseline forgiveness. A module
     is strict if it is named in STRICT or its name starts with
     STRICT_PREFIX ("test_gb_").

New work is always strict. Only the stale legacy tests get baseline
forgiveness.

MUTATION TESTING WARNING
------------------------
Clear __pycache__ (or use `python3 -B`) between mutants. CPython invalidates
bytecode on (mtime, size), so a mutant that does not change the file's SIZE --
e.g. flipping the constant 30 to 14, both two characters -- can leave the
interpreter running bytecode compiled from the PREVIOUS source if both edits
land within the same second. That produces a silent FALSE result: a mutant
that looks killed but was never actually executed, or vice versa. This bit us
once already while verifying WARN_THRESHOLD_DAYS.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "src" / "tests"

# Measured 2026-08-09 against the stale pre-existing suite.
BASELINE_FAILURES = 11
BASELINE_ERRORS = 9

# Floor for "discovery clearly worked." Not a suite-size target -- that's
# what BASELINE_FAILURES/ERRORS and STRICT track. This exists only to catch
# _discover() silently returning zero (or near-zero) tests without raising
# (pattern mismatch after a rename, wrong TESTS_DIR, files moved to a
# non-matching name), which would otherwise report testsRun=failures=
# errors=0 and pass vacuously since 0 is never > BASELINE_FAILURES/ERRORS.
# Set comfortably below the original legacy-only baseline (39 tests, before
# any STRICT modules existed) so it never needs bumping as new STRICT
# modules are added, but far enough above zero that an empty/near-empty
# discovery can't slip through.
MINIMUM_EXPECTED_TESTS = 20

# Modules that must be fully green. Two sources:
#   1. STRICT -- explicit legacy list, from the Spotify work.
#   2. STRICT_PREFIX -- anything named test_gb_*.py is strict automatically.
#
# The prefix rule exists so parallel guestbook tasks never edit this file.
# Seven worktrees each appending to a shared tuple conflicts every time; a
# prefix rule costs one edit here and zero afterwards.
STRICT: tuple[str, ...] = (
    "test_check_token_age",
    "test_render_listening",
    "test_fetch_listening",
)

STRICT_PREFIX = "test_gb_"


def is_strict_module(name: str) -> bool:
    """True when `name` must be held to 100% green, no baseline forgiveness."""
    return name in STRICT or name.startswith(STRICT_PREFIX)


def _strict_modules() -> list[str]:
    """Explicit strict modules plus every discovered test_gb_* module."""
    found = sorted(p.stem for p in TESTS_DIR.glob(f"{STRICT_PREFIX}*.py"))
    return list(STRICT) + found


def _discover(pattern="test*.py"):
    return unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR),
        top_level_dir=str(TESTS_DIR),
        pattern=pattern,
    )


def main():
    # repo root so `from src.xxx import yyy` resolves (most test files use
    # this form); src/ for Gen_Content.* and bare-module imports (e.g.
    # `from markdown_to_blocks import ...`); scripts/ for the fetch and
    # token modules; worker/src/ for the guestbook policy modules, which
    # import each other bare because the deployed Worker roots itself at
    # worker/src (see worker/wrangler.toml `main`). An import of
    # worker.src.X would resolve here and then fail on Worker cold start.
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

    runner = unittest.TextTestRunner(verbosity=2)
    strict_ok = True

    for name in _strict_modules():
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

    discovery_ok = full.testsRun >= MINIMUM_EXPECTED_TESTS
    if not discovery_ok:
        print(f"FAIL: full-suite discovery only found {full.testsRun} "
              f"tests (expected at least {MINIMUM_EXPECTED_TESTS}) -- "
              "discovery likely broke silently rather than the suite "
              "actually improving; treating as a hard failure")

    regressed = failures > BASELINE_FAILURES or errors > BASELINE_ERRORS
    if regressed:
        print("FAIL: new failures relative to recorded baseline")
    if not strict_ok:
        print("FAIL: strict modules must be fully green")

    return 1 if (regressed or not strict_ok or not discovery_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
