#!/usr/bin/env python3
"""One-time Spotify authorization. Prints a refresh token.

Standalone on purpose: standard library only, no imports from src/, so it
can be copied to any machine and run without a repository checkout.

Two supported ways to run, both the same code path:

  * On a machine with a browser (e.g. the Windows box) — the browser opens
    automatically and the callback is caught locally.

  * On a headless host, under an SSH tunnel:
        ssh -L 7777:localhost:7777 you@host
        python3 scripts/spotify_auth.py
    The tunnel makes the local browser's 127.0.0.1:7777 reach this
    listener; the socket is indistinguishable. webbrowser.open() silently
    no-ops, so use the URL printed below.

Credentials are read from the environment or prompted for interactively.
They are never written to disk.

Afterwards:
  1. Paste the refresh token into the repository secret SPOTIFY_REFRESH_TOKEN
  2. Set the repository variable SPOTIFY_AUTH_DATE to today (YYYY-MM-DD)

The refresh token expires 6 months from today. That clock cannot be
extended by refreshing.
"""
import base64
import getpass
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PORT = 7777
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-top-read user-read-currently-playing user-read-recently-played"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

_result = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (params.get("code") or [None])[0]
        _result["state"] = (params.get("state") or [None])[0]
        _result["error"] = (params.get("error") or [None])[0]

        body = b"Authorization received. You can close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal clean


def _credential(name, prompt, secret=False):
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        value = getpass.getpass(prompt) if secret else input(prompt)
    except EOFError:
        return ""  # non-interactive stdin; caller reports it cleanly
    return value.strip()


def _serve_until_answered(server):
    """Handle requests until the callback lands.

    Browsers often request /favicon.ico first. A single handle_request()
    would be consumed by that and never see the real callback, so loop
    until the handler actually records a code or an error.
    """
    while not ("code" in _result or "error" in _result):
        server.handle_request()


def build_auth_url(client_id, state):
    """Assemble the Spotify authorize URL. Pure — used by tests."""
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    return f"{AUTH_URL}?{query}"


def exchange_code(client_id, client_secret, code):
    """Trade an authorization code for tokens. Returns the parsed payload."""
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"Token exchange failed ({exc.code}): {detail}\n"
            "The most common causes are a redirect URI that does not exactly "
            "match the dashboard, or an authorization code that expired "
            "while it sat unused."
        ) from exc


def main():
    client_id = _credential("SPOTIFY_CLIENT_ID", "Client ID: ")
    client_secret = _credential(
        "SPOTIFY_CLIENT_SECRET", "Client secret (hidden): ", secret=True
    )
    if not client_id or not client_secret:
        raise SystemExit("Both a client ID and a client secret are required.")

    state = secrets.token_urlsafe(16)
    url = build_auth_url(client_id, state)

    server = http.server.HTTPServer(("127.0.0.1", PORT), _CallbackHandler)
    threading.Thread(
        target=_serve_until_answered, args=(server,), daemon=True
    ).start()

    print("\nOpen this URL in a browser and approve access:\n")
    print(f"  {url}\n")
    print(f"Waiting for the redirect to {REDIRECT_URI} ...")
    webbrowser.open(url)  # no-ops harmlessly on a headless host

    deadline = time.monotonic() + 300
    while not _result and time.monotonic() < deadline:
        time.sleep(1)

    if not _result:
        raise SystemExit(
            "Timed out waiting for the callback. Authorization codes are "
            "short-lived, so just rerun the script."
        )
    if _result.get("error"):
        raise SystemExit(f"Spotify returned an error: {_result['error']}")
    if _result.get("state") != state:
        raise SystemExit(
            "State mismatch — the response did not come from the request "
            "this script started. Aborting."
        )
    code = _result.get("code")
    if not code:
        raise SystemExit("Callback carried no authorization code.")

    payload = exchange_code(client_id, client_secret, code)
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise SystemExit(f"No refresh_token in the response: {payload}")

    granted = payload.get("scope", "")
    print("\n" + "=" * 68)
    print("REFRESH TOKEN (paste into the SPOTIFY_REFRESH_TOKEN secret):\n")
    print(refresh_token)
    print("\nGranted scopes:", granted or "(none reported)")
    print("\nAlso set the repository variable SPOTIFY_AUTH_DATE to today.")
    print("This token expires 6 months from today; refreshing does not "
          "extend that.")
    print("=" * 68)

    for required in SCOPES.split():
        if required not in granted.split():
            print(f"WARNING: scope {required!r} was not granted.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
