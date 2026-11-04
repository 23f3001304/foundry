"""Login through Switch, and who a login acts for. Foundry keeps no password, and keeps Switch's cookie in memory only."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.requests import Request

from foundry.text import same_login

if TYPE_CHECKING:
    from foundry.desk import Settings

COOKIE = "foundry_session"
LIFETIME = timedelta(hours=12)
LOGIN_PATH = "/gateway/auth/login"
# Switch says one of these when the login or password is wrong. Any other answer is Switch having trouble.
REFUSED = (400, 401, 403, 422)


@dataclass(frozen=True)
class User:
    login: str
    # Each business this login manages, with the chat identity it acts as there.
    businesses: dict[str, str]


@dataclass
class Session:
    login: str
    # What Switch set when it accepted the login. It lives here and nowhere else.
    cookies: dict[str, str]
    csrf: str
    expires: datetime


def businesses_for(settings: "Settings", login: str) -> dict[str, str]:
    # Read from each pack's dashboard list. An entry that doesn't name both a login and who it acts as counts for nobody.
    wanted, found = same_login(login), {}
    for room, pack in settings.packs.items():
        for listed in pack.dashboard:
            if not isinstance(listed, dict) or not wanted or same_login(listed.get("login")) != wanted:
                continue
            acts_as = str(listed.get("acts_as") or "").strip()
            if acts_as:
                found.setdefault(settings.bucket_for(room), acts_as)
    return found


async def switch_login(switch_url: str, transport: httpx.AsyncBaseTransport | None, login: str, password: str) -> dict[str, str]:
    # trust_env off: a proxy named in the environment is never sent a password, whatever Switch's address is.
    async with httpx.AsyncClient(base_url=switch_url, transport=transport, timeout=15, trust_env=False) as switch:
        reply = await switch.post(LOGIN_PATH, json={"email": login, "password": password})
    reply.raise_for_status()
    return dict(reply.cookies.items())


def start_session(request: Request, login: str, cookies: dict[str, str]) -> tuple[str, Session]:
    sessions: dict[str, Session] = request.app.state.sessions
    now = datetime.now(UTC)
    for session_id in [key for key, session in sessions.items() if session.expires <= now]:
        del sessions[session_id]
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = Session(same_login(login), cookies, secrets.token_urlsafe(32), now + LIFETIME)
    return URLSafeTimedSerializer(request.app.state.secret, salt=COOKIE).dumps(session_id), sessions[session_id]


def end_session(request: Request) -> None:
    found = find_session(request)
    if found is not None:
        del request.app.state.sessions[found[0]]


def find_session(request: Request) -> tuple[str, Session] | None:
    signed = request.cookies.get(COOKIE)
    if not signed:
        return None
    try:
        session_id = URLSafeTimedSerializer(request.app.state.secret, salt=COOKIE).loads(signed, max_age=LIFETIME.total_seconds())
    except BadSignature:
        return None
    session = request.app.state.sessions.get(session_id)
    if session is None or session.expires <= datetime.now(UTC):
        return None
    return session_id, session


def current_user(request: Request) -> User | None:
    found = find_session(request)
    if found is None:
        return None
    return User(found[1].login, businesses_for(request.app.state.settings, found[1].login))


def csrf_ok(request: Request, sent: object) -> bool:
    found = find_session(request)
    return found is not None and isinstance(sent, str) and secrets.compare_digest(sent.encode(), found[1].csrf.encode())
