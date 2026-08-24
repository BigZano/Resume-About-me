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

from matching import load_allow, load_blocked
from policy import check_message, check_name
from swaps import apply_swaps, load_swaps
from workers import Response

_DATA = Path(__file__).resolve().parent / "data"

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


def _to_py(value):
    """Convert a D1 result across the JS boundary.

    D1 hands back JS objects, which arrive as `pyodide.ffi.JsProxy`.
    A JsProxy is not subscriptable, so `row["n"]` raises TypeError and
    the request 500s. Marshalling, not policy — nothing here decides
    anything about content.
    """
    return value.to_py() if hasattr(value, "to_py") else value


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
        row = _to_py(row)
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
    return _to_py(result).get("results") or []


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
        # POST only. A GET that mutates is reachable by anything that can
        # make the browser issue one -- an image tag, a prefetch, a link
        # in a page. The bearer token is not sent by those, so this is
        # defence in depth rather than a live hole, but a moderation
        # endpoint should never be a URL you can merely visit.
        if action in ("hide", "unhide") and request.method == "POST":
            # NULL is written as a SQL literal, not a binding. Python None
            # crosses into JS as `undefined`, and D1 rejects that with
            # D1_TYPE_ERROR rather than storing NULL -- which made unhide
            # 500 and leave the entry hidden.
            sql = (
                "UPDATE entries SET hidden = 1, block_reason = 'manual' "
                "WHERE id = ?"
                if action == "hide"
                else "UPDATE entries SET hidden = 0, block_reason = NULL "
                "WHERE id = ?"
            )
            await env.DB.prepare(sql).bind(entry_id).run()
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
