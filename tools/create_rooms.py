"""Creates one client's or department's rooms from the template, gives the makers their tools and saves the room ids in .env.

An agency client is made agents of its own, whose names end with its name. A department shares one set.

uv run --env-file .env python tools/create_rooms.py agency lalten lalten-cafe

Switch puts whoever signs in here in each room it makes, so the rooms go on chat apps that account has linked. To choose the app for outside people, add --outside-bridge Mattermost.
"""

import argparse
import os
from pathlib import Path

import httpx
import yaml
from foundry.brand import load_brand_dir
from foundry.pack import load_pack
from foundry.stickers import mode_for
from register_desk import ENV_FILE, local_url, save
from setup_makers import main as setup_makers

REPO = Path(__file__).resolve().parent.parent
REVIEWER = "foundry-reviewer"
SLOTS = {"brief": "foundry-brief", "deck": "foundry-deck", "visual": "foundry-visual", "reviewer": REVIEWER}
NEW_REVIEWER = "Making {name} on the template's own reviewer, because FOUNDRY_REVIEWER_PROVIDER is empty. An agent's provider is fixed once it is made, so set it in .env first if that is not the one you want."
# Switch refuses a room on an app where its maker has no linked account, because it would make a private channel they can't enter. Foundry says so first, because it can say what to pass.
NOT_ONE_APP = "{wanted} is not one chat app connected to Switch, so no rooms were made. Pass --outside-bridge with one of these: {names}."
NOT_LINKED = "Your Switch account has no linked account on {app}, and Switch won't make a room its maker can't enter, so no rooms were made. Link it under Identities in Switch, or pass --outside-bridge {linked}."
NO_LINK = "Your Switch account has no linked account on any connected chat app ({names}), and Switch won't make a room its maker can't enter, so no rooms were made. Link one under Identities in Switch, then run this again."


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


def chat_apps(bridges: list[dict], linked: set[str], brand_dir: Path, wanted: str) -> dict[str, str]:
    """The template's inputs for which chat app the rooms go on. With no app connected there is nothing to choose, and Switch answers for that."""
    # In the order Switch means by $first.
    apps = sorted((bridge for bridge in bridges if bridge["status"] == "active"), key=lambda app: (not app["is_default"], app["display_name"]))
    if not apps:
        return {}
    reachable = [app for app in apps if app["bridge_id"] in linked]
    if not reachable:
        raise SystemExit(NO_LINK.format(names=", ".join(app["display_name"] for app in apps)))
    if wanted:
        outside = _app_named(apps, wanted)
        if outside not in reachable:
            raise SystemExit(NOT_LINKED.format(app=outside["display_name"], linked=" or ".join(app["display_name"] for app in reachable)))
    else:
        # The template's order, among the apps this account can be put in. The people a pack names and a demo's scripted people are on Mattermost, so Telegram would leave them out of the room that asks.
        kinds = ("mattermost",) if names_people_on_mattermost(brand_dir) else ("telegram", "mattermost")
        outside = next(filter(None, (_of_kind(reachable, kind) for kind in kinds)), reachable[0])
    return {"outside_bridge": outside["display_name"], "bridge": (_of_kind(reachable, "mattermost") or outside)["display_name"]}


def main(mode: str, name: str, slug: str, outside_bridge: str = "") -> None:
    url = local_url("SWITCH_URL", "http://127.0.0.1:8000")
    brand_dir = REPO / "brands" / slug
    ending = agents_ending(mode, name)
    kit = (brand_dir / "kit.md").read_text(encoding="utf-8")
    tokens = yaml.safe_load(kit.split("---")[1])
    guide = (REPO / "templates" / "design-guide.md").read_text(encoding="utf-8")
    with httpx.Client(base_url=f"{url}/gateway", timeout=120, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        online = next((machine for machine in gateway.get("/management/controllers").json() if machine["state"] == "online"), None)
        if online is None:
            raise SystemExit("No agent controller is online, so no rooms were made. Start it as in step 2 of the README, then run this again.")
        bridges = gateway.get("/collaborations").json()
        linked = gateway.get("/auth/me/identities").raise_for_status().json() if bridges else []
        apps = chat_apps(bridges, {identity["bridge_id"] for identity in linked}, brand_dir, outside_bridge)
        # Switch puts every agent in a chat it hasn't seen, and each would say hello.
        for bridge in bridges:
            gateway.patch(f"/collaborations/{bridge['bridge_id']}", json={"agent_greetings_enabled": False}).raise_for_status()
        existing = {agent["name"] for agent in gateway.get("/management/agents").json()}
        if REVIEWER + ending not in existing and not os.environ.get("FOUNDRY_REVIEWER_PROVIDER"):
            print(NEW_REVIEWER.format(name=REVIEWER + ending))
        answer = gateway.post("/rooms/from-template-document", json={
            "template": (REPO / "templates" / "foundry.template.yaml").read_text(encoding="utf-8"),
            "template_name": "foundry",
            "inputs": {
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
            },
            # Only this client's own agents fill its slots, so a rerun reuses them, and another client's, or the shared ones, are never taken.
            "filled": {slot: agent + ending for slot, agent in SLOTS.items() if agent + ending in existing},
        })
        if answer.is_error:
            raise SystemExit(f"Switch refused the template: {answer.text}")
    # A client's own makers are pinned to its brand folder and told their own folder. Shared makers serve many businesses, so they are not.
    setup_makers(online["status"]["machine"]["workspaces_dir"], ending, str(brand_dir) if ending else "")
    rooms = {room["room_name"]: room["room_id"] for room in answer.json()["room"]["rooms"]}
    save_rooms(mode, name, slug, rooms)
    print(f"Created {', '.join(rooms)} and saved their ids in {ENV_FILE}")


def save_rooms(mode: str, name: str, slug: str, rooms: dict[str, str]) -> None:
    ending = agents_ending(mode, name)
    inside = (rooms[f"{name}-studio"], rooms[f"{name}-review"]) if mode == "agency" else (rooms[f"{name}-projects"],) * 2
    # The desk is told the ending, so it asks this client's agents by name.
    entry = f"{rooms[name]}:{inside[0]}:{inside[1]}" + (f":{ending}" if ending else "")
    current = os.environ.get("FOUNDRY_ROOMS", "")
    packs = os.environ.get("FOUNDRY_PACKS", "")
    pack = f"{rooms[name]}:{slug}"
    save({"FOUNDRY_ROOMS": f"{current},{entry}" if current else entry, "FOUNDRY_PACKS": f"{packs},{pack}" if packs else pack})


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
