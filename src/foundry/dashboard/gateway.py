"""What the dashboard asks Switch about its connections. It asks as the person who signed in, with the cookie Switch gave them at login, so Switch decides what that person may do and records who did it. Foundry keeps no token of its own. A token typed into the add form goes on to Switch and is not kept, logged or shown."""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from starlette.requests import Request

from foundry.dashboard.auth import find_session

logger = logging.getLogger(__name__)

GATEWAY = "/gateway"
READ_TIMEOUT = 5
# Adding a connection makes Switch check the credentials with the chat app, and removing one deletes its rooms one by one.
WRITE_TIMEOUT = 30
# The test Switch Console uses to mask a field as it is typed.
SECRET_FIELD = re.compile(r"token|password|secret|api[_-]?key|private[_-]?key|credential", re.I)
# All that is read about a connection or a room. Whatever else Switch sends is dropped, so a secret in a reply can't reach a page.
LISTED = ("bridge_id", "bridge_type", "display_name", "status", "attention", "room_count")
ROOMS_LISTED = ("id", "name", "bridge_id")
MOST_DETAIL = 300
# How much of a typed secret, in a row, counts as Switch having quoted it back.
ECHO_WINDOW = 8

SWITCH_DOWN = "Foundry can't reach Switch. Check that it is running, then try again."
SIGNED_OUT = "Switch no longer accepts your sign-in. Sign out, then sign in again."
NOT_ALLOWED = "Switch says your login isn't allowed to change connections. A Switch admin can."
TROUBLE = "Switch had a problem with that. Try again in a moment."
NOT_ACCEPTED = "Switch did not accept those details. Check them and enter them again."
GONE = "Switch no longer has that connection."
PART_WAY = "Switch had a problem part-way and may have deleted some rooms. Check its Gateway before you try again."


class SwitchProblem(Exception):
    """Switch didn't do it. The text is what the page says, and the status is what the page answers with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True)
class Bridge:
    id: str
    type: str
    name: str
    status: str
    attention: str
    # How many rooms Switch says are on it, or None when it doesn't say.
    rooms: int | None


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    bridge_id: str


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    hint: str
    required: bool
    secret: bool
    boolean: bool
    # Only a yes/no field has one: whether its box starts ticked.
    ticked: bool


@dataclass(frozen=True)
class BridgeType:
    key: str
    name: str
    # Whether Switch may make channels on this kind of connection. It refuses a yes for a kind that can't.
    channels: bool
    fields: tuple[Field, ...]


def scrub(item: object, listed: Sequence[str] = LISTED) -> dict:
    # Only plain values under names that are listed, and never a name that looks like a secret.
    if not isinstance(item, dict):
        return {}
    return {key: value for key, value in item.items() if key in listed and not SECRET_FIELD.search(key) and (value is None or isinstance(value, str | int | bool))}


def open_gateway(request: Request, timeout: float) -> httpx.AsyncClient:
    found = find_session(request)
    return httpx.AsyncClient(base_url=request.app.state.switch_url, transport=request.app.state.transport, cookies=found[1].cookies if found else {}, timeout=timeout)


def echoes(text: str, secrets: Sequence[str]) -> bool:
    # Any stretch of a typed secret, so a copy that is quoted, cut short or masked is caught as well as a whole one.
    for secret in secrets:
        if len(secret) < ECHO_WINDOW:
            if secret and secret in text:
                return True
        elif any(secret[start : start + ECHO_WINDOW] in text for start in range(len(secret) - ECHO_WINDOW + 1)):
            return True
    return False


def plain_detail(answer: httpx.Response, secrets: Sequence[str]) -> str | None:
    # Switch's own sentence, when it is one and holds nothing that was typed. A validation error lists its input, so a list is never shown.
    try:
        detail = answer.json().get("detail")
    except (ValueError, AttributeError):
        return None
    if not isinstance(detail, str):
        return None
    detail = " ".join(detail.split())
    return None if not detail or len(detail) > MOST_DETAIL or echoes(detail, secrets) else detail


def problem_for(answer: httpx.Response, secrets: Sequence[str], missing: str | None, trouble: str) -> SwitchProblem:
    code = answer.status_code
    if code == 401:
        return SwitchProblem(401, SIGNED_OUT)
    if code == 403:
        return SwitchProblem(403, NOT_ALLOWED)
    if code == 404 and missing:
        return SwitchProblem(404, missing)
    if 400 <= code < 500 and code != 404:
        return SwitchProblem(400, plain_detail(answer, secrets) or NOT_ACCEPTED)
    return SwitchProblem(502, trouble)


async def ask(switch: httpx.AsyncClient, method: str, path: str, secrets: Sequence[str] = (), missing: str | None = None, trouble: str = TROUBLE, **options) -> httpx.Response:
    # Nothing about the request goes in a log or an error, because it may hold a token.
    try:
        answer = await switch.request(method, GATEWAY + path, **options)
    except httpx.HTTPError:
        logger.warning("Could not reach Switch for %s %s.", method, path)
        raise SwitchProblem(503, SWITCH_DOWN) from None
    if answer.is_error:
        logger.warning("Switch answered %s to %s %s.", answer.status_code, method, path)
        raise problem_for(answer, secrets, missing, trouble)
    return answer


async def listed(switch: httpx.AsyncClient, path: str, **options) -> list:
    try:
        found = (await ask(switch, "GET", path, **options)).json()
    except ValueError:
        raise SwitchProblem(502, TROUBLE) from None
    if not isinstance(found, list):
        raise SwitchProblem(502, TROUBLE)
    return found


async def bridges(switch: httpx.AsyncClient) -> list[Bridge]:
    found = []
    for item in map(scrub, await listed(switch, "/collaborations")):
        if item.get("bridge_id"):
            count = item.get("room_count")
            found.append(Bridge(str(item["bridge_id"]), str(item.get("bridge_type") or ""), str(item.get("display_name") or item["bridge_id"]), str(item.get("status") or ""), str(item.get("attention") or ""), count if isinstance(count, int) else None))
    return found


async def rooms(switch: httpx.AsyncClient) -> list[Room]:
    # Archived rooms too, because removing a connection deletes those as well.
    found = []
    for item in (scrub(item, ROOMS_LISTED) for item in await listed(switch, "/rooms", params={"include_archived": "true"})):
        if item.get("id") and item.get("bridge_id"):
            found.append(Room(str(item["id"]), str(item.get("name") or item["id"]), str(item["bridge_id"])))
    return found


def humanize(key: str) -> str:
    return key.replace("_", " ").capitalize()


def field_of(key: str, schema: dict, required: bool) -> Field:
    # What Switch sends is Pydantic's JSON schema, where an optional yes/no field is an anyOf and has no type of its own.
    variants = schema.get("anyOf") if isinstance(schema.get("anyOf"), list) else []
    kind = schema.get("type") or next((variant.get("type") for variant in variants if isinstance(variant, dict) and variant.get("type") not in (None, "null")), None)
    boolean = kind == "boolean"
    secret = schema.get("format") == "password" or bool(SECRET_FIELD.search(key))
    return Field(key, str(schema.get("title") or humanize(key)), str(schema.get("description") or ""), required, secret, boolean, boolean and schema.get("default") is True)


async def bridge_types(switch: httpx.AsyncClient) -> list[BridgeType]:
    found = []
    for item in await listed(switch, "/collaborations/types"):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        schema = item.get("config_schema") if isinstance(item.get("config_schema"), dict) else {}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = set(schema.get("required") or [])
        fields = tuple(field_of(key, field, key in required) for key, field in properties.items() if isinstance(field, dict))
        found.append(BridgeType(str(item["key"]), str(item.get("display_name") or item["key"]), item.get("channel_creation_supported", True) is not False, fields))
    return found


def configuration(kind: BridgeType, form: Mapping) -> tuple[dict, list[str], list[str]]:
    # What was typed, as the fields of this kind of connection. Names the kind doesn't have are not read. Also the labels left empty, and the secrets typed.
    config, missing, secrets = {}, [], []
    for field in kind.fields:
        name = f"field.{field.key}"
        if field.boolean:
            config[field.key] = name in form
            continue
        typed = form.get(name)
        value = typed.strip() if isinstance(typed, str) else ""
        if value:
            config[field.key] = value
            if field.secret:
                secrets.append(value)
        elif field.required:
            missing.append(field.label)
    return config, missing, secrets


async def add_bridge(switch: httpx.AsyncClient, kind: BridgeType, name: str, config: dict, secrets: Sequence[str]) -> None:
    body = {"bridge_type": kind.key, "display_name": name, "connection_config": config, "set_as_default": False, "channel_creation_enabled": kind.channels}
    await ask(switch, "POST", "/collaborations", secrets, json=body)


async def delete_bridge(switch: httpx.AsyncClient, bridge_id: str) -> None:
    await ask(switch, "DELETE", f"/collaborations/{quote(bridge_id, safe='')}", missing=GONE, trouble=PART_WAY)
