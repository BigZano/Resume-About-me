#!/usr/bin/env python3
"""Turn the RSDB listing into a candidate term list for hash_terms.py.

    python3 scripts/import_rsdb_terms.py ~/rsdb.html ~/gb-terms.txt

Input is a saved copy of http://www.rsdb.org/races (fetch it yourself;
this script never makes a network request). Output is plaintext terms,
one per line, for `hash_terms.py` to digest.

NOTHING here prints a term. Counts only. The plaintext list is the one
thing in this project that must never reach a log, a transcript, or the
repository -- see the header of worker/src/data/blocked.txt.

Three buckets come out:

  <out>              terms safe to block outright
  <out>.review.txt   terms that need a human decision, and why
  <out>.dropped.txt  terms the matcher could never act on anyway

The review bucket is the point of this script. `matching.py` substring-
matches any term of `substr_minlen` characters or more, so importing a
list this size unchecked means blocking every message containing a
legitimate word that happens to have a slur inside it. That failure is
silent: a real person is told their message was blocked and you never
find out unless they tell you. Every term that occurs inside a
dictionary word is therefore held back for review rather than trusted.

Terms shorter than `substr_minlen` are word-matched only, so they carry
no Scunthorpe risk and skip that check.
"""

import re
import sys
from pathlib import Path

# Must match the header hash_terms.py writes and matching.py reads.
MINLEN = 3
MAXLEN = 14
SUBSTR_MINLEN = 5

DICT_PATHS = (
    Path("/usr/share/dict/words"),
    Path("/usr/dict/words"),
)

SLUG = re.compile(r'href="/slur/([^"]+)"')


def load_dictionary() -> set[str]:
    """Lowercased dictionary words, for the Scunthorpe check.

    Includes two- and three-letter words — an earlier cut that skipped
    short words produced an 8.7% false-positive rate on a benign corpus.
    """
    for path in DICT_PATHS:
        if path.exists():
            words = set()
            with path.open(encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    word = line.strip().lower()
                    if word.isalpha():
                        words.add(word)
            return words
    return set()


def load_dictionary_forms(words: set[str]) -> set[str]:
    """Every reading the matcher derives from a dictionary word.

    `normalize.candidates` collapses repeated letters and folds leetspeak,
    so an innocent word can arrive at the matcher as a spelling its
    dictionary entry does not have. Checking terms against the raw
    spelling alone misses those collisions entirely.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker" / "src"))
    try:
        from normalize import candidates as forms_of
    except ImportError:
        return set()

    forms = set()
    for word in words:
        forms.update(forms_of(word))
    return forms


def candidates(html: str) -> list[str]:
    """Every term the listing links to, deduplicated, order preserved."""
    seen = {}
    for slug in SLUG.findall(html):
        term = slug.replace("+", " ").replace("%20", " ")
        term = re.sub(r"%[0-9a-fA-F]{2}", "", term).strip().lower()
        if term and term not in seen:
            seen[term] = None
    return list(seen)


def canonical(term: str) -> str:
    """What the matcher will actually compare: alphanumerics only.

    hash_terms.py does this too. Doing it here as well is what makes the
    length and dictionary checks below measure the real thing rather
    than the decorated form.
    """
    return re.sub(r"[^a-z0-9]", "", term.lower())


def classify(terms: list[str], words: set[str], forms: set[str]):
    keep, review, dropped = [], [], []

    for term in terms:
        canon = canonical(term)

        if not canon:
            dropped.append((term, "nothing left after canonicalization"))
            continue
        if len(canon) < MINLEN:
            dropped.append((term, f"under minlen={MINLEN}"))
            continue
        if len(canon) > MAXLEN:
            dropped.append((term, f"over maxlen={MAXLEN}"))
            continue
        if " " in term.strip() and len(canon) > MAXLEN:
            dropped.append((term, "multi-word, over bounds once joined"))
            continue

        if canon in words:
            review.append((term, "is itself a dictionary word"))
            continue

        if canon in forms:
            review.append((term, "is a collapsed or de-leeted reading of "
                                 "an ordinary word"))
            continue

        # Word-matched only below the substring floor: no substring risk.
        if len(canon) < SUBSTR_MINLEN:
            keep.append(canon)
            continue

        hits = [w for w in words if canon in w]
        if hits:
            sample = ", ".join(sorted(hits, key=len)[:3])
            review.append((term, f"occurs inside {len(hits)} words e.g. {sample}"))
            continue

        keep.append(canon)

    return keep, review, dropped


def write(path: Path, lines) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2

    source = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser()

    if not source.exists():
        print(f"ERROR: {source} does not exist", file=sys.stderr)
        return 1
    if str(out).startswith(str(Path(__file__).resolve().parents[1])):
        print("ERROR: refusing to write plaintext terms inside the repo",
              file=sys.stderr)
        return 1

    words = load_dictionary()
    forms = load_dictionary_forms(words) if words else set()
    if not words:
        print("WARNING: no system dictionary found; every long term will "
              "be sent to review, since the Scunthorpe check cannot run.",
              file=sys.stderr)

    terms = candidates(source.read_text(errors="replace"))
    keep, review, dropped = classify(terms, words, forms)

    write(out, sorted(set(keep)))
    write(out.with_suffix(".review.txt"),
          [f"{term}\t{why}" for term, why in review])
    write(out.with_suffix(".dropped.txt"),
          [f"{term}\t{why}" for term, why in dropped])

    print(f"found      {len(terms):5d} terms in the listing")
    print(f"accepted   {len(set(keep)):5d} -> {out}")
    print(f"review     {len(review):5d} -> {out.with_suffix('.review.txt')}")
    print(f"dropped    {len(dropped):5d} -> {out.with_suffix('.dropped.txt')}")
    print()
    print("Read the review file before deciding. Anything you keep from it")
    print("goes on the end of the accepted file by hand. Then:")
    print(f"  python3 scripts/hash_terms.py {out} "
          "worker/src/data/blocked.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
