"""Creates one client's or department's rooms from the template, gives the makers their tools and saves the room ids in .env.

An agency client is made agents of its own, whose names end with its name. A department shares one set.

uv run --env-file .env python tools/create_rooms.py agency lalten lalten-cafe

Switch puts whoever signs in here in each room it makes, so the rooms go on chat apps that account has linked. To choose the app for outside people, add --outside-bridge Mattermost.
"""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import httpx
import yaml
from foundry.brand import load_brand_dir
from foundry.pack import load_pack
from foundry.stickers import mode_for
from register_desk import ENV_FILE, local_url, save
from setup_makers import main as setup_makers

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "templates" / "foundry.template.yaml"
REVIEWER = "foundry-reviewer"
SLOTS = {"brief": "foundry-brief", "deck": "foundry-deck", "visual": "foundry-visual", "reviewer": REVIEWER}
NEW_REVIEWER = "Making {name} on the template's own reviewer, because FOUNDRY_REVIEWER_PROVIDER is empty. An agent's provider is fixed once it is made, so set it in .env first if that is not the one you want."
# Switch refuses a room on an app where its maker has no linked account, because it would make a private channel they can't enter. Foundry says so first, because it can say what to pass.
NOT_ONE_APP = "{wanted} is not one chat app connected to Switch, so no rooms were made. Pass --outside-bridge with one of these: {names}."
NOT_LINKED = "Your Switch account has no linked account on {app}, and Switch won't make a room its maker can't enter, so no rooms were made. Link it under Identities in Switch, or pass --outside-bridge {linked}."
NO_LINK = "Your Switch account has no linked account on any connected chat app ({names}), and Switch won't make a room its maker can't enter, so no rooms were made. Link one under Identities in Switch, then run this again."
NO_APP_RUNNING = "You chose {wanted}, and no chat app is connected to Switch, so no rooms were made. Connect it to Switch, then run this again."
# The people a pack names and a demo's scripted people are on Mattermost, so any other app would leave them out of the room that asks. A rerun doesn't repair that, because a room that exists is not made again.
PEOPLE_ON_MATTERMOST = "The pack for {brand} names its people on Mattermost, {why}, so they would be left out of the room that asks and no rooms were made. {fix}, or pass --outside-bridge {linked} to make the rooms there without them."
NOT_CONNECTED = ("and Mattermost isn't connected to Switch", "Connect Mattermost to Switch")
NOT_LINKED_THERE = ("and your Switch account has no linked account there", "Link it under Identities in Switch")
# Switch makes a group's rooms one by one and rolls nothing back. A room it couldn't make is in its answer's errors, and the rest exist.
ROOMS_NOT_ALL_MADE = "Switch could not make every room for {name}. {why} What was made is saved in {env}, and the desk won't use {name} until the rest exist. Run this same command again to make only those."
MADE_BUT = "Made {rooms} and saved their ids in {env}, but not everything went in. {why}"
ROOM_FAILED = "{room} was not made: {error}."
NOT_THERE = "It gave no reason, and these are missing: {rooms}."
OWNER_LEFT_OUT = "You are not in {room}: Switch could not add {who}, because {error}. Add that account to the room in Switch Console."
NOT_ATTACHED = "{room} has no {kind} {what}: {error}."
LINK_FAILED = "{first} is not linked to {second}: {error}. The rooms work without it, and you can link them in Switch Console."
NOT_FILED = "{room} is not in its group in Switch: {error}."
# What a run left half made: name:group:room=id:room=id, comma-separated. It isn't in FOUNDRY_ROOMS, because the desk won't start with an entry it can't use, and that would stop every other client.
UNFINISHED = "FOUNDRY_ROOMS_UNFINISHED"


def reviewer_inputs() -> dict[str, str]:
    # The template's model only exists on OpenCode, so another provider starts on its own default.
    provider, model = os.environ.get("FOUNDRY_REVIEWER_PROVIDER"), os.environ.get("FOUNDRY_REVIEWER_MODEL")
    inputs = {"reviewer_provider": provider, "reviewer_model": ""} if provider else {}
    return inputs | {"reviewer_model": model} if model else inputs


def template_approver(brand_dir: Path) -> str:
    return load_pack(brand_dir).approver or os.environ.get("FOUNDRY_APPROVER", "")


def agents_ending(mode: str, name: str) -> str:
    # Each agency client gets agents of its own, whose names end with its name, so no client's work or folder is ever open to another's makers.
    # An internal company or department is one business, so its rooms share one set.
    return f"-{name}" if mode == "agency" else ""


def names_people_on_mattermost(brand_dir: Path) -> bool:
    pack = brand_dir / "pack.md"
    return pack.is_file() and "{bridge}" in pack.read_text(encoding="utf-8")


def _of_kind(apps: list[dict], kind: str) -> dict | None:
    return next((app for app in apps if app["bridge_type"] == kind), None)


def _app_named(apps: list[dict], wanted: str) -> dict:
    # Switch knows an app by its display name. A person may write that, or the kind of app it is.
    plain = wanted.strip().casefold()
    found = [app for app in apps if app["display_name"].casefold() == plain] or [app for app in apps if app["bridge_type"].casefold() == plain]
    if len(found) != 1:
        raise SystemExit(NOT_ONE_APP.format(wanted=wanted.strip(), names=", ".join(app["display_name"] for app in apps)))
    return found[0]


def _people_on_mattermost(apps: list[dict], reachable: list[dict], brand_dir: Path) -> dict:
    found = _of_kind(reachable, "mattermost")
    if found is None:
        why, fix = NOT_LINKED_THERE if _of_kind(apps, "mattermost") else NOT_CONNECTED
        raise SystemExit(PEOPLE_ON_MATTERMOST.format(brand=brand_dir.name, why=why, fix=fix, linked=" or ".join(app["display_name"] for app in reachable)))
    return found


def own_accounts(identities: list[dict]) -> dict[str, str]:
    # The name the signed-in account goes by on each chat app it has linked. Switch takes the first it has on an app, and so does this. A name that means nothing is no link.
    accounts: dict[str, str] = {}
    for identity in identities:
        if identity.get("external_username"):
            accounts.setdefault(identity["bridge_id"], identity["external_username"])
    return accounts


def chat_apps(bridges: list[dict], accounts: dict[str, str], brand_dir: Path, wanted: str) -> dict[str, str]:
    """The template's inputs for which chat app the rooms go on and who to add to the inside rooms. With no app connected there is nothing to choose, and Switch answers for that."""
    wanted = wanted.strip()
    # In the order Switch means by $first.
    apps = sorted((bridge for bridge in bridges if bridge["status"] == "active"), key=lambda app: (not app["is_default"], app["display_name"]))
    if not apps:
        if wanted:
            raise SystemExit(NO_APP_RUNNING.format(wanted=wanted))
        return {}
    reachable = [app for app in apps if app["bridge_id"] in accounts]
    if not reachable:
        raise SystemExit(NO_LINK.format(names=", ".join(app["display_name"] for app in apps)))
    if wanted:
        outside = _app_named(apps, wanted)
        if outside not in reachable:
            raise SystemExit(NOT_LINKED.format(app=outside["display_name"], linked=" or ".join(app["display_name"] for app in reachable)))
    elif names_people_on_mattermost(brand_dir):
        outside = _people_on_mattermost(apps, reachable, brand_dir)
    else:
        # The template's order, among the apps this account can be put in.
        outside = next(filter(None, (_of_kind(reachable, kind) for kind in ("telegram", "mattermost"))), reachable[0])
    inside = _of_kind(reachable, "mattermost") or outside
    # Switch has one $creator, the name on the first room's app, and it looks a name up on each room's own app. So the inside rooms are told the owner's name on their app, and a stranger who holds the other app's name there is never asked for.
    return {"outside_bridge": outside["display_name"], "bridge": inside["display_name"], "inside_owner": accounts[inside["bridge_id"]]}


class Made(NamedTuple):
    """What Switch said it did: the rooms it made, by name, and what it couldn't do, each as a sentence."""

    rooms: dict[str, str]
    group: str = ""
    not_made: tuple[str, ...] = ()
    trouble: tuple[str, ...] = ()


def what_was_made(answer: dict) -> Made:
    # A template with a group answers with its rooms and errors, and one room answers as itself. rooms_yaml.GroupProvisionResult and ProvisionResult.
    rooms = answer.get("rooms", [answer])
    trouble = [
        OWNER_LEFT_OUT.format(room=room["room_name"], who=failed.get("id"), error=failed.get("error")) if failed.get("kind") == "user" else NOT_ATTACHED.format(room=room["room_name"], kind=failed.get("kind"), what=failed.get("id"), error=failed.get("error"))
        for room in rooms
        for failed in room.get("failed_attachments", [])
    ]
    errors = answer.get("errors", [])
    not_made = [ROOM_FAILED.format(room=error["room_name"], error=str(error.get("error")).rstrip(".")) for error in errors if "room_name" in error]
    # A link fails on its own only when both rooms are there. With a room missing, the room's own failure says it, and finishing that room makes the link.
    missing = {error["room_name"] for error in errors if "room_name" in error}
    trouble += [LINK_FAILED.format(first=error.get("from"), second=error.get("to"), error=str(error.get("error")).rstrip(".")) for error in errors if "room_name" not in error and not {error.get("from"), error.get("to")} & missing]
    return Made({room["room_name"]: room["room_id"] for room in rooms}, answer.get("group_id", ""), tuple(not_made), tuple(trouble))


def _resources(template: str) -> dict[str, dict]:
    return yaml.safe_load(template)["resources"]


def _named(spec: dict, name: str) -> str:
    return spec["name"].replace("{client_or_department}", name)


def _in_mode(spec: dict, mode: str) -> bool:
    return spec.get("if") == f"{{org_mode}} == {mode}"


def rooms_of(template: str, mode: str, name: str) -> list[str]:
    return [_named(spec, name) for spec in _resources(template).values() if spec["type"] == "room" and _in_mode(spec, mode)]


def one_room_of(template: str, mode: str, name: str, room: str) -> str:
    # The template with its agents and one room, in no group. Switch refuses a group's name a second time, and it would make the rooms that exist again, because a room's name isn't unique.
    document = yaml.safe_load(template)
    document["resources"] = {key: spec for key, spec in document["resources"].items() if spec["type"] == "agent" or (spec["type"] == "room" and _in_mode(spec, mode) and _named(spec, name) == room)}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _links_of(template: str, mode: str, name: str) -> list[tuple[str, str, str]]:
    resources = _resources(template)
    links = (link for spec in resources.values() if spec["type"] == "group" and _in_mode(spec, mode) for link in spec.get("links", []))
    return [(_named(resources[link["from"]], name), _named(resources[link["to"]], name), link["label"]) for link in links]


def _make_the_rest(gateway: httpx.Client, run: Callable[[str], httpx.Response], template: str, mode: str, name: str, group: str, made: dict[str, str]) -> Made:
    # A rerun of a business left half made: only the rooms missing, one at a time, filed under the group the first run made and linked as the template links them.
    rooms, not_made, trouble = {}, [], []
    for room in rooms_of(template, mode, name):
        if room in made:
            continue
        answer = run(one_room_of(template, mode, name, room))
        if answer.is_error:
            not_made.append(ROOM_FAILED.format(room=room, error=answer.text))
            continue
        one = what_was_made(answer.json()["room"])
        rooms |= one.rooms
        trouble += one.trouble
        for made_id in one.rooms.values():
            filed = gateway.put(f"/rooms/{made_id}/group", json={"group_id": group})
            if filed.is_error:
                trouble.append(NOT_FILED.format(room=room, error=filed.text))
    every = made | rooms
    for first, second, label in _links_of(template, mode, name):
        if first in every and second in every and (first in rooms or second in rooms):
            linked = gateway.post(f"/rooms/{every[first]}/linked-rooms", json={"target_room_id": every[second], "label": label})
            if linked.is_error:
                trouble.append(LINK_FAILED.format(first=first, second=second, error=linked.text))
    return Made(rooms, group, tuple(not_made), tuple(trouble))


def unfinished_rooms() -> dict[str, tuple[str, dict[str, str]]]:
    found = {}
    for entry in filter(None, os.environ.get(UNFINISHED, "").split(",")):
        name, group, *rooms = entry.split(":")
        found[name] = (group, dict(room.split("=", 1) for room in rooms))
    return found


def _unfinished_text(records: dict[str, tuple[str, dict[str, str]]]) -> str:
    return ",".join(":".join([name, group, *(f"{room}={room_id}" for room, room_id in rooms.items())]) for name, (group, rooms) in records.items())


def main(mode: str, name: str, slug: str, outside_bridge: str = "") -> None:
    url = local_url("SWITCH_URL", "http://127.0.0.1:8000")
    brand_dir = REPO / "brands" / slug
    ending = agents_ending(mode, name)
    kit = (brand_dir / "kit.md").read_text(encoding="utf-8")
    tokens = yaml.safe_load(kit.split("---")[1])
    guide = (REPO / "templates" / "design-guide.md").read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    with httpx.Client(base_url=f"{url}/gateway", timeout=120, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        online = next((machine for machine in gateway.get("/management/controllers").json() if machine["state"] == "online"), None)
        if online is None:
            raise SystemExit("No agent controller is online, so no rooms were made. Start it as in step 2 of the README, then run this again.")
        bridges = gateway.get("/collaborations").json()
        linked = gateway.get("/auth/me/identities").raise_for_status().json() if bridges else []
        apps = chat_apps(bridges, own_accounts(linked), brand_dir, outside_bridge)
        # Switch puts every agent in a chat it hasn't seen, and each would say hello.
        for bridge in bridges:
            gateway.patch(f"/collaborations/{bridge['bridge_id']}", json={"agent_greetings_enabled": False}).raise_for_status()
        existing = {agent["name"] for agent in gateway.get("/management/agents").json()}
        if REVIEWER + ending not in existing and not os.environ.get("FOUNDRY_REVIEWER_PROVIDER"):
            print(NEW_REVIEWER.format(name=REVIEWER + ending))
        inputs = {
            "org_mode": mode,
            "client_or_department": name,
            "business_type": tokens["business_type"],
            "audience": tokens["audience"],
            "tone": tokens["voice"],
            "brand_kit": kit,
            "design_guide": guide,
            "brand_dir": str(brand_dir),
            "approver": template_approver(brand_dir),
            "sticker_mode": mode_for(load_brand_dir(brand_dir), os.environ.get("FOUNDRY_STICKER_MODE", "subtle")),
            "agent_suffix": ending,
            **reviewer_inputs(),
            **apps,
        }

        def run(document: str) -> httpx.Response:
            there = {agent["name"] for agent in gateway.get("/management/agents").json()}
            return gateway.post("/rooms/from-template-document", json={
                "template": document,
                "template_name": "foundry",
                "inputs": inputs,
                # Only this client's own agents fill its slots, so a rerun reuses them, and another client's, or the shared ones, are never taken.
                "filled": {slot: agent + ending for slot, agent in SLOTS.items() if agent + ending in there},
            })

        group, earlier = unfinished_rooms().get(name, ("", {}))
        if name in unfinished_rooms():
            # A room deleted since, or a stack wiped since, is made again, and its dead id is never saved.
            there = {room["id"] for room in gateway.get("/rooms").json()}
            earlier = {room: room_id for room, room_id in earlier.items() if room_id in there}
            made = _make_the_rest(gateway, run, template, mode, name, group, earlier)
        else:
            answer = run(template)
            if answer.is_error:
                raise SystemExit(f"Switch refused the template: {answer.text}")
            made = what_was_made(answer.json()["room"])
    rooms = earlier | made.rooms
    missing = [room for room in rooms_of(template, mode, name) if room not in rooms]
    whole = not missing
    # Saved before anything else can stop this, because .env is how a rerun knows these rooms are there.
    if whole:
        save_rooms(mode, name, slug, rooms)
    else:
        save({UNFINISHED: _unfinished_text(unfinished_rooms() | {name: (made.group or group, rooms)})})
    # A client's own makers are pinned to its brand folder and told their own folder. Shared makers serve many businesses, so they are not.
    setup_makers(online["status"]["machine"]["workspaces_dir"], ending, str(brand_dir) if ending else "")
    if not whole:
        raise SystemExit(ROOMS_NOT_ALL_MADE.format(name=name, why=" ".join(made.not_made) or NOT_THERE.format(rooms=", ".join(missing)), env=ENV_FILE))
    if made.trouble:
        raise SystemExit(MADE_BUT.format(rooms=", ".join(rooms), env=ENV_FILE, why=" ".join(made.trouble)))
    print(f"Created {', '.join(rooms)} and saved their ids in {ENV_FILE}")


def save_rooms(mode: str, name: str, slug: str, rooms: dict[str, str]) -> None:
    ending = agents_ending(mode, name)
    inside = (rooms[f"{name}-studio"], rooms[f"{name}-review"]) if mode == "agency" else (rooms[f"{name}-projects"],) * 2
    # The desk is told the ending, so it asks this client's agents by name.
    entry = f"{rooms[name]}:{inside[0]}:{inside[1]}" + (f":{ending}" if ending else "")
    current = os.environ.get("FOUNDRY_ROOMS", "")
    packs = os.environ.get("FOUNDRY_PACKS", "")
    pack = f"{rooms[name]}:{slug}"
    values = {"FOUNDRY_ROOMS": f"{current},{entry}" if current else entry, "FOUNDRY_PACKS": f"{packs},{pack}" if packs else pack}
    # The whole set is saved, so nothing of it is left to finish.
    unfinished = unfinished_rooms()
    if name in unfinished:
        del unfinished[name]
        values[UNFINISHED] = _unfinished_text(unfinished)
    save(values)


def remember_rooms(seed: tuple[tuple[str, str, str], ...], rooms: dict[str, str]) -> None:
    # Puts in .env any room Switch has that .env doesn't name, as a run stopped just after Switch made it leaves. A room whose set is only partly there is left for Switch to say so.
    named = os.environ.get("FOUNDRY_ROOMS", "")
    for mode, name, slug in seed:
        if name in rooms and rooms[name] not in named:
            inside = (f"{name}-studio", f"{name}-review") if mode == "agency" else (f"{name}-projects",)
            if all(room in rooms for room in inside):
                save_rooms(mode, name, slug, rooms)
                named = os.environ.get("FOUNDRY_ROOMS", "")


def command() -> None:
    parser = argparse.ArgumentParser(description="Creates one client's or department's rooms.")
    parser.add_argument("mode", choices=["agency", "internal"])
    parser.add_argument("name")
    parser.add_argument("brand_folder")
    parser.add_argument("--outside-bridge", default="", help="The connected chat app for the room outside people use, by its name in Switch or its kind. Left out, it is one your account is linked on.")
    given = parser.parse_args()
    main(given.mode, given.name, given.brand_folder, given.outside_bridge)


if __name__ == "__main__":
    command()
