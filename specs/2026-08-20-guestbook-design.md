# Guestbook — Design

Status: approved for planning
Date: 2026-08-20
Supersedes: nothing. Fulfils the deferral in
`specs/2026-08-09-spotify-listening-design.md` §2 and §13.

---

## 1. Problem

The site is a static build committed to `docs/` and served by GitHub Pages.
There is no write path of any kind. A guestbook needs one: somewhere to accept a
POST, somewhere to keep the result, and a read path fresh enough that a visitor
sees their own signature appear.

GitHub Pages cannot accept a POST at all. So this spec stands up the first
server-side component the site has ever had.

## 2. Scope boundary

**In scope:** the Worker, its datastore, the content policy, moderation
tooling, the `/guestbook.html` page, and the latest-signature cell on the
landing page.

Explicitly **out of scope**:

- **Live now-playing.** Rides this Worker in its own small spec once the Worker
  is proven. The `user-read-currently-playing` scope was already requested in
  the Spotify spec §6 precisely so no re-authorization is needed.
- **Bot / image verification (Turnstile).** A documented seam is built (§9). The
  check itself is not. Deferred until the user has workshopped it.
- **Joke-name detection.** Deliberately dropped. Joke names are permitted —
  see §6.4.
- **AI-assisted moderation.** Considered and rejected on fairness grounds.
  See §11.

## 3. Decisions

| Decision | Choice | Reasoning |
|---|---|---|
| Read freshness | Live fetch, instant publish | User requirement. A signature must appear immediately, not on the next build |
| Backend | Cloudflare Worker + D1 | Cloudflare already fronts the domain (DNS resolves to `172.67.180.38` / `104.21.67.198`). Free tier covers this many times over. No host to patch or keep powered. Turnstile drops in later |
| Worker language | **Python** (`python_workers` compat flag) | Matches the repo. The owner audits Python fluently and has said they cannot yet audit JS/TS. D1 bindings are supported. Cost: Python Workers are in open beta |
| Subdomain | `api.bretzanotelli.work` | Not `guestbook.` — now-playing rides the same Worker |
| Build coupling | **None** | The build stays offline and dependency-free. No network call is added to `build.sh`. This invariant is inherited from the Spotify spec and is not traded away |
| Slur handling | Hard block, entry stored `hidden=1` | Public never sees it. Storing it lets the owner audit filter misfires rather than have them be invisible |
| Profanity handling | Stored raw, swapped at render, click to reveal | Owner's humour is preserved; the page reads clean at a glance |
| Denylist storage | SHA-256 digests, in repo | The repo is **public** (`github.com/BigZano/Resume-About-me`). A plaintext wall of slurs in it is not acceptable. Digests stay versioned and reviewable |
| Name policy | Slur check **only** | Fixes the Scunthorpe class outright: Cockburn, Weiner, Kuntz, Hoare, Dickinson all post cleanly |
| Moderation | Soft hide, never destroy | A misclick costs nothing |
| Deletion of IP | Salted hash, never raw | Rate limiting works without holding visitors' addresses |

## 4. Components

| File | Runs | Knows about |
|---|---|---|
| `worker/src/content_policy.py` | Every submission | **Pure functions. No I/O, no network, no Cloudflare.** Text in, verdict out |
| `worker/src/entry.py` | Every request | HTTP, routing, D1. A thin shell. Holds no policy logic |
| `worker/schema.sql` | Once, at setup | D1 table + indexes |
| `worker/data/blocked.txt` | Loaded at cold start | SHA-256 digests, one per line |
| `worker/data/allow.txt` | Loaded at cold start | Plaintext false-positive allowlist |
| `worker/data/swaps.txt` | Loaded at cold start | Plaintext profanity → swap map |
| `scripts/guestbook_admin.py` | By hand | The admin API. stdlib only, no `src/` imports |
| `src/Gen_Content/generate_guestbook_page.py` | Every build | Templating only. **Never sees the Worker or the network** |

### The seam

`content_policy.py` is the whole point of this layout. Every piece of logic that
can be wrong — normalization, slur detection, false-positive suppression,
profanity swapping, URL rejection, length caps — lives there as pure functions
with the wordlists **injected as parameters**.

Consequences:

- It is tested by the existing `./test.sh` with stdlib `unittest`. No `wrangler`,
  no network, no Cloudflare account.
- Tests inject **benign fake wordlists**. The real denylist is never needed to
  prove the algorithm correct.
- `entry.py` holds no branching policy, so the part that can only be tested
  against a live runtime is also the part with nothing to get wrong.

## 5. Data contract

### D1 schema

```sql
CREATE TABLE IF NOT EXISTS entries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT    NOT NULL,
  message      TEXT    NOT NULL,          -- RAW, exactly as typed
  created_at   TEXT    NOT NULL,          -- ISO 8601 UTC, e.g. 2026-08-20T14:03:11Z
  ip_hash      TEXT    NOT NULL,          -- sha256(salt || ip), hex, truncated to 32
  hidden       INTEGER NOT NULL DEFAULT 0,
  block_reason TEXT                       -- NULL | 'slur' | 'manual'
);

CREATE INDEX IF NOT EXISTS idx_entries_visible ON entries (hidden, id DESC);
CREATE INDEX IF NOT EXISTS idx_entries_ip      ON entries (ip_hash, created_at);
```

`message` stores the raw text always. The swap is a **render-time transform**,
never a write-time one, so the policy stays reversible and nothing is lost.

`block_reason` separates "the filter caught this" from "the owner hid this",
which is what makes `--review` able to surface filter misfires.

### Public API

All responses `application/json`. CORS allows `https://bretzanotelli.work` only.

**`GET /entries?limit=N`** — `limit` default 25, max 100. Returns `hidden=0` only.

```json
{ "entries": [
    { "id": 41,
      "name": "Cockburn",
      "message_display": "hey what's up FLIP you",
      "message_raw":     "hey what's up fuck you",
      "has_swap": true,
      "created_at": "2026-08-20T14:03:11Z" } ] }
```

`has_swap` tells the client whether to render the reveal toggle at all.

**`POST /entries`** — body `{"name": "...", "message": "...", "website": ""}`

`website` is the honeypot. It is never a real field.

| Status | Body | When |
|---|---|---|
| 201 | `{"ok":true,"entry":{…}}` | Accepted |
| 200 | `{"ok":true}` | Honeypot filled. **Nothing stored.** Looks identical to success |
| 400 | `{"ok":false,"code":"…"}` | `empty`, `name_too_long`, `message_too_long`, `url_not_allowed`, `blocked` |
| 429 | `{"ok":false,"code":"rate_limited"}` | See §9 |

`code` is a stable machine string. The visible copy lives in the frontend, so
wording changes never touch the Worker.

### Admin API

Bearer token from Worker secret `ADMIN_TOKEN`. Constant-time compare.

- `GET  /admin/entries?include_hidden=1&reason=slur`
- `POST /admin/entries/:id/hide`
- `POST /admin/entries/:id/unhide`

## 6. Content policy

### 6.1 What is blocked

Hard block, all categories, no exceptions and no reclaimed-use carve-out —
everyone is subject to the same rule:

- Racial slurs
- LGBTQIA+ slurs, explicitly including transphobic slurs
- Antisemitic slurs
- Ableist slurs
- Tertiary terms and coded variants of the above

**Not blocked:** profanity, crass humour, dark humour, joke names, insults
aimed at the site owner.

Because the list contains **slur terms, not topics**, the antisemitic /
anti-Zionist distinction holds automatically. Political criticism uses ordinary
vocabulary and never touches the list. No special handling is required or built.

### 6.2 Normalization

Naive substring matching is beaten by `n1gger`, `nïgger`, `n i g g e r`,
`nnnigger`, and Cyrillic homoglyphs. Detection therefore runs over a **set of
candidate strings**, not one string:

1. NFKD normalize
2. Drop combining marks (`unicodedata.category(c) == 'Mn'`)
3. Drop zero-width and soft-hyphen chars (`U+200B`–`U+200D`, `U+FEFF`, `U+00AD`)
4. `casefold()`
5. Map confusables to Latin — Cyrillic `а е о р с х і ѕ`, Greek `α ο ρ ν τ`

**Steps 4 and 5 are in this order for a reason, and an earlier draft of this
spec had them reversed.** Confusable tables are keyed on lowercase Latin
targets. Casefolding capital Cyrillic `А` yields lowercase *Cyrillic* `а`, not
Latin `a` — so mapping before casefolding means the table never sees uppercase
homoglyphs at all, and `АЕОС` survives normalization as Cyrillic. The homoglyph
defense then silently fails on any capitalized evasion. Fold first, map second.

That yields the base form. Candidates are then generated from it:

| Candidate | Purpose |
|---|---|
| base | Ordinary usage |
| base + deleet (`0→o 1→i 3→e 4→a 5→s 7→t 8→b @→a $→s !→i \|→l +→t`) | `n1gg3r` |
| runs of 3+ collapsed to 1 | `fuuuck` → `fuck` |
| runs of 3+ collapsed to 2 | preserves genuine doubles (`ass`) |
| all non-alphanumerics stripped | `n.i.g.g.e.r`, `n i g g e r` |

Stripping and collapsing must **interleave**, not run in sequence. Collapsing
before stripping cannot fold `w o o o o r d`, because at collapse time the
repeated characters are not adjacent — the separators sit between them. The
order is strip → collapse → strip, which makes the candidate set a superset of
the naive one.

Deleet and collapse are **additive variants, never destructive** — the base form
is always checked too, so `1488`-style numeric terms are not mangled into
nonsense before matching.

### 6.3 The Scunthorpe problem

`Scunthorpe`, `assassin`, `analysis`, `classic`, `Cockburn`, `shiitake`, `bass`,
`pass`, `Sussex`, `Lipschitz`, `Uranus` all contain flagged substrings. Rejecting
them is a real bug, not a cosmetic one.

Order of operations, and the order is the whole fix:

```
normalize
  → REMOVE allowlisted safe words (word boundary)
  → generate candidates from the remainder
  → word-boundary scan  → hit = block
  → substring scan      → hit = block
```

The allowlist is subtracted **before** candidates are generated, so the
aggressive separator-stripped pass never sees the safe word at all.

### 6.4 Names

Names are checked for **slurs, URLs, and length only**. No profanity check, no
joke-name list, no AI. The URL check applies to the name field as well as the
message — the name field is a favourite place for link spam.

`James Cockburn`, `Dixie Normus`, and `Mike Hawk` all post. This is intended.
The owner's position: joke names are funny, only slurs are the line.

### 6.5 Profanity swap

Profanity is permitted, stored raw, and swapped for rendering. The swap
preserves case pattern: `FUCK → FLIP`, `Fuck → Flip`, `fuck → flip`.

The swap runs **server-side**, so it is single-source-of-truth and does not fail
open if the client's JS breaks. Both forms ship in the JSON; the client renders
`message_display` and reveals `message_raw` on request.

`worker/data/swaps.txt` is plaintext — a list of mild profanity and comic
replacements is not something that needs hiding. Words are tunable later;
Salamanders/Nocturne flavour is on the table given the site's theme.

### 6.6 Denylist storage

`worker/data/blocked.txt` holds **SHA-256 hex digests, one per line**, with a
header recording bounds:

```
# minlen=3 maxlen=14
3a7f9c2e…
b41d8e07…
```

Matching hashes each candidate token, and for the substring pass, each substring
of length `minlen..maxlen`. For a 500-char message that is roughly 4.5k hashes —
bounded and fast.

**The two passes use different minimums.** The word-boundary pass uses every
term. The separator-stripped substring pass uses only terms of length **≥ 5**.
Short terms are exactly the ones that appear innocently inside longer words, and
once separators are stripped the surrounding word boundaries are gone, so a
3-character term would fire constantly on ordinary text. The allowlist alone is
not sufficient protection at that length — it cannot enumerate every word in
English. The header records both bounds:

```
# minlen=3 maxlen=14 substr_minlen=5
```

The repo is public. Digests keep the list versioned, diffable, and reviewable
in PRs without putting a wall of slurs in a repository bearing the owner's name.
Tests never touch it; they inject benign fakes.

### 6.7 Limits, stated plainly

- **"Punching down" cannot be encoded.** The filter enforces the *slur* rule.
  A cruel joke about disabled people that uses no slur passes clean. That rule
  is enforced by the owner via `--hide`. The filter is a floor, not the policy.
- **Coded and tertiary terms are an arms race.** Numeric and symbolic
  dogwhistles evolve faster than any static list. It will lag. `--review` and
  `--hide` are the backstop.
- **Reclaimed use is indistinguishable from hostile use.** A friend signing
  affectionately with a reclaimed slur is blocked. This is a known, accepted
  cost of the "same rule for everyone" decision, and the reason blocked entries
  are stored rather than destroyed.

## 7. Flow

### Submit

```
browser → POST /entries
  ├ honeypot filled?        → 200, store nothing
  ├ oversized body (>4KB)?  → 400 before parsing
  ├ empty / too long?       → 400
  ├ URL in name OR message? → 400 url_not_allowed
  ├ rate limit exceeded?    → 429
  ├ slur in name/message?   → store hidden=1, reason='slur' → 400 blocked
  └ clean                   → store hidden=0 → 201
```

### Read

```
browser → GET /entries?limit=25
  → SELECT … WHERE hidden = 0 ORDER BY id DESC LIMIT ?
  → swap applied per row at render
```

## 8. Rendering

### Guestbook page

New template `guestbook.html` at repo root, alongside `template.html`,
`titlepage.html`, and `dev_diary_template.html`. Generated by
`src/Gen_Content/generate_guestbook_page.py`. Added to `PageLinks`.

Form:

```
[ Name    ]  ≤ 40
[ Message ]  ≤ 500, live counter
[ website ]  honeypot, visually hidden, aria-hidden, tabindex=-1
[ Sign it ]
```

Client-side caps and URL checks exist for instant feedback. **The server
revalidates everything.** Client checks are UX and are never trusted.

Status lives in an `aria-live="polite"` region. The button disables in flight.
Real `<label>` elements. Focus moves to the status region on response.

### Blocked response

On `code: "blocked"`, the form renders the Bender panel: an image pointing left
with the message *"Bite my shiny metal ass"*.

- **Two** assets, both supplied by the owner. CSS cannot swap an `<img>`
  `src` nor pause an animated WebP, so reduced-motion needs a second file
  rather than a media query over one element:
  - `static/bender-reject.webp` — animated
  - `static/bender-reject-still.webp` — one poster frame

  `build.sh` already copies `static/` → `docs/`.
- Ship as animated WebP or MP4, not GIF — roughly 10× smaller.
- `@media (prefers-reduced-motion: reduce)` serves a static poster frame.
- Real `alt` text.
- Note: Bender is 20th Television / Disney IP. Fan use on a personal site is
  low-risk and ubiquitous but unlicensed. Accepted by the owner.

### Landing cell

A 4th `.into-card` right of Cooking, class `.into-card--guestbook`.
`.into-grid` is `repeat(auto-fit, minmax(190px, 1fr))`, so it absorbs a 4th card
with **no CSS layout change**.

### Fallback chain

The landing page is the front door and now carries a live dependency. It must
fail as a design state, never as a broken box.

```
1. fetch OK    → render latest signature, write cache
2. fetch fails → read localStorage cache, render last known good
3. no cache    → blacked-out card
```

The blackout is deliberate, not an error state: the palette is already a forge
(`--soot`, `--ash`, `--iron`, `--flame`), so a cooled card reads as intentional
and stays on-theme with the footer's "forged in fire, tempered in code".

Cache rules:

- Key `gb_cache`, holding the current entry and one previous.
- **`message_display` only. Never `message_raw`.** A hidden entry can never
  resurface unswapped from a stale cache.
- 24h TTL, so a moderated entry self-evicts.
- Every read and write wrapped in `try/catch` — private browsing throws on
  access.

Known limit: the cache only helps returning visitors. A first-time visitor
during an outage still lands on the blackout. It narrows the window; it does not
close it. That is why both layers exist.

## 9. Abuse controls

**Rate limit**, on `ip_hash`, entirely in D1 — no extra service:

| Window | Cap |
|---|---|
| 10 minutes | 3 entries |
| 24 hours | 10 entries |

`ip_hash = sha256(RATE_SALT || cf-connecting-ip)[:32]`, salt from Worker secret.

**Honeypot** — hidden `website` field. Bots fill it; the response is a normal
200 and nothing is stored. Free, and catches the unsophisticated majority.

**Request hardening**

- CORS: `https://bretzanotelli.work` only. No wildcard.
- Methods: `GET`, `POST`, `OPTIONS`. Everything else 405.
- `Content-Type: application/json` required on POST.
- Body capped at 4KB, rejected **before** parsing.
- Admin routes compare the bearer token in constant time.

**Turnstile seam** — a single documented function in `entry.py`,
`verify_challenge(request) -> bool`, hardcoded to `True` with a comment naming
exactly what replaces it. When the owner wants bot verification, it is a few
lines in one place.

## 10. Moderation

`scripts/guestbook_admin.py`, stdlib only, matching the existing `scripts/`
convention (`spotify_auth.py`, `check_token_age.py`). Token read from env.

```
--list                 visible entries
--review               entries with block_reason='slur' — filter misfire audit
--hide ID
--unhide ID
```

`--review` is the feedback loop for §6.7. If real people are being caught, this
is where it becomes visible instead of silent.

## 11. Rejected alternatives

**AI-assisted name/content moderation (Workers AI).** Technically available and
free at this volume — 10,000 Neurons/day, binding built in. Rejected because an
LLM asked to judge whether a name is "real" over-flags names outside Western
convention. That does not remove the Cockburn problem; it relocates it onto
people with less common names, where the owner would never see it happening.
The failure modes are asymmetric: a joke name slipping through costs one
`--hide`, while a real person being told their name is unacceptable costs a
visitor and is invisible. Optimize for the invisible failure.

If revisited, AI must **flag, never block** — writing `suspect=1` into a review
queue, so a false positive costs a glance rather than a person.

**Go on Workers via TinyGo.** Keeps Workers + D1 and serves the owner's Go
learning, but depends on a community WASM shim, WASI on Workers is experimental,
and a ~0.75MB build sits against a 1MB free-tier cap.

**Go on a container host.** Real Go and real `net/http`, but abandons Workers +
D1, and free tiers sleep — which directly damages a live read path.

**Home Debian server behind a cloudflared tunnel.** No hosting fee, hardware
already running. Rejected because live reads make home power and ISP blips into
site downtime, and it points a public write path at the LAN holding ~10TB.

**Baking the latest entry into the build**, the way `listening.json` works.
A nicer offline fallback, but it puts a network call in the build and breaks the
offline clone-and-build invariant. Not traded away for a fallback string.

**Hard-deleting blocked entries.** Leaves filter misfires invisible and
unrecoverable. `hidden=1` costs nothing and makes §10's audit possible.

## 12. Known risks

- **Python Workers are in open beta** and require the `python_workers` compat
  flag. Breaking changes are possible. Accepted: the blast radius is a personal
  guestbook, and the logic worth protecting lives in `content_policy.py`, which
  is plain Python and portable to any runtime.
- **Cold starts.** Improved through late 2025, but a first request after idle is
  slower. The fallback chain in §8 already covers a slow or failed fetch.
- **`https_enforced` is `false`** on the GitHub Pages config. Cloudflare
  terminates TLS so this is not currently exploitable, but it should be enabled.
  Out of scope here; noted so it is not lost.

## 13. Testing

Per the repo's testing posture: adversarial by default, mutation is the bar.

**`content_policy.py` — 100% coverage and 100% mutation score.** It is pure, so
there is no excuse. Wordlists are injected, so tests use benign fakes.

Hostile battery, at minimum:

- Leetspeak, Cyrillic and Greek homoglyphs, zero-width joiners, soft hyphens
- Separator evasion: spaces, dots, dashes, underscores, newlines
- Repeat-run evasion, and the genuine-double case (`ass` must survive collapse)
- **A Scunthorpe corpus that must pass clean**: Scunthorpe, Cockburn, assassin,
  analysis, classic, shiitake, Lipschitz, Sussex, Uranus, bass, Weiner, Kuntz
- Empty, whitespace-only, exactly-at-cap, one-over-cap, 10KB input
- Emoji, RTL override marks, combining-mark stacks
- Case-pattern preservation in the swap
- URL forms: `http://`, `https://`, `www.`, bare domain, `user@host`

**Property tests:** normalization is idempotent; the swap never changes token
count; a clean string is never blocked by any candidate variant.

`entry.py` is deliberately thin. Route behaviour is smoke-tested against
`wrangler dev`.

**Mutation runs must clear `__pycache__` first.** Same-length mutants otherwise
read stale bytecode and report false survivors.

**Gate:** whole-suite regression check (no new failures against the recorded
baseline) plus `content_policy.py` at 100% coverage and mutation, wired into the
existing pre-push hook.

## 14. Deferred to follow-up specs

- **Live now-playing.** One route on this Worker, reusing credentials already
  scoped for it.
- **Turnstile**, via the §9 seam.
- **The stale `src/tests/` files.** The recorded baseline in
  `scripts/run_tests.py` is 11 failures / 9 errors; the suite currently runs 90
  tests at 11 failures / 6 errors. This spec, like the Spotify spec before it,
  deliberately leaves them alone.
