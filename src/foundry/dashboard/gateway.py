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
# Switch Console's test for a field to mask as it is typed, with the other names a secret goes by.
SECRET_FIELD = re.compile(r"token|passw|pwd|passphrase|secret|credential|cookie|bearer|jwt|signing|auth|(^|[_-])key($|[_-])|api[_-]?key|private[_-]?key", re.I)
# All that is read about a connection or a room. Whatever else Switch sends is dropped, so a secret in a reply can't reach a page.
LISTED = ("bridge_id", "bridge_type", "display_name", "status", "attention", "room_count")
ROOMS_LISTED = ("id", "name", "bridge_id")
MOST_DETAIL = 300
# How much of a typed secret, in a row, counts as Switch having quoted it back. Only letters and numbers are compared, whatever their case.
ECHO_WINDOW = 6
# A reply that hides most of a secret and shows its two ends is quoting it too. Four are enough to tell.
ECHO_END = 4
MASK = re.compile(r"\.{2,}|\u2026|\*{2,}|\u2022|x{3,}", re.I)

SWITCH_DOWN = "Foundry can't reach Switch. Check that it is running, then try again."
SIGNED_OUT = "Switch no longer accepts your sign-in. Sign out, then sign in again."
NOT_ALLOWED = "Switch says your login isn't allowed to change connections. A Switch admin can."
TROUBLE = "Switch had a problem with that. Try again in a moment."
NOT_ACCEPTED = "Switch did not accept those details. Check them and enter them again."
GONE = "Switch no longer has that connection."
# A remove it refuses was refused before anything was deleted, and there were no details for anyone to enter.
REMOVE_REFUSED = "Switch would not remove that connection, so nothing was deleted."
# Looking is not changing, so a refusal to show something is not told as a form filled in wrong or a change a login may not make.
READ_NOT_ALLOWED = "Switch says your login isn't allowed to see its connections."
READ_REFUSED = "Switch would not give that list just now. Try again in a moment."
# A write that may have got part of the way. Switch deletes a connection's rooms one by one and then the connection, so nothing is said to be undone or not done.
PART_WAY = "Switch had a problem part-way and may have deleted some rooms. Check its Gateway before you try again."
DELETE_LOST = "Foundry lost touch with Switch part-way, so it may have deleted some rooms. Check its Gateway before you try again."
ADD_TROUBLE = "Switch had a problem with that, and the connection may have been added. Check its Gateway before you try again."
ADD_LOST = "Foundry lost touch with Switch part-way, so the connection may have been added. Check its Gateway before you try again."


class SwitchProblem(Exception):
    """Switch didn't do it. The text is what the page says, and the status is what the page answers with."""

    def __init__(self, status: int, message: str, unsure: bool = False) -> None:
        super().__init__(message)
        # Unsure: the change may have been made, so the page does not offer the same form again.
        self.status, self.message, self.unsure = status, message, unsure


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
    # trust_env off: the login's cookie and a token typed here go to the Switch the dashboard was started for, never to a proxy the environment happens to name.
    return httpx.AsyncClient(base_url=request.app.state.switch_url, transport=request.app.state.transport, cookies=found[1].cookies if found else {}, timeout=timeout, trust_env=False)


def squash(text: str) -> str:
    # Letters and digits in any script, in one case. A secret in Cyrillic or Chinese is as much a secret, and would be nothing if only the ASCII were kept.
    return re.sub(r"[\W_]", "", text.casefold())


def unspaced(text: str) -> str:
    return re.sub(r"\s+", "", text.casefold())


def stretches(secret: str, window: int) -> list[str]:
    return [secret] if len(secret) <= window else [secret[start : start + window] for start in range(len(secret) - window + 1)]


def echoes(text: str, secrets: Sequence[str]) -> bool:
    # Any stretch of a typed secret, however it is cut, cased or spaced, and its two ends when the middle is hidden. A whole copy is the least of it.
    flat, hidden = squash(text), MASK.search(text) is not None
    for typed in secrets:
        # A secret made only of marks has no letters or digits to compare, so it is compared as it was typed. Nothing at all is never a match.
        secret, where = (squash(typed), flat) if squash(typed) else (unspaced(typed), unspaced(text))
        if not secret:
            continue
        if any(part in where for part in stretches(secret, ECHO_WINDOW)):
            return True
        if hidden and len(secret) >= 2 * ECHO_END and (secret[:ECHO_END] in where or secret[-ECHO_END:] in where):
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


def problem_for(answer: httpx.Response, secrets: Sequence[str], missing: str | None, trouble: str, writing: bool, refused: str) -> SwitchProblem:
    code = answer.status_code
    if code == 401:
        return SwitchProblem(401, SIGNED_OUT)
    if code == 403:
        return SwitchProblem(403, NOT_ALLOWED if writing else READ_NOT_ALLOWED)
    if code == 404 and missing:
        return SwitchProblem(404, missing)
    if 400 <= code < 500 and code != 404:
        # Only what a person typed can be wrong in a way they can fix, so a read that is refused is not told that way.
        return SwitchProblem(400, (plain_detail(answer, secrets) or refused) if writing else READ_REFUSED)
    # Anything else, a redirect included, is not a change that worked. After a write it may have got part of the way.
    return SwitchProblem(502, trouble, unsure=writing)


async def ask(
    switch: httpx.AsyncClient, method: str, path: str, secrets: Sequence[str] = (), missing: str | None = None, trouble: str = TROUBLE, lost: str = TROUBLE, refused: str = NOT_ACCEPTED, **options
) -> httpx.Response:
    # Nothing about the request goes in a log or an error, because it may hold a token. Nor does anything Switch said back.
    writing = method != "GET"
    try:
        answer = await switch.request(method, GATEWAY + path, **options)
    except httpx.HTTPError as error:
        logger.warning("Could not reach Switch for %s %s.", method, path)
        # Failing to connect means nothing was sent. Any other failure may have come after Switch began.
        if writing and not isinstance(error, httpx.ConnectError | httpx.ConnectTimeout):
            raise SwitchProblem(502, lost, unsure=True) from None
        raise SwitchProblem(503, SWITCH_DOWN) from None
    if not answer.is_success:
        logger.warning("Switch answered %s to %s %s.", answer.status_code, method, path)
        raise problem_for(answer, secrets, missing, trouble, writing, refused)
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


def masked(schema: dict) -> bool:
    # Switch marks a secret by its format, or as one that can be written and never read back.
    return schema.get("format") == "password" or schema.get("writeOnly") is True


def field_of(key: str, schema: dict, required: bool) -> Field:
    # What Switch sends is Pydantic's JSON schema, where an optional yes/no field is an anyOf and has no type of its own.
    variants = schema.get("anyOf") if isinstance(schema.get("anyOf"), list) else []
    kind = schema.get("type") or next((variant.get("type") for variant in variants if isinstance(variant, dict) and variant.get("type") not in (None, "null")), None)
    boolean = kind == "boolean"
    secret = bool(SECRET_FIELD.search(key)) or any(masked(part) for part in (schema, *(variant for variant in variants if isinstance(variant, dict))))
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


async def add_bridge(switch: httpx.AsyncClient, kind: BridgeType, name: str, config: dict, secrets: Sequence[str]) -> str:
    # The new connection's id, so the dashboard can go straight on to setting a business up on it. Empty if Switch didn't say.
    body = {"bridge_type": kind.key, "display_name": name, "connection_config": config, "set_as_default": False, "channel_creation_enabled": kind.channels}
    answer = await ask(switch, "POST", "/collaborations", secrets, trouble=ADD_TROUBLE, lost=ADD_LOST, json=body)
    try:
        found = answer.json()
    except ValueError:
        return ""
    return str(found.get("bridge_id") or found.get("id") or "") if isinstance(found, dict) else ""


@dataclass(frozen=True)
class Person:
    external_user_id: str
    username: str
    display_name: str


async def linked_on(switch: httpx.AsyncClient, bridge_id: str) -> bool:
    # Whether this login's chat account on the connection is linked and confirmed, which Switch needs before it makes rooms there for it.
    return any(isinstance(item, dict) and item.get("bridge_id") == bridge_id and item.get("verified") for item in await listed(switch, "/auth/me/identities"))


async def find_people(switch: httpx.AsyncClient, bridge_id: str, query: str) -> tuple[list[Person], str]:
    # The chat app's own member list where it has one. Telegram has none, so it is the people who have already written to Foundry, and the note says so.
    answer = await ask(switch, "GET", f"/collaborations/{quote(bridge_id, safe='')}/directory", params={"query": query})
    try:
        found = answer.json()
    except ValueError:
        raise SwitchProblem(502, TROUBLE) from None
    people = [Person(str(item.get("external_user_id")), str(item.get("username") or ""), str(item.get("display_name") or item.get("username") or ""))
              for item in found.get("users", []) if isinstance(item, dict) and item.get("external_user_id")]
    note = str(found.get("note") or "") if found.get("source") == "known" else ""
    return people, note


async def claim(switch: httpx.AsyncClient, bridge_id: str, person: Person) -> tuple[str, str]:
    # The one-time code and where to post it. Posting it from that account is what proves the account is yours.
    answer = await ask(switch, "POST", f"/collaborations/{quote(bridge_id, safe='')}/identities", json={"external_user_id": person.external_user_id, "username": person.username, "expects_confirmation": True})
    try:
        code = (answer.json().get("link_request") or {}).get("code") or {}
    except (ValueError, AttributeError):
        raise SwitchProblem(502, TROUBLE) from None
    return str(code.get("code") or ""), str(code.get("instructions") or "")


async def delete_bridge(switch: httpx.AsyncClient, bridge_id: str) -> None:
    # Quoting leaves dots alone, and an address that ends in .. is a step up from the one meant, so such an id is not a connection that can be asked for.
    if bridge_id in (".", ".."):
        raise SwitchProblem(404, GONE)
    await ask(switch, "DELETE", f"/collaborations/{quote(bridge_id, safe='')}", missing=GONE, trouble=PART_WAY, lost=DELETE_LOST, refused=REMOVE_REFUSED)
