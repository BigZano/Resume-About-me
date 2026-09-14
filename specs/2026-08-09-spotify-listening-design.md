# Spotify "Listening" Pipeline — Design

**Date:** 2026-08-09
**Status:** Approved, ready for implementation planning
**Scope:** The `Listening` block on the landing page only.

> **Note on location:** this file is deliberately *not* in `docs/`. `src/main.py:49`
> runs `shutil.rmtree(docs_path)` on every build, so anything written to `docs/` is
> silently destroyed. Specs live in `specs/` at the repo root — tracked in git, and
> not published, since GitHub Pages serves `/docs` only.

---

## 1. Problem

`titlepage.html` has a `Listening` block in the `Now` sidebar with four hardcoded
placeholder tracks and a `not yet live` stamp. It should show what Bret actually
listens to, updating itself, without turning a dependency-free static site into
something that needs a server.

## 2. Scope boundary

This spec covers **only** the Listening block.

Explicitly **out of scope**, each deferred to its own spec:

- **Guestbook.** Needs a write path, persistence, spam handling, and a live
  endpoint. GitHub Pages cannot accept a POST at all. Entirely different problem.
- **Currently-playing.** See §9 — structurally incompatible with a weekly static
  build. Deferred to the backend the guestbook forces into existence.
- **Actions-based Pages deploy.** Cleaner than committing `docs/`, but a change to
  the deploy model that should stand on its own merits, not ride along here.

## 3. Decisions

| Decision | Choice | Reasoning |
|---|---|---|
| Data source | `/me/top/tracks?time_range=short_term` | Spotify's rolling 4-week ranking. Stable, no noise from one-off plays, podcasts, or skips |
| Count | 10 tracks | User request; requires the CSS change in §8 |
| Refresh cadence | Weekly, Mon 14:17 UTC | A 4-week ranking barely moves daily. Off-the-hour because GitHub delays top-of-hour scheduled runs under load |
| OAuth flow | Authorization Code **with client secret** | Not PKCE. PKCE targets clients that can't hold a secret and tends to rotate the refresh token, which would invalidate the stored GitHub secret |
| Failure behavior | Keep last data, fail the run loudly | Site never breaks; a silent failure could freeze the block for months unnoticed |
| Architecture | Committed data file + weekly Action | Preserves clone-and-build with zero secrets |
| Player embed | Rejected | See §10 |

## 4. Components

Five pieces. The three that do real work never learn about each other.

| File | Runs | Knows about |
|---|---|---|
| `scripts/spotify_auth.py` | Once by hand, ~2×/year | OAuth only. **Standalone** — stdlib, no `src/` imports, runnable on any machine |
| `scripts/fetch_listening.py` | Weekly, in Actions | Spotify API + JSON. **Never sees HTML** |
| `scripts/check_token_age.py` | Weekly, in Actions | Date arithmetic only. **No network** |
| `src/Gen_Content/render_listening.py` | Every build | JSON + HTML. **Never sees Spotify or the network** |
| `.github/workflows/listening.yml` | Weekly cron | Orchestration only |

`render_listening.py` gets its own module rather than living inside
`generate_landing_page.py`, which is already 135 lines doing directory scanning,
title extraction, link building, and template substitution. `generate_landing_page`
gains two `.replace()` calls in the chain it already has.

### The seam

`content/listening.json` is the entire contract between "talks to Spotify" and
"makes HTML." Each side is testable with no network and no mocks.

## 5. Data contract

`content/listening.json` — committed to git, deliberately minimal:

```json
{
  "fetched_at": "2026-08-09T14:17:03Z",
  "tracks": [
    { "artist": "Tech N9ne", "title": "Speedom" },
    { "artist": "Cannibal Corpse", "title": "Hammer Smashed Face" }
  ]
}
```

Only what renders. No track IDs, album art, popularity scores, or Spotify URLs —
the markup is text-only and this file lives in a public repo.

(Example truncated — the real file carries 10 entries.)

**Why it is committed:** local `./build.sh` keeps working with zero secrets, and a
fresh clone still builds a page with real tracks. This preserves the
clone-and-build property the migration notes are built around. Any design where the
build itself calls Spotify destroys it.

### Change detection

`fetched_at` changes on **every** run, so a naive file-level diff would report a
change every week — committing 52 times a year, defeating the no-op property and
rendering the §11 keep-alive meaningless.

**The rule: only the `tracks` array decides whether to commit.**

- `tracks` differ from the committed version → write the new file, including a
  fresh `fetched_at`, and commit.
- `tracks` identical → **discard** the newly written file (restore the committed
  one) and commit nothing. `fetched_at` deliberately goes stale.
- `tracks` identical **but** the newest commit is older than ~45 days → write
  `fetched_at` anyway and commit, purely as the §11 keep-alive.

This makes `fetched_at` mean "when the tracks last changed," not "when the job last
ran" — which is also the more useful of the two readings.

## 6. Credentials

**Repository secrets** (already entered for the first two):

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REFRESH_TOKEN` — added after the one-time auth

**Repository variable** (not a secret — an auth date isn't sensitive, and having it
readable in the UI means the countdown is visible at a glance):

- `SPOTIFY_AUTH_DATE` — ISO date, e.g. `2026-08-09`

**Scopes**, requested at authorization time:

- `user-top-read` — used now
- `user-read-currently-playing` — unused until the backend exists
- `user-read-recently-played` — insurance

Scopes are frozen into the refresh token, and re-authorizing is a manual chore, so
requesting the future ones now avoids a wasted re-auth cycle. All three are
read-only. `user-read-playback-state` is deliberately excluded — it drags in device
information that nothing here needs.

**Redirect URI:** `http://127.0.0.1:7777/callback`, registered in the dashboard.
Port 7777 rather than 8888 because `scripts/main.sh` already serves the preview on
8888. Spotify permits multiple redirect URIs, so both may be registered.
`localhost` is **not** permitted — Spotify requires the explicit loopback IP as of
April 2025. Loopback is the sole exception to Spotify's HTTPS-only rule, which is
safe because that hop never leaves the machine.

## 7. Flow

### One-time (~2×/year)

```
spotify_auth.py → browser → consent → code → refresh token
  → paste into secret SPOTIFY_REFRESH_TOKEN
  → set variable  SPOTIFY_AUTH_DATE to today
```

The script binds `127.0.0.1:7777`, always **prints** the auth URL, and
*additionally* attempts `webbrowser.open()`. This single code path covers both
deployment scenarios with no OS detection and no fallback branch:

- **On the Windows box** — browser and script co-located, opens automatically.
- **On the headless server** — run under `ssh -L 7777:localhost:7777`. The tunnel
  makes the local browser's `127.0.0.1:7777` reach the server's listener; the
  socket is indistinguishable to the script. `webbrowser.open()` silently no-ops,
  and the printed URL is used instead.

Client ID and secret are read from env vars or an interactive prompt — **never**
from a file, so nothing secret lands on disk or in shell history.

Federated login (Spotify via Facebook) is irrelevant to all of this. OAuth
separates authentication from authorization: Spotify handles proving identity
however it likes, and the script only ever exchanges the resulting code. It never
sees Facebook or any credential.

### Weekly (GitHub Actions)

```
1. check_token_age.py        pure date math, no network
     > 30 days   → silent, continue
     30 → 1 days → gh issue create (skip if one already open)
     ≤ 0 days    → gh issue create + exit 1, stop
2. fetch_listening.py        refresh token → access token → top tracks
     → validate shape → write content/listening.json
     → any failure → exit non-zero, stop
3. ./build.sh                renders JSON into docs/
4. commit only if `tracks` changed   content/listening.json + docs/
     (see §5 "Change detection" — `fetched_at` alone never triggers a commit)
     (+ keep-alive touch if repo quiet ~45 days — see §11)
```

Step 2 halts the job **before** step 3. Nothing is committed on a bad fetch, so the
last good tracks stay live. The graceful degradation is a property of the ordering,
not special-case code.

Required workflow permissions:

```yaml
permissions:
  contents: write   # commit listening.json + docs/
  issues:   write   # open the expiry reminder
```

`gh` is preinstalled on runners, so no third-party action is pulled into a repo
whose defining property is having zero dependencies.

## 8. Rendering

`titlepage.html` becomes:

```html
<ul class="now-list now-tracks">
{{ ListeningTracks }}
</ul>
<p class="now-stamp">{{ ListeningStamp }}</p>
```

### Two render states

| `listening.json` | Renders | Stamp |
|---|---|---|
| Present, valid | The tracks | `on repeat this month` |
| **Missing** | `Nothing logged yet` | `not yet live` |
| **Malformed** | `Nothing logged yet` + build warning | `not yet live` |

Missing is a legitimate state — a fresh clone that has never fetched — so it
degrades silently, matching the existing `Reading` block's `Nothing logged yet`
convention. Malformed indicates a bug, so it degrades **and** prints a warning in
the existing `print(f"Warning: ...")` style used at
`generate_landing_page.py:72`.

**The build never fails because of Listening data.** A clone must always build.

### Escaping

All artist and track names pass through `html.escape()`. This is not paranoia about
Spotify serving a `<script>` tag — band names contain `&` and `<`, and
"Simon & Garfunkel" written raw produces invalid HTML that renders wrong.

### CSS change

`.now` is `position:sticky; top:2rem`. At ~47px per two-line entry, 10 tracks push
the card to roughly 811px, needing ~843px of viewport. A laptop after browser chrome
has ~650–750px. **A sticky element taller than the viewport has its bottom cut off
with no way to scroll to it**, which would make `Building` and `Reading` partially
unreachable.

Fix, in `static/landing.css` on `body.landing .now`:

```css
max-height: calc(100vh - 4rem);
overflow-y: auto;
```

**Preserve** the existing two-line layout (`.now-tracks li span{display:block}` puts
artist above track) and the text-only decision. The CSS comment records the reason,
which is a real constraint rather than an aesthetic one:

```
/* artist name sits above the track — deliberately text only, no
   album art (some of it is genuinely not safe for a work laptop) */
```

## 9. Error handling

| Condition | Behavior |
|---|---|
| 401/400 on refresh | Token dead. Clear message, non-zero exit. The reminder issue fired a month earlier |
| Zero tracks returned | **Treated as failure, not written.** Never overwrite good data with worse data — an empty response must never blank the page |
| New refresh token in response | Run still succeeds, but prints loudly with instructions. A workflow cannot rewrite its own secret, and silently discarding a rotated token would make next week fail for reasons that look unrelated |
| Malformed response | Validate shape **before** writing, so partial failure cannot leave a truncated file |
| Network error / timeout / 429 | Fail. Retrying a weekly job isn't worth the complexity |

### Refresh token expiry

**Refresh tokens live 6 months.** The clock starts at authorization and **cannot be
extended by refreshing.** This is the one failure the design cannot self-heal, so it
gets two independent notification channels:

1. **Proactive** — `check_token_age.py` opens a GitHub issue labeled
   `spotify-token` at the 30-day mark. Creating an issue notifies the repo owner
   through existing notification settings, reaching the account email with no SMTP
   credentials, no app password, and no third-party action. It also leaves a
   persistent, closeable to-do rather than an email that gets buried.
2. **Reactive** — the workflow-failure email GitHub already sends for scheduled
   runs, covering expiry, revocation, and outages alike.

## 10. Rejected alternatives

| Rejected | Why |
|---|---|
| **Spotify embed / mini player** | Would delete the whole pipeline, but: adds a few hundred KB of third-party JS to a site that self-hosts fonts and recompressed a headshot from 4.4 MB → 57 KB; Spotify-green widget clashes with the hearth/fire theme and self-hosted type; and a hand-curated playlist stops being *live*. The `Elsewhere` section already links the public Spotify profile, which covers "go listen to my stuff" |
| **Fetch inside `build.sh`** | Every build would need secrets. Laptop builds would fail or silently blank the block, and a fresh clone couldn't build at all |
| **Client-side fetch in `fire.js`** | Requires a token in the browser on a public repo |
| **Patching `docs/index.html` directly** | Violates the one rule the migration notes shout about. `src/main.py:49` rmtree's `docs/`, so the next local build silently wipes it |
| **Top artists instead of tracks** | Loses the track column and the existing two-line markup |
| **Recently-played instead of top tracks** | Includes every skip, podcast, and song someone else played |

## 11. Known risk: scheduled-workflow auto-disable

**Public repos disable scheduled workflows after 60 days with no repository
activity.** This repo is public — that is what keeps Pages free — and the job only
commits when data changes. A long quiet stretch could therefore **silently disable
the workflow, taking the reminder with it**: the one job whose purpose is to warn
would be the thing that went quiet.

**Mitigation:** if the most recent commit is older than ~45 days, the job writes the
`fetched_at` timestamp purely to reset the inactivity clock. Normal weeks stay
no-op and git history stays clean; this costs at most a couple of commits a year.

## 12. Testing

Per the project's testing posture: adversarial tests, property tests, and 100%
mutation score on the units under test. The seam in §4 exists partly to make this
possible — three genuinely pure functions, no clock mocking, no network.

| Unit | Signature | Adversarial cases |
|---|---|---|
| `days_until_expiry` | `(auth_date, today) → int` | Day 30 vs 31 vs 0 vs −1; malformed and non-ISO strings; future auth date; leap-year spans. **Property:** strictly decreasing as `today` advances |
| `parse_top_tracks` | `(api_json) → list[dict]` | Missing `items`; empty `artists[]`; null names; non-string types; 0 tracks; 50 tracks |
| `render_listening` | `(data) → (html, stamp)` | Names with `&` `<` `>` `"`; unicode and emoji; empty list; missing keys; very long titles. **Property:** no input can produce unescaped `<` in output |

`today` is a **parameter**, not `datetime.now()`. Tests assert return values, never
mock calls or private state. The network layer (`_refresh_access_token`,
`_get_top_tracks`) stays deliberately thin so the untested surface is small, and is
verified once manually against the real API.

### Harness repair (prerequisite)

The runner is broken in two independent ways, confirmed on this host:

- `test.sh` calls `python`; this box only has `python3` → `exit 127`.
- `unittest discover -s src` finds **zero** tests because `src/tests/` is not an
  importable package (`ImportError: Start directory is not importable`).

**Measured baseline**, via `PYTHONPATH=src python3 -m unittest discover -s src/tests -t src/tests`:

```
Ran 39 tests — 19 pass, 11 failures, 9 errors
```

This spec will:

1. Fix `test.sh` (use `python3` with the same interpreter detection as `build.sh`;
   correct discovery).
2. Take the three new modules to 100% coverage and mutation.
3. Record the 39/19/11/9 baseline so "no new failures" is checkable.

It will **not** repair the 9 stale test files. Their `textnode` vs `src.textnode`
import disagreement is pre-existing, unrelated to Spotify, and already flagged in
the migration notes as a separate cleanup.

## 13. Deferred to the backend spec

Currently-playing is **structurally impossible** on a weekly static build. Baking it
in produces a page announcing what was playing at 14:17 UTC *last Monday* — not
stale but wrong, which is worse than showing nothing.

Making it genuinely live requires one of:

- Building every few minutes — Pages rate-limits deploys and this would generate
  hundreds of commits a day. Non-starter.
- Client-side fetching — needs a token in the browser on a public repo.
- **A small backend holding the token, serving `/now-playing` to the browser.**

The third is exactly the infrastructure the guestbook already forces. Once it
exists, live now-playing is nearly free: the backend has credentials and the browser
polls it. The `user-read-currently-playing` scope is requested now (§6) precisely so
that work needs no re-authorization.
