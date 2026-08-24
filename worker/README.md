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
| `src/data/` | Wordlists. `blocked.txt` is SHA-256 digests only. |

The four pure modules import stdlib only and are tested by the repo's
normal `./test.sh` — no wrangler, no network, no Cloudflare account.

## First-time setup

These are one-time, run by hand by the repo owner. They require an
interactive Cloudflare login and are **not** run by any agent or CI job.

```bash
npx wrangler login
```

```bash
cd worker
npx wrangler d1 create guestbook
```

Copy the printed `database_id` from the output above. Paste it over the
`PASTE_THE_ID_FROM_TASK_3` placeholder that Task 8 adds to the
`[[d1_databases]]` block in `wrangler.toml`.

```bash
npx wrangler d1 execute guestbook --local  --file=./schema.sql
npx wrangler d1 execute guestbook --remote --file=./schema.sql
```

### Verify the schema applied

```bash
npx wrangler d1 execute guestbook --local \
  --command="SELECT name FROM sqlite_master WHERE type='table';"
```

Expected: a row for `entries`.

```bash
npx wrangler d1 execute guestbook --local \
  --command="INSERT INTO entries (name, message, created_at, ip_hash) VALUES ('t','t','2026-08-20T00:00:00Z','x'); SELECT hidden, block_reason FROM entries;"
```

Expected: `hidden = 0`, `block_reason = NULL` — confirms the defaults.
Then clean up:

```bash
npx wrangler d1 execute guestbook --local --command="DELETE FROM entries;"
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

Requires Node 22+; wrangler refuses to start on 20.

```bash
npx wrangler dev
```

## Runtime constraints

Three things about this Worker are not free choices. Changing any of
them breaks it in a way local unit tests cannot see, because the pure
modules never touch the runtime.

**`src/data/`, not `data/`.** Wrangler bundles files relative to the
module root, which is the directory holding `main` — `src/`. Wordlists
outside it are silently absent at runtime, and the loaders treat an
unreadable file as an empty list. The failure mode is not a crash: it is
a Worker that accepts everything, with the profanity swap and the entire
denylist inert. The `[[rules]]` block with `type = "Text"` is what pulls
the `.txt` files into the bundle; without it they are dropped even from
`src/`.

**`disable_python_external_sdk`.** Without it the runtime looks for the
`workers` package from `workers-py`, which must be vendored by
`pywrangler sync`. That resolution fails here: `workers-py` depends on
`pyjson5`, which publishes no Pyodide/emscripten wheel, and building it
from source needs an emsdk toolchain. The flag selects the runtime's
built-in SDK instead, which supplies the same `Response` import.

**`disable_python_no_global_handlers`.** At this `compatibility_date`
the runtime no longer discovers module-level handlers, so `on_fetch`
is invisible and every request 500s with "we lack a handler for
FetchEvents". The flag restores discovery. The alternative is porting
`entry.py` to a `WorkerEntrypoint` subclass, which is the forward path
once `workers-py` can actually be installed.

**D1 rows are JS objects.** They arrive as `pyodide.ffi.JsProxy`, which
is not subscriptable — `row["n"]` raises `TypeError`. `_to_py()` in
`entry.py` converts them. Relatedly, Python `None` crosses into JS as
`undefined`, which D1 rejects with `D1_TYPE_ERROR`; write SQL `NULL` as
a literal rather than binding `None`.

## Deploy

Node 22+ and `CLOUDFLARE_API_TOKEN` in the environment. The token needs
Workers Scripts:Edit, D1:Edit, Account Settings:Read on the account, and
Workers Routes:Edit + Zone:Read on `bretzanotelli.work`.

```bash
cd worker && npx wrangler deploy
```

The `api` hostname is an `AAAA` record pointing at `100::`, **proxied**
(orange cloud). The Worker route intercepts before it resolves; the
address is a discard prefix and is never actually reached. Adding that
record needs DNS:Edit, which the deploy token deliberately lacks — do it
in the dashboard.

## Moderation

```bash
export GUESTBOOK_ADMIN_TOKEN=...
python3 ../scripts/guestbook_admin.py --review   # filter-blocked entries
python3 ../scripts/guestbook_admin.py --hide 41
```

`--review` is the filter's feedback loop. If it shows a real person was
caught, add the word to `src/data/allow.txt` and redeploy. Never weaken
the matcher to fix one false positive.

## Credentials for the CLI

`scripts/guestbook_admin.py` reads, in order: the environment, then
`~/.config/guestbook/credentials`. The file exists so moderating does
not require pasting a secret every session -- the paste is the step
that gets skipped, and a moderation tool that is annoying to run does
not get run.

```bash
mkdir -p ~/.config/guestbook
install -m 600 /dev/null ~/.config/guestbook/credentials
cat >> ~/.config/guestbook/credentials <<'EOF'
GUESTBOOK_ADMIN_TOKEN=...
CF_ACCESS_CLIENT_ID=...
CF_ACCESS_CLIENT_SECRET=...
EOF
```

The file is refused outright if anyone but its owner can read it. A
silently-honoured world-readable secret would defeat the point of
moving it off the command line. The two Access values are optional and
are only sent when both are present: half a service token reads to
Access as a failed authentication rather than an unauthenticated call.

## Cloudflare Access on /admin

Optional, and stronger than the bearer token alone: unauthenticated
requests are turned away at Cloudflare's edge, revocation is a dashboard
click rather than a redeploy, and every admin access is logged. The
bearer check in `entry.py` stays regardless -- it is the gate that does
not depend on a dashboard setting being correct.

Dashboard only; the deploy token deliberately has no Access permissions.

1. **Zero Trust -> Settings**, pick a team name. Access must be enabled
   on the account before its API answers at all.
2. **Access -> Applications -> Add -> Self-hosted.**
   Domain `api.bretzanotelli.work`, path `admin`. Session duration to
   taste.
3. **Two policies:**
   - `me` -- action *Allow*, include *Emails* -> your address. One-time
     PIN needs no identity provider.
   - `cli` -- action *Service Auth*, include *Service Token* -> the one
     created below. Service Auth, not Allow: an Allow policy expects a
     human session.
4. **Access -> Service Auth -> Create Service Token**, named for the
   CLI. The secret is shown once. Put both halves in the credentials
   file above.

**Verify which layer answers first, because it decides what this buys
you.** Workers and Access both run at the edge, and which one sees a
request first depends on how the route is bound:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.bretzanotelli.work/admin/entries
```

- `302` or an Access login page: Access is in front. Unauthenticated
  traffic never reaches the Worker or D1, which is the whole point.
- `401` with `{"ok":false,"code":"unauthorized"}`: the Worker ran first
  and Access is not protecting this path. The bearer token is still the
  real gate. To get edge enforcement in that case, the Worker must
  validate the `Cf-Access-Jwt-Assertion` header itself against the
  team's public keys.

Then confirm the CLI still works:

```bash
python3 ../scripts/guestbook_admin.py --review
```

## Updating the denylist

The plaintext term list is NEVER committed. Keep it outside the repo:

```bash
python3 ../scripts/hash_terms.py ~/gb-terms.txt src/data/blocked.txt
npx wrangler deploy
```

## Known limits

- Python Workers are in open beta. The logic worth protecting lives in the
  four pure modules and is portable to any runtime.
- "Punching down" is not encodable. The filter enforces the slur rule; the
  owner enforces the rest with `--hide`.
- Coded and tertiary terms evolve faster than a static list. `--review` is
  the backstop.
- Two `disable_*` compatibility flags are load-bearing. See "Runtime
  constraints" above before changing `compatibility_date`.
