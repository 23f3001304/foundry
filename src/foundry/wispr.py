"""Wispr Flow's meeting notes, read through its MCP.

The owner signs in once in their browser (python -m foundry.wispr login). Foundry keeps the refresh token in .foundry/wispr.json,
which git ignores, and the desk reads notes after a meeting with no window open. Only reading is asked of Wispr.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

MCP_URL = "https://api.wisprflow.ai/connect/mcp"
AUTH = "https://mcp-auth.wisprflow.com/oauth2"
SCOPE = "openid offline_access"
TOKEN_PATH = Path(".foundry/wispr.json")
REDIRECT = "http://127.0.0.1:8765/callback"


class NotSignedIn(Exception):
    """Wispr has not been connected yet, or the owner took the access back."""


def _save(state: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(state), encoding="utf-8")


def _load() -> dict:
    if not TOKEN_PATH.exists():
        raise NotSignedIn("Wispr Flow is not connected. Run: python -m foundry.wispr login")
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def login(client: httpx.Client | None = None) -> None:
    """Register Foundry with Wispr, send the person to Wispr's sign-in page, catch the answer on this computer, and keep the tokens.

    Wispr's device-code page needs its own app to start it, so Foundry signs in the way Claude and Cursor do: a browser redirect back to 127.0.0.1.
    """
    import base64
    import hashlib
    import secrets
    import urllib.parse
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    http = client or httpx.Client(timeout=30)
    registered = http.post(f"{AUTH}/register", json={
        "client_name": "Foundry",
        "redirect_uris": [REDIRECT],
        "response_types": ["code"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    })
    registered.raise_for_status()
    client_id = registered.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = f"{AUTH}/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": MCP_URL,
    })
    caught: dict = {}

    class Catch(BaseHTTPRequestHandler):
        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in query or "error" in query:
                caught.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p style='font:20px sans-serif'>Foundry has your answer. You can close this tab.</p>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 8765), Catch)
    server.timeout = 1
    print(f"Sign in to Wispr Flow here: {url}", flush=True)
    webbrowser.open(url)
    deadline = time.monotonic() + 600
    while not caught and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if caught.get("state") != state or "code" not in caught:
        raise RuntimeError(f"Wispr sign-in stopped: {caught.get('error_description') or caught.get('error') or 'no answer in 10 minutes'}")
    answer = http.post(f"{AUTH}/token", data={
        "grant_type": "authorization_code", "code": caught["code"], "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier, "resource": MCP_URL,
    })
    if answer.status_code != 200:
        raise RuntimeError(f"Wispr refused the sign-in: {answer.json().get('error')}")
    _save({"client_id": client_id, "connected_at": time.time(), **_kept(answer.json())})
    print("Wispr Flow is connected.", flush=True)


def connected_at():
    """When Wispr was connected, or None if it isn't."""
    from datetime import UTC, datetime

    state = json.loads(TOKEN_PATH.read_text(encoding="utf-8")) if TOKEN_PATH.exists() else {}
    return datetime.fromtimestamp(state["connected_at"], UTC) if "connected_at" in state else None


def _kept(body: dict) -> dict:
    return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token"), "expires_at": time.time() + int(body.get("expires_in", 3600)) - 60}


def access_token(client: httpx.Client | None = None) -> str:
    """A live access token, refreshed when the kept one has run out."""
    state = _load()
    if time.time() < state["expires_at"]:
        return state["access_token"]
    if not state.get("refresh_token"):
        raise NotSignedIn("Wispr Flow's access ran out. Run: python -m foundry.wispr login")
    http = client or httpx.Client(timeout=30)
    answer = http.post(f"{AUTH}/token", data={"grant_type": "refresh_token", "refresh_token": state["refresh_token"], "client_id": state["client_id"], "resource": MCP_URL})
    if answer.status_code != 200:
        raise NotSignedIn("Wispr Flow's access was taken back. Run: python -m foundry.wispr login")
    state.update({k: v for k, v in _kept(answer.json()).items() if v})
    _save(state)
    return state["access_token"]


async def _session_call(work):
    from mcp import ClientSession
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {access_token()}"}, timeout=httpx2.Timeout(60, read=300))
    async with http, streamable_http_client(MCP_URL, http_client=http) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await work(session)


def _run(coroutine_factory):
    """Run on a thread of its own, because the desk calls this from inside its own event loop."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coroutine_factory())).result(timeout=120)


def call(tool: str, arguments: dict | None = None) -> str:
    """Call one Wispr tool and return its text."""
    async def work(session):
        result = await session.call_tool(tool, arguments or {})
        return "\n".join(part.text for part in result.content if getattr(part, "type", "") == "text")
    return _run(lambda: _session_call(work))


def tools() -> list[dict]:
    async def work(session):
        listed = await session.list_tools()
        return [{"name": t.name, "description": t.description, "input": t.input_schema} for t in listed.tools]
    return _run(lambda: _session_call(work))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "tools"
    if command == "login":
        login()
    elif command == "tools":
        print(json.dumps(tools(), indent=2))
    elif command == "call":
        print(call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}))
