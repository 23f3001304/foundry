"""The dashboard's pages and actions. A page reads. An action adds a command, and the desk is the one that acts on it. The exception is a connection, which is Switch's: it is added and removed in Switch, as the person who is signed in."""

import inspect
import logging
import os
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

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
from foundry.dashboard import data as brand_data
from foundry.dashboard import gateway
from foundry.dashboard.auth import COOKIE, LIFETIME, REFUSED, User, csrf_ok, current_user, end_session, find_session, start_session, switch_login
from foundry.dashboard.queries import MEDIA, PICTURES, ConnectionRow, Reader, is_made_file
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
    413: "That file is too big.",
}
MOST_STATEMENT = 200
JOB_ACTIONS = ("restart", *DUE_ACTIONS)
JOB_ANSWERS = ("approve", "revise")
MOST_CHOICE = 300
# A form with a file in it can be a little over the file's own limit. Anything bigger is refused before it is read.
MOST_BODY = 1_000_000
MOST_NAME = 80
NEEDS_NAME = "Give the connection a name."
NAME_TOO_LONG = f"Use a name of {MOST_NAME} letters or fewer."
CONFIRM_FIRST = "Open the warning for this connection first. Nothing was deleted."
ROOMS_CHANGED = "The rooms on this connection changed since you looked, so nothing was deleted. Read the warning again and confirm."
NOTICES = {
    "added": "The connection was added. It has no rooms yet, so it shows in this list once a room of yours uses it.",
    "removed": "The connection and the rooms on it were deleted.",
    "saved": "Saved. The desk reads it again within a few seconds, and jobs that start after that use it.",
}

Handler = Callable[..., Response | Awaitable[Response]]


def whole_number(value: object) -> int | None:
    text = str(value or "")
    return int(text) if text.isascii() and text.isdigit() else None


def render(request: Request, name: str, user: User | None = None, status: int = 200, **context) -> Response:
    found = find_session(request)
    return request.app.state.templates.TemplateResponse(request, name, {"user": user, "csrf": found[1].csrf if found else "", **context}, status_code=status)


def signed_in(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
    # Every page and every action needs a login. A form also has to carry the token its own page gave it.
    async def guarded(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/login", 303)
        arguments: tuple = (request, user)
        if request.method == "POST":
            if (whole_number(request.headers.get("content-length")) or 0) > MOST_BODY:
                raise HTTPException(413)
            form = await request.form()
            if not csrf_ok(request, form.get("csrf")):
                raise HTTPException(403, FORM_EXPIRED)
            arguments = (request, user, form)
        # A handler that waits on Switch is async and runs on the loop. The rest are plain functions that read SQLite or files, so they run in the thread pool and not on the event loop.
        if inspect.iscoroutinefunction(handler):
            return await handler(*arguments)
        return await run_in_threadpool(handler, *arguments)

    return guarded


def job_of(request: Request, user: User, job_id: str):
    job = request.app.state.reader.job_of(user, job_id)
    if job is None:
        raise HTTPException(404)
    return job


def ask(request: Request, user: User, action: str, payload: dict, bucket: str) -> None:
    # The command names the client it is about, and the desk compares that with the card or job's own.
    request.app.state.commands.add(action, {"bucket": bucket, **payload}, user.login, user.businesses[bucket])


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
    return next((row for row in await connection_rows(request, user, gateway.READ_TIMEOUT) if row.id == bridge_id), None)


@signed_in
async def overview(request: Request, user: User) -> Response:
    figures = await run_in_threadpool(request.app.state.reader.overview, user)
    health = {}
    if user.businesses:
        # Nothing else on the page needs Switch, so Switch being down only changes this line.
        try:
            health = request.app.state.reader.health(user, await connection_rows(request, user, gateway.READ_TIMEOUT))
        except gateway.SwitchProblem as trouble:
            health = dict.fromkeys(user.businesses, trouble.message)
    return render(request, "overview.html", user, title="Overview", page="overview", figures=figures, health=health)


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


def add_page(request: Request, user: User, kinds: list[gateway.BridgeType], chosen: gateway.BridgeType | None, problem: str = "", status: int = 200) -> Response:
    return render(request, "connection_add.html", user, status, title="Add a connection", page="connections", kinds=kinds, chosen=chosen, problem=problem, gateway_link=connections_link(request))


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
    kinds, chosen = [], None
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
        return add_page(request, user, kinds, chosen, trouble.message, trouble.status)
    logger.info("%s added a %s connection.", user.login, chosen.key)
    return RedirectResponse("/connections?done=added", 303)


def remove_page(request: Request, user: User, row: ConnectionRow | None, problem: str = "", status: int = 200) -> Response:
    return render(request, "connection_remove.html", user, status, title="Remove a connection", page="connections", row=row, problem=problem)


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
        if sent != len(row.rooms):
            return remove_page(request, user, row, ROOMS_CHANGED, 409)
        async with gateway.open_gateway(request, gateway.WRITE_TIMEOUT) as switch:
            await gateway.delete_bridge(switch, row.id)
    except gateway.SwitchProblem as trouble:
        return remove_page(request, user, row, trouble.message, trouble.status)
    logger.info("%s removed connection %s and its %d rooms.", user.login, row.id, len(row.rooms))
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


def read_upload(form: FormData) -> tuple[str, str, str | None]:
    # The name the file came with, its text, and what is wrong with it. Only as much is read as a source can be.
    upload = form.get("upload")
    if not isinstance(upload, UploadFile):
        return "", "", brand_data.NO_FILE
    text, problem = brand_data.text_of(upload.file.read(brand_data.MOST_UPLOAD + 1))
    return upload.filename or "", text, problem


@signed_in
def data_save(request: Request, user: User, form: FormData) -> Response:
    # Replaces a file that is already there. The folder and the name are matched against what is on disk, never built into a path.
    bucket, file = request.path_params["bucket"], request.path_params["file"]
    folder = request.app.state.reader.data_folder(user, bucket)
    found = brand_data.find(folder, file) if folder else None
    if found is None:
        raise HTTPException(404)
    _, text, problem = read_upload(form)
    if problem is None and file == KIT:
        problem = brand_data.kit_problem(text, folder)
    status = 400
    if problem is None:
        problem, status = brand_data.write(found.path, text), 500
    if problem:
        view = request.app.state.reader.data_view(user, bucket, file)
        return render(request, "data_file.html", user, status, title=file, page="data", view=view, problem=problem, recent=recent(request, user))
    ask(request, user, "reload_pack", {"file": brand_data.relative(file)}, bucket)
    return RedirectResponse("/data?done=saved", 303)


@signed_in
def data_add(request: Request, user: User, form: FormData) -> Response:
    # A new source document, named by the file chosen. A name already there, in any letters, is replaced.
    bucket = request.path_params["bucket"]
    folder = request.app.state.reader.data_folder(user, bucket)
    if folder is None:
        raise HTTPException(404)
    name, text, problem = read_upload(form)
    if problem != brand_data.NO_FILE:
        problem = brand_data.name_problem(name) or problem
    target, status = None, 400
    if problem is None:
        target, problem = brand_data.target_for(folder, name)
    if target is not None:
        problem, status = brand_data.write(target, text), 500
    if problem:
        return data_page(request, user, problem, status)
    ask(request, user, "reload_pack", {"file": brand_data.relative(target.name)}, bucket)
    return RedirectResponse("/data?done=saved", 303)


@signed_in
def jobs(request: Request, user: User) -> Response:
    return render(request, "jobs.html", user, title="Jobs", page="jobs", rows=request.app.state.reader.job_rows(user))


@signed_in
def job(request: Request, user: User) -> Response:
    page = request.app.state.reader.job_page(user, request.path_params["job_id"])
    if page is None:
        raise HTTPException(404)
    return render(request, "job.html", user, title=page.row.title, page="jobs", job=page, recent=recent(request, user))


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
    return render(request, "work.html", user, title="Generated work", page="work", jobs=request.app.state.reader.work(user))


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
    return render(request, "log.html", user, title="Action log", page="log", jobs=timelines, more=more, only=only, flagged=reader.flagged(user), recent=recent(request, user))


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
    return render(request, "chain.html", user, title="Chain", page="log", chain=page)


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
    app.state.settings, app.state.reader, app.state.commands = settings, reader, CommandStore(settings.commands_path)
    app.state.templates = Jinja2Templates(env=environment)
    # Without a secret from the environment each run has its own, so a restart signs everyone out.
    app.state.secret = secret or os.environ.get("FOUNDRY_DASHBOARD_SECRET") or secrets.token_hex(32)
    app.state.sessions, app.state.switch_url, app.state.transport = {}, switch_url, transport
    return app
