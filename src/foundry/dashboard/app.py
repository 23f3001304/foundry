"""The dashboard's pages and actions. A page reads. An action adds a command, and the desk is the one that acts on it. The exception is a connection, which is Switch's: it is added and removed in Switch, as the person who is signed in."""

import inspect
import logging
import os
import re
import secrets
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import jinja2
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from foundry.chain import SAID
from foundry.commands import DUE_ACTIONS, KIT, CommandStore
from foundry.dashboard import charts, gateway, shapes
from foundry.dashboard import data as brand_data
from foundry.dashboard.auth import COOKIE, LIFETIME, REFUSED, User, csrf_ok, current_user, end_session, find_session, start_session, switch_login
from foundry.dashboard.queries import MEDIA, PICTURES, STEP_FAMILIES, ConnectionRow, NavCounts, Reader, bucket_name, is_made_file
from foundry.dashboard.shortened import shortened
from foundry.desk import Settings

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent
# The same sprites as the README, served from where they live.
TEAM = HERE.parents[2] / "assets" / "team"
POLICY = "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
NOT_ACCEPTED = "Switch did not accept that login."
# Pages are for this machine. A request that names any other host is somebody else's page asking for ours.
THIS_MACHINE = ["127.0.0.1", "localhost"]
NOT_FROM_HERE = "That login form didn't come from this page, so nothing was sent to Switch. Open the dashboard's own address and try again."
SWITCH_TROUBLE = "Switch had a problem with that login. Try again in a moment."
ASK_FOR_BOTH = "Enter your login and your password."
NO_DATA = "Foundry's data can't be read just now. If the desk has never run, start it first. Otherwise try again in a moment."
FORM_EXPIRED = "That form didn't come from this page, so nothing was done. Reload the page and try again."
ERRORS = {
    400: "That wasn't something this page can do.",
    403: "You can't do that here.",
    404: "That page isn't here, or it belongs to someone else.",
    405: "That page doesn't take this.",
    411: "That form needs a length, and this one had none, so nothing was done.",
    413: "That file is too big.",
}
MOST_STATEMENT = 200
JOB_ACTIONS = ("restart", *DUE_ACTIONS)
JOB_ANSWERS = ("approve", "revise")
MOST_CHOICE = 300
# A form with a file in it can be a little over the file's own limit. Anything bigger is refused before it is read, and so is one that doesn't say how big it is.
MOST_BODY = brand_data.MOST_TABLE + 500_000
# A sign-in is a login and a password.
MOST_LOGIN_BODY = 20_000
# More digits than this is not a number a form could mean, and is cheap to refuse before it is read as one.
MOST_DIGITS = 9
MOST_NAME = 80
# The pages a person opens a file from, for its way back.
BACK_PATHS = re.compile(r"/(work|jobs|log|responses)?|/jobs/[\w-]+|/log/flagged/\d+")
DEFAULT_BACK = "/work"
MOST_BACK = 500
NEEDS_NAME = "Give the connection a name."
NAME_TOO_LONG = f"Use a name of {MOST_NAME} letters or fewer."
CONFIRM_FIRST = "Open the warning for this connection first. Nothing was deleted."
ROOMS_CHANGED = "The rooms on this connection changed since you looked, so nothing was deleted. Read the warning again and confirm."
NOTICES = {
    "added": "The connection was added. It has no rooms yet, so it shows in this list once a room of yours uses it.",
    "removed": "The connection and the rooms on it were deleted.",
    "saved": "Saved. The new file is used straight away, including on jobs already running. The agents' copy of the brand kit in Switch is not changed by this.",
}

Handler = Callable[..., Response | Awaitable[Response]]


def whole_number(value: object) -> int | None:
    text = str(value or "")
    return int(text) if text.isascii() and text.isdigit() and len(text) <= MOST_DIGITS else None


def link(path: str, **query: str) -> str:
    # An address for a page, with whichever of these have a value. Used in templates, so a filter is kept the one way everywhere.
    kept = {key: value for key, value in query.items() if value}
    return f"{path}?{urlencode(kept)}" if kept else path


def back_from(value: object) -> str:
    # Where a page's Close goes, from its address, so only a page of this dashboard people come to a file from. Anything else goes to Generated work.
    text = str(value or "")
    if len(text) > MOST_BACK or any(ord(letter) < 32 or letter == "\\" for letter in text):
        return DEFAULT_BACK
    parts = urlsplit(text)
    return text if not parts.scheme and not parts.netloc and BACK_PATHS.fullmatch(parts.path) else DEFAULT_BACK


def render(request: Request, name: str, user: User | None = None, status: int = 200, **context) -> Response:
    found = find_session(request)
    # A page reached some other way than a signed-in handler, like an address that isn't here, shows no counts.
    counts = getattr(request.state, "counts", None) or NavCounts()
    return request.app.state.templates.TemplateResponse(request, name, {"user": user, "csrf": found[1].csrf if found else "", "counts": counts, "here": f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path, **context}, status_code=status)


def check_body(request: Request, most: int) -> None:
    # A form says how big it is, once, and is no bigger than the most its page takes. One sent in pieces is not read, whatever length it also claims.
    if "transfer-encoding" in request.headers:
        raise HTTPException(411)
    length = whole_number(request.headers.get("content-length"))
    if length is None:
        raise HTTPException(411)
    if length > most:
        raise HTTPException(413)


def signed_in(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
    # Every page and every action needs a login. A form also has to carry the token its own page gave it.
    async def guarded(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", 303)
        arguments: tuple = (request, user)
        if request.method == "POST":
            check_body(request, MOST_BODY)
            form = await request.form()
            if not csrf_ok(request, form.get("csrf")):
                raise HTTPException(403, FORM_EXPIRED)
            arguments = (request, user, form)
        request.state.counts = await run_in_threadpool(request.app.state.reader.nav_counts, user)
        # A handler that waits on Switch is async and runs on the loop. The rest are plain functions that read SQLite or files, so they run in the thread pool and not on the event loop.
        if inspect.iscoroutinefunction(handler):
            return await handler(*arguments)
        return await run_in_threadpool(handler, *arguments)

    return guarded


def in_view(request: Request, user: User) -> tuple[User, str]:
    # The login with only the business the address names. A name that isn't one of theirs shows them all, the same as any filter nobody knows.
    wanted = request.query_params.get("business", "")
    if len(user.businesses) > 1 and wanted in user.businesses:
        return User(user.login, {wanted: user.businesses[wanted]}), wanted
    return user, ""


def one_business(request: Request, user: User) -> tuple[User, str]:
    # The overview shows one business at a time, so someone with several starts on their first and moves with the switcher.
    shown, business = in_view(request, user)
    if len(shown.businesses) > 1:
        business = next(iter(shown.businesses))
        return User(user.login, {business: user.businesses[business]}), business
    return shown, business


def job_of(request: Request, user: User, job_id: str):
    job = request.app.state.reader.job_of(user, job_id)
    if job is None:
        raise HTTPException(404)
    return job


def ask(request: Request, user: User, action: str, payload: dict, bucket: str) -> None:
    # The command names the client it is about, and the desk compares that with the card or job's own.
    request.app.state.commands.add(action, {"bucket": bucket, **payload}, user.login, user.businesses[bucket])


def note_connection(request: Request, user: User, buckets: Sequence[str], what: str, name: str, kind: str, rooms: int = 0, sure: bool = True) -> None:
    # Switch has done it, or may have, as this person. The desk writes it in the action log of each business the person acts for, as it writes a change to the data. Nothing typed as a secret is in it.
    for bucket in buckets:
        try:
            ask(request, user, "note_connection", {"what": what, "name": name, "kind": kind, "rooms": rooms, "sure": sure}, bucket)
        except Exception:
            logger.exception("Could not leave a note of the connection change for %s to write in the log.", bucket)


def recent(request: Request, user: User):
    return request.app.state.reader.recent(request.app.state.commands, user.login)


# Login


async def login_page(request: Request) -> Response:
    if current_user(request) is not None:
        return RedirectResponse("/", 303)
    return render(request, "login.html", title="Sign in", error="")


async def login_submit(request: Request) -> Response:
    # A browser says which page a form came from. One from another site isn't sent on to Switch.
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
        return render(request, "login.html", title="Sign in", status=403, error=NOT_FROM_HERE)
    check_body(request, MOST_LOGIN_BODY)
    form = await request.form()
    login, password = str(form.get("login") or "").strip(), str(form.get("password") or "")
    if not login or not password:
        return render(request, "login.html", title="Sign in", status=400, error=ASK_FOR_BOTH)
    try:
        cookies = await switch_login(request.app.state.switch_url, request.app.state.transport, login, password)
    except httpx.HTTPStatusError as error:
        refused = error.response.status_code in REFUSED
        return render(request, "login.html", title="Sign in", status=401 if refused else 503, error=NOT_ACCEPTED if refused else SWITCH_TROUBLE)
    except httpx.HTTPError:
        return render(request, "login.html", title="Sign in", status=503, error=gateway.SWITCH_DOWN)
    signed, _ = start_session(request, login, cookies)
    response = RedirectResponse("/", 303)
    # Strict, so another site can't send a form from here. HttpOnly, so no page can read it.
    response.set_cookie(COOKIE, signed, max_age=int(LIFETIME.total_seconds()), httponly=True, samesite="strict", path="/")
    return response


@signed_in
def logout(request: Request, user: User, form: FormData) -> Response:
    end_session(request)
    response = RedirectResponse("/login", 303)
    response.delete_cookie(COOKIE, path="/")
    return response


# Pages


async def connection_rows(request: Request, user: User, timeout: float) -> list[ConnectionRow]:
    # The connections this login may see, as Switch has them now.
    async with gateway.open_gateway(request, timeout) as switch:
        bridges = await gateway.bridges(switch)
        rooms = await gateway.rooms(switch)
    return request.app.state.reader.connections(user, bridges, rooms)


async def own_connection(request: Request, user: User, bridge_id: str) -> ConnectionRow | None:
    # Looked up fresh each time, so what a form names is only ever matched against what Switch says now.
    if not user.businesses:
        return None
    # One that other businesses use as well is shown for its health alone, and is not found here.
    return next((row for row in await connection_rows(request, user, gateway.READ_TIMEOUT) if row.id == bridge_id and not row.shared), None)


@signed_in
async def overview(request: Request, user: User) -> Response:
    shown, business = one_business(request, user)
    figures = await run_in_threadpool(request.app.state.reader.overview, shown)
    health = {}
    if shown.businesses:
        # Nothing else on the page needs Switch, so Switch being down only changes this line.
        try:
            # A room two businesses share counts as this login's when it has both, so the rows come from the whole login and only the line is for the business shown.
            health = request.app.state.reader.health(shown, await connection_rows(request, user, gateway.READ_TIMEOUT))
        except gateway.SwitchProblem as trouble:
            health = dict.fromkeys(shown.businesses, trouble.message)
    boards = await run_in_threadpool(request.app.state.reader.boards, shown)
    return render(request, "overview.html", user, title="Overview", page="overview", figures=figures, health=health, boards=boards, business=business)


# Connections


def connections_link(request: Request) -> str:
    return f"{request.app.state.switch_url.rstrip('/')}/collaborations"


@signed_in
async def connections(request: Request, user: User) -> Response:
    rows, problem, status = [], "", 200
    if user.businesses:
        try:
            rows = await connection_rows(request, user, gateway.READ_TIMEOUT)
        except gateway.SwitchProblem as trouble:
            problem, status = trouble.message, trouble.status
    return render(request, "connections.html", user, status, title="Connections", page="connections", rows=rows, problem=problem, notice=NOTICES.get(request.query_params.get("done", "")), gateway_link=connections_link(request))


def add_page(request: Request, user: User, kinds: list[gateway.BridgeType], chosen: gateway.BridgeType | None, problem: str = "", status: int = 200, unsure: bool = False) -> Response:
    return render(request, "connection_add.html", user, status, title="Add a connection", page="connections", kinds=kinds, chosen=chosen, problem=problem, unsure=unsure, gateway_link=connections_link(request))


@signed_in
async def connection_add_page(request: Request, user: User) -> Response:
    if not user.businesses:
        raise HTTPException(403)
    try:
        async with gateway.open_gateway(request, gateway.READ_TIMEOUT) as switch:
            kinds = await gateway.bridge_types(switch)
    except gateway.SwitchProblem as trouble:
        return add_page(request, user, [], None, trouble.message, trouble.status)
    wanted = request.query_params.get("type")
    chosen = next((kind for kind in kinds if kind.key == wanted), None)
    if wanted and chosen is None:
        raise HTTPException(404)
    return add_page(request, user, kinds, chosen)


def add_problem(name: str, missing: list[str]) -> str:
    # What is wrong with the form before anything is sent to Switch. It names the fields left empty and never what was typed.
    if not name:
        return NEEDS_NAME
    if len(name) > MOST_NAME:
        return NAME_TOO_LONG
    return " ".join(f"{label} is needed." for label in missing)


@signed_in
async def connection_add(request: Request, user: User, form: FormData) -> Response:
    # What is typed here goes to Switch and nowhere else. It is not logged, not kept, and never put back in a page.
    if not user.businesses:
        raise HTTPException(403)
    kinds, chosen, name = [], None, ""
    try:
        async with gateway.open_gateway(request, gateway.WRITE_TIMEOUT) as switch:
            kinds = await gateway.bridge_types(switch)
            chosen = next((kind for kind in kinds if kind.key == form.get("type")), None)
            if chosen is None:
                raise HTTPException(404)
            name = " ".join(str(form.get("display_name") or "").split())
            config, missing, secrets_typed = gateway.configuration(chosen, form)
            if problem := add_problem(name, missing):
                return add_page(request, user, kinds, chosen, problem, 400)
            await gateway.add_bridge(switch, chosen, name, config, secrets_typed)
    except gateway.SwitchProblem as trouble:
        if trouble.unsure:
            note_connection(request, user, list(user.businesses), "added", name, chosen.key, sure=False)
        return add_page(request, user, kinds, chosen, trouble.message, trouble.status, trouble.unsure)
    logger.info("%s added a %s connection.", user.login, chosen.key)
    note_connection(request, user, list(user.businesses), "added", name, chosen.key)
    return RedirectResponse("/connections?done=added", 303)


def remove_page(request: Request, user: User, row: ConnectionRow | None, problem: str = "", status: int = 200, unsure: bool = False) -> Response:
    # When the delete may have gone part way, the page does not offer to do it again.
    return render(request, "connection_remove.html", user, status, title="Remove a connection", page="connections", row=row, problem=problem, unsure=unsure, gateway_link=connections_link(request))


@signed_in
async def connection_remove_page(request: Request, user: User) -> Response:
    try:
        row = await own_connection(request, user, request.path_params["bridge_id"])
    except gateway.SwitchProblem as trouble:
        return remove_page(request, user, None, trouble.message, trouble.status)
    if row is None:
        raise HTTPException(404)
    return remove_page(request, user, row)


@signed_in
async def connection_remove(request: Request, user: User, form: FormData) -> Response:
    row = None
    try:
        row = await own_connection(request, user, request.path_params["bridge_id"])
        if row is None:
            raise HTTPException(404)
        if not row.removable:
            return remove_page(request, user, row, status=403)
        # The warning said how many rooms would go. If that is no longer so, the person is asked again.
        sent = whole_number(form.get("rooms"))
        if sent is None:
            return remove_page(request, user, row, CONFIRM_FIRST, 400)
        if sent != row.room_total:
            return remove_page(request, user, row, ROOMS_CHANGED, 409)
        async with gateway.open_gateway(request, gateway.WRITE_TIMEOUT) as switch:
            await gateway.delete_bridge(switch, row.id)
    except gateway.SwitchProblem as trouble:
        if trouble.unsure and row is not None:
            note_connection(request, user, row.serves, "removed", row.name, row.kind, row.room_total, sure=False)
        return remove_page(request, user, row, trouble.message, trouble.status, trouble.unsure)
    logger.info("%s removed connection %s and its %d rooms.", user.login, row.id, row.room_total)
    note_connection(request, user, row.serves, "removed", row.name, row.kind, row.room_total)
    return RedirectResponse("/connections?done=removed", 303)


# Data


def data_page(request: Request, user: User, problem: str = "", status: int = 200) -> Response:
    reader = request.app.state.reader
    return render(request, "data.html", user, status, title="Data", page="data", clients=reader.data(user), problem=problem, notice=NOTICES.get(request.query_params.get("done", "")), recent=recent(request, user))


@signed_in
def data(request: Request, user: User) -> Response:
    return data_page(request, user)


@signed_in
def data_file(request: Request, user: User) -> Response:
    view = request.app.state.reader.data_view(user, request.path_params["bucket"], request.path_params["file"])
    if view is None:
        raise HTTPException(404)
    return render(request, "data_file.html", user, title=view.file, page="data", view=view, problem="", recent=recent(request, user))


def read_upload(form: FormData) -> tuple[str, bytes, str | None]:
    # The name the file came with, what is in it, and what is wrong with it. Only as much is read as the biggest thing a source can be.
    upload = form.get("upload")
    if not isinstance(upload, UploadFile):
        return "", b"", brand_data.NO_FILE
    return upload.filename or "", upload.file.read(brand_data.MOST_TABLE + 1), None


@signed_in
def data_save(request: Request, user: User, form: FormData) -> Response:
    # Replaces a file that is already there, or gives a brand with no kit its first one. The folder and the name are matched against what is on disk, never built into a path.
    bucket, file = request.path_params["bucket"], request.path_params["file"]
    folder = request.app.state.reader.data_folder(user, bucket)
    found = brand_data.find(folder, file) if folder else None
    if folder is None or (found is None and file != KIT):
        raise HTTPException(404)
    target, problem = (found.path, None) if found else brand_data.target_for_kit(folder)
    content, status = b"", 400
    if problem is None:
        _, raw, problem = read_upload(form)
        if problem is None:
            content, problem = brand_data.checked(file, raw, folder)
    if problem is None:
        problem, status = brand_data.write(target, content), 500
    if problem:
        view = request.app.state.reader.data_view(user, bucket, file)
        if view is None:
            return data_page(request, user, problem, status)
        return render(request, "data_file.html", user, status, title=file, page="data", view=view, problem=problem, recent=recent(request, user))
    ask(request, user, "reload_pack", {"file": brand_data.relative(file), "sha": brand_data.fingerprint(content)}, bucket)
    return RedirectResponse("/data?done=saved", 303)


@signed_in
def data_add(request: Request, user: User, form: FormData) -> Response:
    # A new source, named by the file chosen. A name already there, in any letters, is replaced.
    bucket = request.path_params["bucket"]
    folder = request.app.state.reader.data_folder(user, bucket)
    if folder is None:
        raise HTTPException(404)
    name, raw, problem = read_upload(form)
    if problem != brand_data.NO_FILE:
        problem = brand_data.name_problem(name)
    target, content, status = None, b"", 400
    if problem is None:
        target, problem = brand_data.target_for(folder, name)
    if target is not None:
        content, problem = brand_data.checked(name, raw, folder)
        if problem is None:
            problem, status = brand_data.write(target, content), 500
    if problem:
        return data_page(request, user, problem, status)
    ask(request, user, "reload_pack", {"file": brand_data.relative(target.name), "sha": brand_data.fingerprint(content)}, bucket)
    return RedirectResponse("/data?done=saved", 303)


@signed_in
def jobs(request: Request, user: User) -> Response:
    shown, business = in_view(request, user)
    stage = request.query_params.get("stage", "")
    return render(request, "jobs.html", user, title="Jobs", page="jobs", board=request.app.state.reader.job_board(shown, stage), business=business, stage=stage)


@signed_in
def job(request: Request, user: User) -> Response:
    page = request.app.state.reader.job_page(user, request.path_params["job_id"])
    if page is None:
        raise HTTPException(404)
    return render(request, "job.html", user, title=page.row.title, page="jobs", job=page, tabs=request.app.state.reader.job_nav(user, page.row.id), recent=recent(request, user))


@signed_in
def job_act(request: Request, user: User, form: FormData) -> Response:
    found = job_of(request, user, request.path_params["job_id"])
    action = form.get("action")
    if action not in JOB_ACTIONS:
        raise HTTPException(400)
    ask(request, user, action, {"job_id": found.id}, found.bucket)
    return RedirectResponse(f"/jobs/{found.id}", 303)


@signed_in
def job_answer(request: Request, user: User, form: FormData) -> Response:
    found = job_of(request, user, request.path_params["job_id"])
    card = request.app.state.reader.card(str(form.get("request_id") or ""))
    if card is None or card.job_id != found.id or card.bucket != found.bucket:
        raise HTTPException(404)
    choice = form.get("choice")
    if choice not in JOB_ANSWERS:
        raise HTTPException(400)
    payload = {"request_id": card.request_id, "choice": choice}
    if choice == "revise":
        payload["notes"] = str(form.get("notes") or "").strip()
    ask(request, user, "answer_card", payload, found.bucket)
    return RedirectResponse(f"/jobs/{found.id}", 303)


@signed_in
def work(request: Request, user: User) -> Response:
    # One job's files, for that job's own tab. A job of another client is not found, so nobody can tell it exists.
    reader, only = request.app.state.reader, request.query_params.get("job")
    tabs = reader.job_nav(user, only) if only else None
    if only and tabs is None:
        raise HTTPException(404)
    return render(request, "work.html", user, title=tabs.title if tabs else "Generated work", page="jobs" if tabs else "work", jobs=reader.work(user, only), tabs=tabs)


@signed_in
def work_file(request: Request, user: User) -> Response:
    found = request.app.state.reader.file_for(user, request.path_params["entry_id"])
    if found is None:
        raise HTTPException(404)
    path, name = found
    suffix = path.suffix.lower()
    inline = (suffix in PICTURES or suffix == ".pdf") and "download" not in request.query_params
    return FileResponse(path, media_type=MEDIA[suffix], filename=name, content_disposition_type="inline" if inline else "attachment")


@signed_in
def work_view(request: Request, user: User) -> Response:
    # A page of its own for a work file, with a way back. It shows what the raw address would serve, to whoever it would serve it to.
    found = request.app.state.reader.viewed(user, request.path_params["entry_id"])
    if found is None:
        raise HTTPException(404)
    return render(request, "viewer.html", user, 200 if found.here else 404, title=found.name, focus=True, file=found, back=back_from(request.query_params.get("back")))


@signed_in
def work_slide(request: Request, user: User) -> Response:
    path = request.app.state.reader.slide_for(user, request.path_params["entry_id"], request.path_params["number"])
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type=MEDIA[path.suffix.lower()], filename=path.name, content_disposition_type="inline")


@signed_in
def responses(request: Request, user: User) -> Response:
    cards, hidden = request.app.state.reader.card_rows(user)
    return render(request, "responses.html", user, title="Responses", page="responses", cards=cards, hidden=hidden, recent=recent(request, user))


@signed_in
def responses_answer(request: Request, user: User, form: FormData) -> Response:
    card = request.app.state.reader.card(str(form.get("request_id") or ""))
    if card is None or card.bucket not in user.businesses:
        raise HTTPException(404)
    choice = str(form.get("choice") or "")
    if not choice or len(choice) > MOST_CHOICE:
        raise HTTPException(400)
    payload = {"request_id": card.request_id, "choice": choice}
    if notes := str(form.get("notes") or "").strip():
        payload["notes"] = notes
    ask(request, user, "answer_card", payload, card.bucket)
    return RedirectResponse("/responses", 303)


@signed_in
def action_log(request: Request, user: User) -> Response:
    reader, only = request.app.state.reader, request.query_params.get("job")
    timelines, more = reader.job_logs(user, only)
    if only and not timelines:
        raise HTTPException(404)
    flagged = reader.flagged(user)
    # A job's timeline is one of that job's pages, so what it lists is that job's.
    tabs = reader.job_nav(user, only) if only else None
    if tabs:
        flagged = [item for item in flagged if item.job_id == only]
    return render(request, "log.html", user, title=tabs.title if tabs else "Action log", page="jobs" if tabs else "log", jobs=timelines, more=more, only=only, flagged=flagged, tabs=tabs, recent=recent(request, user))


@signed_in
def log_flag(request: Request, user: User, form: FormData) -> Response:
    found = job_of(request, user, str(form.get("job_id") or ""))
    if found.approver != user.businesses[found.bucket]:
        raise HTTPException(403)
    # The target is built here from an entry of this job, never from a path or a number the form names.
    entries = {entry.id: entry for entry in request.app.state.reader.entries_of(found)}
    what = form.get("what")
    if what in ("file", "text"):
        made = entries.get(whole_number(form.get("file")))
        if made is None or not is_made_file(made):
            raise HTTPException(404)
        statement = " ".join(str(form.get("statement") or "").split())
        if what == "text" and not 0 < len(statement) <= MOST_STATEMENT:
            raise HTTPException(400)
        target = f"file:{made.ref}" if what == "file" else f"text:{made.ref}:{statement}"
    elif what == "entry":
        said = entries.get(whole_number(form.get("entry")))
        if said is None or said.kind not in SAID:
            raise HTTPException(404)
        target = f"entry:{said.id}"
    else:
        raise HTTPException(400)
    ask(request, user, "flag", {"job_id": found.id, "target": target}, found.bucket)
    return RedirectResponse("/log", 303)


@signed_in
def chain(request: Request, user: User) -> Response:
    page = request.app.state.reader.chain(user, request.path_params["flag_id"])
    if page is None:
        raise HTTPException(404)
    return render(request, "chain.html", user, title="Chain", page="log", chain=page, tabs=request.app.state.reader.job_nav(user, page.job_id) if page.job_id else None)


# Around the pages


async def secure(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store"
    return response


async def http_error(request: Request, error: HTTPException) -> Response:
    # A form the page didn't give carries its own wording. The rest say what the page can't do.
    message = error.detail if error.status_code == 403 and error.detail == FORM_EXPIRED else ERRORS.get(error.status_code, "Something went wrong.")
    return render(request, "error.html", current_user(request), error.status_code, title="Not done", message=message)


async def no_data(request: Request, error: sqlite3.OperationalError) -> Response:
    return render(request, "error.html", current_user(request), 503, title="No data", message=NO_DATA)


def create_app(settings: Settings, switch_url: str, transport: httpx.AsyncBaseTransport | None = None, secret: str | None = None) -> Starlette:
    routes = [
        Route("/login", login_page),
        Route("/login", login_submit, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/", overview),
        Route("/connections", connections),
        Route("/connections/add", connection_add_page),
        Route("/connections/add", connection_add, methods=["POST"]),
        Route("/connections/{bridge_id}/remove", connection_remove_page),
        Route("/connections/{bridge_id}/remove", connection_remove, methods=["POST"]),
        Route("/data", data),
        Route("/data/{bucket}/add", data_add, methods=["POST"]),
        Route("/data/{bucket}/{file}", data_file),
        Route("/data/{bucket}/{file}", data_save, methods=["POST"]),
        Route("/jobs", jobs),
        Route("/jobs/{job_id}", job),
        Route("/jobs/{job_id}/act", job_act, methods=["POST"]),
        Route("/jobs/{job_id}/answer", job_answer, methods=["POST"]),
        Route("/work", work),
        Route("/work/files/{entry_id:int}", work_file),
        Route("/work/view/{entry_id:int}", work_view),
        Route("/work/view/{entry_id:int}/slides/{number:int}", work_slide),
        Route("/responses", responses),
        Route("/responses/answer", responses_answer, methods=["POST"]),
        Route("/log", action_log),
        Route("/log/flag", log_flag, methods=["POST"]),
        Route("/log/flagged/{flag_id:int}", chain),
        Mount("/static/team", StaticFiles(directory=TEAM, check_dir=False)),
        Mount("/static", StaticFiles(directory=HERE / "static")),
    ]
    app = Starlette(
        routes=routes,
        middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=THIS_MACHINE), Middleware(BaseHTTPMiddleware, dispatch=secure)],
        exception_handlers={HTTPException: http_error, sqlite3.OperationalError: no_data},
    )
    reader = Reader(settings)
    environment = jinja2.Environment(loader=jinja2.FileSystemLoader(HERE / "templates"), autoescape=True)
    environment.filters["when"] = reader.when
    environment.filters["client"] = bucket_name
    environment.filters["shortened"] = shortened
    environment.globals["charts"] = charts
    environment.globals["shapes"] = shapes
    environment.globals["families"] = STEP_FAMILIES
    environment.globals["link"] = link
    app.state.settings, app.state.reader, app.state.commands = settings, reader, CommandStore(settings.commands_path)
    app.state.templates = Jinja2Templates(env=environment)
    # Without a secret from the environment each run has its own, so a restart signs everyone out.
    app.state.secret = secret or os.environ.get("FOUNDRY_DASHBOARD_SECRET") or secrets.token_hex(32)
    app.state.sessions, app.state.switch_url, app.state.transport = {}, switch_url, transport
    return app
