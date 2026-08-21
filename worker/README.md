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

```bash
npx wrangler dev
```
