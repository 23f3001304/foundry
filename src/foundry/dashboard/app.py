"""The dashboard's pages and actions. A page reads. An action adds a command, and the desk is the one that acts on it."""

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
from starlette.datastructures import FormData
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
from foundry.commands import DUE_ACTIONS, CommandStore
from foundry.dashboard.auth import COOKIE, LIFETIME, REFUSED, User, csrf_ok, current_user, end_session, find_session, start_session, switch_login
from foundry.dashboard.queries import MEDIA, PICTURES, Reader, is_made_file
from foundry.desk import Settings

HERE = Path(__file__).parent
# The same sprites as the README, served from where they live.
TEAM = HERE.parents[2] / "assets" / "team"
POLICY = "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
NOT_ACCEPTED = "Switch did not accept that login."
# Pages are for this machine. A request that names any other host is somebody else's page asking for ours.
THIS_MACHINE = ["127.0.0.1", "localhost"]
NOT_FROM_HERE = "That login form didn't come from this page, so nothing was sent to Switch. Open the dashboard's own address and try again."
SWITCH_DOWN = "Foundry can't reach Switch. Check that it is running, then try again."
SWITCH_TROUBLE = "Switch had a problem with that login. Try again in a moment."
ASK_FOR_BOTH = "Enter your login and your password."
NO_DATA = "Foundry's data can't be read just now. If the desk has never run, start it first. Otherwise try again in a moment."
FORM_EXPIRED = "That form didn't come from this page, so nothing was done. Reload the page and try again."
ERRORS = {
    400: "That wasn't something this page can do.",
    403: "You can't do that here.",
    404: "That page isn't here, or it belongs to someone else.",
    405: "That page doesn't take this.",
}
MOST_STATEMENT = 200
JOB_ACTIONS = ("restart", *DUE_ACTIONS)
JOB_ANSWERS = ("approve", "revise")
MOST_CHOICE = 300

Handler = Callable[..., Response]


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
        # The handlers are plain functions that read SQLite, so they run in the thread pool and not on the event loop.
        if request.method == "POST":
            form = await request.form()
            if not csrf_ok(request, form.get("csrf")):
                raise HTTPException(403, FORM_EXPIRED)
            return await run_in_threadpool(handler, request, user, form)
        return await run_in_threadpool(handler, request, user)

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
        return render(request, "login.html", title="Sign in", status=503, error=SWITCH_DOWN)
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


@signed_in
def overview(request: Request, user: User) -> Response:
    return render(request, "overview.html", user, title="Overview", page="overview", figures=request.app.state.reader.overview(user))


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
