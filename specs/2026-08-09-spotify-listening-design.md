# Spotify "Listening" Pipeline — Design

**Date:** 2026-08-09
**Revised:** 2026-11-25 — top-tracks replaced by a true weekly chart built from a
rolling play log (§§3, 5, 7, 9, 10, 12), and a Steam `Playing` fetcher added
(§14). The 2026-08-09 reasoning is kept where it still holds; where it was
overturned, the section says so.
**Status:** Approved, ready for implementation planning
**Scope:** The `Listening` block on the landing page, plus the `Playing` data
file in §14.

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
| Data source | `/me/player/recently-played?limit=50`, folded into a rolling 7-day play log | *(Revised.)* The owner wants a true "this week" chart with play counts, which `/me/top/tracks` cannot give (its shortest window is ~4 weeks and it carries no counts). The cost is that recently-played only ever returns the last 50 plays — see §5.1 |
| Count | 10 tracks | User request; requires the CSS change in §8 |
| Refresh cadence | Poll every 4 hours (`17 1,5,9,13,17,21 * * *`); publish about once a day | *(Revised.)* Polling often enough that 50 plays never scroll past between polls is what makes a weekly chart possible. Publishing is gated on the age of the last `listening.json` commit (§7), so the site and git history still move about once a day. Off-the-hour because GitHub delays top-of-hour scheduled runs under load |
| OAuth flow | Authorization Code **with client secret** | Not PKCE. PKCE targets clients that can't hold a secret and tends to rotate the refresh token, which would invalidate the stored GitHub secret |
| Failure behavior | Keep last data, fail the run loudly | Site never breaks; a silent failure could freeze the block for months unnoticed |
| Architecture | Committed data file + scheduled Action | Preserves clone-and-build with zero secrets |
| Player embed | Rejected | See §10 |

## 4. Components

Seven pieces (the Steam fetcher and its renderer arrived 2026-11-25, §14). The ones that do real work never learn about each other.

| File | Runs | Knows about |
|---|---|---|
| `scripts/spotify_auth.py` | Once by hand, ~2×/year | OAuth only. **Standalone** — stdlib, no `src/` imports, runnable on any machine |
| `scripts/fetch_listening.py` | Every poll (~4h), in Actions | Spotify API + the play log + JSON. **Never sees HTML** |
| `scripts/fetch_playing.py` | Publish runs, in Actions | Steam API + JSON. **Never sees HTML** (§14) |
| `scripts/check_token_age.py` | Every poll, in Actions | Date arithmetic only. **No network** |
| `src/Gen_Content/render_listening.py` | Every build | JSON + HTML. **Never sees Spotify or the network** |
| `src/Gen_Content/render_playing.py` | Every build | JSON + HTML for the Playing block. **Never sees Steam or the network** |
| `.github/workflows/listening.yml` | 4-hourly cron | Orchestration only |

`render_listening.py` gets its own module rather than living inside
`generate_landing_page.py`, which is already 135 lines doing directory scanning,
title extraction, link building, and template substitution. `generate_landing_page`
gains two `.replace()` calls in the chain it already has.

*Revised 2026-11-25:* the landing generator has since grown the homepage sitemap
(per-page blurbs and build-time stamps) and the Playing wiring, and is ~300 lines.
Splitting the sitemap gatherer into its own module is the obvious next cut.

### The seam

`content/listening.json` is the entire contract between "talks to Spotify" and
"makes HTML." Each side is testable with no network and no mocks.

The play log (§5.1) is a second file, but it is *private to the fetcher*: the
renderer never reads it, and it is never committed.

## 5. Data contract

`content/listening.json` — committed to git, deliberately minimal:

```json
{
  "fetched_at": "2026-11-25T01:17:03Z",
  "tracks": [
    { "artist": "Trivium", "title": "The Terror", "plays": 12 },
    { "artist": "Cannibal Corpse", "title": "Hammer Smashed Face", "plays": 9 }
  ]
}
```

Only what renders. Each track is `artist`, `title`, and `plays` — the number of
times it was played in the last 7 days. **No timestamps**, track IDs, album art,
popularity scores, or Spotify URLs: the markup is text-only and this file lives
in a public repo. `plays` is a positive integer; tracks are ordered most-played
first (ties: most recently played, then artist, then title, so the order is
deterministic and never flaps).

(Example truncated — the real file carries up to 10 entries.)

*Revised 2026-11-25:* `plays` is new. A committed file from before the change has
tracks without it; the renderer must treat a missing `plays` as "unknown", not as
an error, and the first publish after the switch rewrites the file because the
tracks no longer compare equal.

### 5.1 The play log

`/me/player/recently-played` returns at most the **last 50 plays**, so a single
weekly fetch would see a few hours of listening. Instead every run polls and
merges the response into a rolling 7-day **play log**:

```json
{ "since": "2026-11-25T13:17:03.412Z",
  "plays": [ { "artist": "Trivium", "title": "The Terror",
               "played_at": "2026-11-25T13:22:11.995Z" } ] }
```

*Added 2026-11-25:* `since` is when this log started: the time of the poll that
created it. See "Warm-up" below.

- **Never committed.** It holds listening timestamps and the repo is public. It
  lives at `.cache/spotify-plays.json` (gitignored; a test asserts this) and is
  carried between runs by the GitHub Actions cache.
- **Merging** de-duplicates on `(played_at, artist, title)`, so overlapping polls
  never double-count, and drops anything older than 7 days relative to `now`. An
  entry exactly 7 days old is kept; one second older is dropped. Timestamps are
  normalised to UTC with millisecond precision so equal instants always compare
  equal. The file is written oldest-first so its content is stable.
- **Missing or corrupt** log (first run, or the cache was evicted — caches unused
  for 7 days are): start fresh from what the current poll returned and carry on.
  A corrupt file also prints a warning. The next publish then reports a thinner
  chart than the true week, which is the correct failure — see §9.
  *Revised 2026-11-25:* it no longer publishes that thin chart straight away
  when there is a committed one to keep; see "Warm-up" below.
- The log is written *before* aggregating, so a failed publish cannot also lose
  that poll.

**Warm-up** (*Added 2026-11-25*). Spotify offers no deeper history through the
API: `recently-played` is capped at the last 50 plays and there is no endpoint
for anything older. A log that has only just started, on the first ever run or
after the cache is evicted, therefore cannot know what was played before its
first poll, and no amount of polling afterwards can backfill it. Publishing it
as-is would replace a good 10-track chart with a thin one (a simulated first run
produced 4 tracks). Since the history cannot be fetched, the design waits for it
to accumulate instead: **the first 7 days of a log's life keep the committed
chart.**

- **`since`** is written into the log whenever it starts fresh (new, missing or
  corrupt file) as an ISO-8601 UTC timestamp, and is **preserved unchanged on
  every later merge**. A log with no `since` (written before this existed) is
  treated as starting now. A `since` that is unusable (not a timestamp, no zone)
  or lies in the future is also treated as now, with a warning, so a bad value
  cannot stretch the warm-up past a week. Plays from before `since` are kept and
  counted as normal while they are inside the 7-day window; `since` records when
  observation began, not the age of the oldest play.
- **The rule**, applied on publish runs by `plan_publish` (pure, so it is tested
  without I/O): if the committed `content/listening.json` holds at least one
  usable track (an entry with a text `artist` and a text `title`) **and**
  `now - since < 7 days` (the same `WINDOW_DAYS` as the log), no new chart is
  written. The run prints `Warming up: play log covers 2d 4h of 7d; keeping the
  committed chart.` and exits 0.
- **Boundary:** 7 days minus one second still keeps the committed chart; exactly
  7 days publishes normally.
- **`--keep-alive`** during warm-up re-stamps the committed chart without
  changing its tracks, exactly as the empty-window path does, so the 60-day
  inactivity clock (§11) still resets.
- **No usable committed chart** (fresh clone, missing file, malformed file, empty
  `tracks`): there is nothing to protect, so the log publishes whatever it has,
  and still never zero tracks.
- A cache eviction or a corrupt log mid-week restarts the warm-up from that poll.
- Poll-only runs never write `listening.json`, so they are unaffected. During
  warm-up every publish run reports the notice and commits nothing.

**Why it is committed:** local `./build.sh` keeps working with zero secrets, and a
fresh clone still builds a page with real tracks. This preserves the
clone-and-build property the migration notes are built around. Any design where the
build itself calls Spotify destroys it.

### Change detection

`fetched_at` changes on **every** run, so a naive file-level diff would report a
change every run — defeating the no-op property and rendering the §11 keep-alive
meaningless.

**The rule: only the `tracks` array decides whether to commit.** (It now includes
`plays`, so a changed count is a changed chart. That is intended — the chart
commits roughly daily while Bret is listening, and not at all while he is not.)

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
- `STEAM_API_KEY`, `STEAM_ID` — for §14. Not yet created; the Steam step is a
  no-op until they are

**Repository variable** (not a secret — an auth date isn't sensitive, and having it
readable in the UI means the countdown is visible at a glance):

- `SPOTIFY_AUTH_DATE` — ISO date, e.g. `2026-08-09`

**Scopes**, requested at authorization time:

- `user-top-read` — no longer used since the 2026-11 revision; harmless to keep
- `user-read-currently-playing` — unused until the backend exists
- `user-read-recently-played` — **used now**; the source of the weekly chart.
  (Requested up front as "insurance", which is why the revision needed no
  re-authorization.)

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

### Every 4 hours (GitHub Actions)

```
1. check_token_age.py        pure date math, no network
     > 30 days   → silent, continue
     30 → 1 days → gh issue create (skip if one already open)
     ≤ 0 days    → gh issue create + exit 1, stop
2. restore the play log      actions/cache/restore, newest `spotify-plays-*`
3. publish gate              `workflow_dispatch`, OR the last commit touching
                             content/listening.json is ≥ 20 hours old
                             (or there never was one) → this run PUBLISHES;
                             otherwise it only POLLS
4. fetch_listening.py        refresh token → access token → recently-played
     → validate shape → merge into the play log → save the log
     → [publish only] aggregate → write content/listening.json if tracks changed
     → any failure → exit non-zero, stop
5. save the play log         actions/cache/save, key `spotify-plays-<run>-<attempt>`
6. [publish only]
     fetch_playing.py        Steam → content/playing.json (§14)
     ./build.sh              renders JSON into docs/
     commit only if `tracks` changed   content/listening.json,
       content/playing.json, docs/
     (see §5 "Change detection" — `fetched_at` alone never triggers a commit)
     (+ keep-alive touch if repo quiet ~45 days — see §11)
```

The gate uses **commit age, not the clock hour**, because GitHub delays scheduled
runs by minutes to hours: "publish at 01:xx" would sometimes never fire. A 20-hour
threshold on a 4-hourly poll publishes about once a day and tolerates ~4 hours of
delay. If a publish finds nothing new, the commit age does not reset, so every
later run retries — cheap, since an unchanged chart means no commit and no deploy.

A **poll-only** run updates the cache and touches nothing under `content/`.
`fetch_listening.py` encodes that: without `--publish` it never writes
`listening.json`, and `--keep-alive` without `--publish` is a usage error.

```
python3 scripts/fetch_listening.py                      # poll only
python3 scripts/fetch_listening.py --publish            # poll, then publish
python3 scripts/fetch_listening.py --publish --keep-alive
```

Caches are immutable, so each run saves under a fresh key and restores the
newest by prefix. Caches created by a run on a non-default branch are invisible to
`main`, so a manual dispatch from a feature branch cannot disturb the real log.

Step 4 halts the job **before** the build. Nothing is committed on a bad fetch, so
the last good tracks stay live. The graceful degradation is a property of the
ordering, not special-case code.

Required workflow permissions:

```yaml
permissions:
  contents: write   # commit listening.json + playing.json + docs/
  issues:   write   # open the expiry reminder
```

`gh` is preinstalled on runners, so no third-party action is pulled into a repo
whose defining property is having zero dependencies.

## 8. Rendering

`titlepage.html` becomes:

```html
<ol class="now-list now-tracks">
{{ ListeningTracks }}
</ol>
<p class="now-stamp">{{ ListeningStamp }}</p>
```

*Revised 2026-11-25:* an `<ol>`, since it's a ranked chart. Each row is
`<span class="artist">` `<span class="title">` `<span class="plays">×N</span>`;
when a track's artist matches the previous row's, the row gets `class="same-artist"`
and CSS hides the repeated artist visually (screen readers still hear it), so a week
of one band reads as one band with its tracks beneath it.

### Two render states

| `listening.json` | Renders | Stamp |
|---|---|---|
| Present, valid | The tracks | `top N this week · updated Mon D` (from `fetched_at`) |
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

*Superseded 2026-11-25:* the Now panel is no longer sticky, so the fix below is gone.
The nested scrollbar it created was its own problem, and grouping the chart by artist
made the card short enough to sit in the column. Kept for the reasoning:

`.now` was `position:sticky; top:2rem`. At ~47px per two-line entry, 10 tracks push
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
| Recently-played payload structurally broken (not an object; `items` missing or not a list) or **non-empty `items` in which no entry is usable** | Non-zero exit. The play log is not touched. The second case smells like Spotify changed the shape, and reading it as "no plays" would hide that |
| Recently-played `items` is an **empty list** | **Not a fault.** Means "no new plays": the poll succeeds and the log is unchanged (apart from the usual 7-day pruning). *(Revised 2026-11-25: this used to raise.)* A quiet stretch is a legitimate state, and a red run every 4 hours trains the owner to ignore real failures |
| No plays inside the 7-day window at publish time | **Zero tracks are never written.** The committed chart stays and the run exits 0 with a notice: a quiet week is not a pipeline fault, and failing every 4 hours for a week would be noise. (With `--keep-alive` the committed chart is re-stamped so the §11 clock still resets) |
| Play log missing or corrupt | Start fresh from the current poll, stamping a new `since`, and publish what exists, never fewer than one track. Corrupt prints a warning. *(Revised 2026-11-25: if a usable committed chart exists, the next 7 days are a warm-up and keep it; see the next row.)* |
| Play log younger than 7 days *(Added 2026-11-25)* | **Warm-up.** The first run, an evicted cache and a corrupt log all produce a log that holds at most the last 50 plays, and Spotify offers no way to look further back, so warm-up stands in for a backfill. A usable committed chart is kept, not overwritten with a thin one: the run exits 0 with `Warming up: play log covers 2d 4h of 7d; keeping the committed chart.` (With `--keep-alive` the committed chart is re-stamped.) Exactly 7 days old publishes normally |
| Play log younger than 7 days and **no usable committed chart** *(Added 2026-11-25)* | Nothing to protect, so publish whatever the log yields (never zero tracks). A missing, unparseable, wrongly shaped or empty `listening.json` all count as no chart |
| Play log has no `since`, or an unusable or future one *(Added 2026-11-25)* | Treated as starting now. No `since` is silent (a log written before this existed); an unusable or future one also prints a warning |
| New refresh token in response | Run still succeeds, but prints loudly with instructions. A workflow cannot rewrite its own secret, and silently discarding a rotated token would make next week fail for reasons that look unrelated |
| Malformed response | Validate shape **before** writing, so partial failure cannot leave a truncated file |
| Network error / timeout / 429 | Fail. The next poll is 4 hours away and re-reads the last 50 plays, so nothing is lost unless 50 plays happen in between |

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
| ~~**Recently-played instead of top tracks**~~ | *Overturned 2026-11-25.* The objection was that it includes every skip and podcast; the owner prefers a true weekly chart with real play counts. Podcast episodes are dropped at parse time (no `artists`). A skipped track still counts as a play, which is accepted |

## 11. Known risk: scheduled-workflow auto-disable

**Public repos disable scheduled workflows after 60 days with no repository
activity.** This repo is public — that is what keeps Pages free — and the job only
commits when data changes. A long quiet stretch could therefore **silently disable
the workflow, taking the reminder with it**: the one job whose purpose is to warn
would be the thing that went quiet.

**Mitigation:** if the most recent commit is older than ~45 days, a publish run
writes the `fetched_at` timestamp purely to reset the inactivity clock. Normal
weeks stay no-op and git history stays clean; this costs at most a couple of
commits a year. (Since the 2026-11 revision the chart commits about daily while
Bret is listening, so the keep-alive only matters across a long listening gap.)

## 12. Testing

Per the project's testing posture: adversarial tests, property tests, and 100%
mutation score on the units under test. The seam in §4 exists partly to make this
possible — three genuinely pure functions, no clock mocking, no network.

| Unit | Signature | Adversarial cases |
|---|---|---|
| `days_until_expiry` | `(auth_date, today) → int` | Day 30 vs 31 vs 0 vs −1; malformed and non-ISO strings; future auth date; leap-year spans. **Property:** strictly decreasing as `today` advances |
| `parse_recently_played` | `(api_json) → list[dict]` | Missing/non-list `items`; null `track`; empty `artists[]`; null names; non-string types; missing, naive, garbage or overflowing `played_at`; podcast items; **empty `items` → `[]`, but non-empty `items` with nothing usable → raises**; 50 plays; equivalent timestamp spellings normalise |
| `merge_play_log` | `(existing, fresh, now) → list[dict]` | Dedupe on `(played_at, artist, title)`; **exactly 7 days kept, 7 days + 1 s dropped**; naive `now`; garbage entries. **Properties:** idempotent, independent of input order, a later `now` only shrinks the log |
| `aggregate_weekly_top` | `(entries, now, limit) → list[dict]` | Counts; tiebreak on most recent play, then artist/title; window boundary; limit; stale plays cannot win ties. **Properties:** counts never increase down the chart, output independent of input order, output carries no timestamps |
| `load_play_log` / `save_play_log` | `(path, now) → (plays, since, warning)` / `(path, plays, since)` | Missing, empty, corrupt, binary, wrong-shape, absurdly nested files; round trip; atomic write. *Revised 2026-11-25:* `since` is missing, unusable, naive, in the future, or stored by a corrupt file → now; a good one is read back untouched |
| `update_play_log` | `(path, fresh, now) → (plays, since, previous_count, warning)` | *Added 2026-11-25.* `since` is stamped by the first poll and survives 42 polls, empty polls, plays aging out, and a naive `now` (rejected before anything is written) |
| `plan_publish` | `(tracks, existing, keep_alive, *, since, now) → (tracks \| None, msg)` | **Never returns an empty list to write**, for every combination of empty/unchanged/changed × keep-alive. *Revised 2026-11-25 (warm-up):* **7 days − 1 s keeps the committed chart, exactly 7 days publishes**; no, malformed or empty committed chart publishes; one usable track among junk keeps it; keep-alive re-stamps without changing tracks; `since` and `now` are keyword-only and naive datetimes are rejected |
| `parse_recent_games` | `(api_json) → list[dict]` | See §14 |
| `render_listening` | `(data) → (html, stamp)` | Names with `&` `<` `>` `"`; unicode and emoji; empty list; missing keys; very long titles. **Property:** no input can produce unescaped `<` in output |

`today` and `now` are **parameters**, not `datetime.now()`. Tests assert return
values, never mock calls or private state. The network layer
(`refresh_access_token`, `get_recently_played`, `get_recent_games`) stays
deliberately thin so the untested surface is small, and is verified once manually
against the real API. File-level behaviour (`publish_chart`, `fetch_playing.main`)
is tested against temporary directories, with the Steam fetch passed in as a plain
function rather than patched.

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

## 14. Steam "Playing" (added 2026-11-25)

A second, independent fetcher in the same shape: `scripts/fetch_playing.py` calls
`IPlayerService/GetRecentlyPlayedGames/v1` and writes `content/playing.json`. It
shares no code with the Spotify fetcher — the two never learn about each other —
and the seam is again a committed JSON file the renderer reads.

```json
{
  "fetched_at": "2026-11-25T01:17:09Z",
  "games": [
    { "name": "Hades", "hours_2weeks": 12.5 }
  ]
}
```

- Top **5** games by two-week playtime, longest first (ties: name). Steam reports
  `playtime_2weeks` in **minutes**; `hours_2weeks` is that over 60, rounded
  half-up to one decimal using integer arithmetic (so 9 minutes is always `0.2`,
  never `0.1` by accident of binary floats). A game whose hours round to `0.0`
  (under 3 minutes) is **dropped**: it would only show as "0.0 h". The first
  playtime that survives is 3 minutes (0.05 h rounds up to `0.1`). Dropped games
  never take a slot, so the five shown are the five longest that still show.
- No app IDs, icon hashes, lifetime playtime, or URLs.
- `games` **may be empty** (`"games": []`): the renderer must handle it, and should
  not treat it as an error.
- **Secrets:** `STEAM_API_KEY` and `STEAM_ID`. If **either** is unset the script
  prints a notice and exits 0 without touching anything, so the workflow works
  before the secrets exist. The key travels in the query string (that is how the
  API takes it) and is never printed; errors report status and body, not the URL.
- **Steam profile "Game details" must be public.** A private profile (or a wrong
  `STEAM_ID`) returns an empty `response` object `{}`, which is a `ValueError` →
  non-zero exit, nothing written.
- **A public profile with nothing played in two weeks is valid, not a fault.** Steam
  sends `total_count: 0` and/or `games: []` for it, and this writes
  `{"fetched_at": ..., "games": []}` and exits 0, under the same change rule as
  any other chart (an already-empty committed file is left alone). So does a
  profile whose every game rounds to `0.0` hours. *(Revised 2026-11-25: this used
  to raise.)* A red run every 4 hours over a quiet stretch would train the owner to
  ignore real failures.
- Still non-zero, nothing written: a `response` or payload that is not an object, a
  `games` that is missing (without `total_count: 0`) or not a list, `total_count`
  that is not the integer `0` while `games` is missing, and a **non-empty** `games`
  list in which no entry is usable (that smells like a shape change).
- Runs on **publish runs only**, after the Spotify step. `continue-on-error` keeps
  a Steam failure from blocking the Spotify chart; a final step then fails the run
  so the failure is still loud (GitHub's failure email) *after* the commit.
- Only writes when `games` changed; `fetched_at` goes stale otherwise, as in §5.
