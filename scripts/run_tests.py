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
    # repo root so `from src.xxx import yyy` resolves (most test files use
    # this form); src/ for Gen_Content.* and bare-module imports (e.g.
    # `from markdown_to_blocks import ...`); scripts/ for the fetch and
    # token modules added by later tasks.
    sys.path.insert(0, str(REPO_ROOT))
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
