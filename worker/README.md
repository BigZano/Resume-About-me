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
