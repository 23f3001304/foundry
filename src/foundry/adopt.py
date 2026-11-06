"""Follows a chat the bot was added to in a business that is set up already, so nobody makes its rooms by hand.

Switch makes a room as soon as the bot joins a channel. When that room is on the same chat app and workspace as exactly one business's rooms,
the desk joins it and writes it into .env as another outside room of that business, with the business's studio, review room and brand.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

# Foundry's own channels, such as the Slack home it posts approvals to, are never a business's room.
OWN_CHANNEL = "foundry-"


def workspace(room: dict) -> tuple[str, str]:
    # One chat app can hold several workspaces. Slack names its own in the channel's address; elsewhere the app itself is the workspace.
    team = parse_qs(urlparse(room.get("external_channel_url") or "").query).get("team", [""])[0]
    return room.get("bridge_id") or "", team


def entries(text: str) -> list[list[str]]:
    return [entry.split(":") for entry in text.split(",") if entry.strip()]


def packs(text: str) -> dict[str, str]:
    return dict(entry.split(":", 1) for entry in text.split(",") if ":" in entry)


def new_rooms(rooms: list[dict], followed: str, brands: str, env_text: str) -> list[tuple[str, str, str]]:
    """Each room to follow, as its FOUNDRY_ROOMS entry, its FOUNDRY_PACKS entry and its name."""
    by_id = {room["id"]: room for room in rooms}
    places: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    brand_of = packs(brands)
    for entry in entries(followed):
        if (room := by_id.get(entry[0])) is not None:
            places.setdefault(workspace(room), set()).add((*entry[1:], brand_of.get(entry[0], "")))
    found = []
    for room in rooms:
        if room.get("archived") or room.get("group_id") or room["id"] in env_text or room.get("name", "").startswith(OWN_CHANNEL):
            continue
        business = places.get(workspace(room), set())
        # Two businesses on one workspace leave it unclear whose room this is, so it waits for someone to set it up.
        if len(business) != 1:
            continue
        *rest, brand = next(iter(business))
        found.append((":".join([room["id"], *rest]), f"{room['id']}:{brand}" if brand else "", room.get("name", room["id"])))
    return found


def write_env(path: Path, changes: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for key, value in changes.items():
        at = next((i for i, line in enumerate(lines) if line.partition("=")[0].strip() == key), None)
        if at is None:
            lines.append(f"{key}={value}")
        else:
            lines[at] = f"{key}={value}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def adopt(env_file: Path, client: Callable[[], httpx.Client] | None = None) -> list[str]:
    """Joins and saves every new room it can place, and returns their names. It needs the Switch account in .env, and does nothing without it."""
    email, password, desk = os.environ.get("SWITCH_EMAIL"), os.environ.get("SWITCH_PASSWORD"), os.environ.get("FOUNDRY_DESK_ID")
    if not (email and password and desk and env_file.is_file()):
        return []
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    with (client or (lambda: httpx.Client(base_url=f"{url}/gateway", timeout=60, trust_env=False)))() as gateway:
        gateway.post("/auth/login", json={"email": email, "password": password}).raise_for_status()
        listed = gateway.get("/rooms", params={"include_archived": "true"}).raise_for_status().json()
        rooms = listed.get("items", []) if isinstance(listed, dict) else listed
        env_text = env_file.read_text(encoding="utf-8")
        current = {key.strip(): value.strip() for key, _, value in (line.partition("=") for line in env_text.splitlines())}
        followed, brands = current.get("FOUNDRY_ROOMS", ""), current.get("FOUNDRY_PACKS", "")
        adopted = []
        for entry, pack, name in new_rooms(rooms, followed, brands, env_text):
            joined = gateway.post(f"/rooms/{entry.split(':')[0]}/agents", json={"agent_ids": [desk]})
            if joined.is_error:
                logger.warning("Could not join %s, so it is not followed: %s", name, joined.text[:200])
                continue
            followed = f"{followed},{entry}" if followed else entry
            brands = f"{brands},{pack}" if brands and pack else (pack or brands)
            adopted.append(name)
    if adopted:
        write_env(env_file, {"FOUNDRY_ROOMS": followed, "FOUNDRY_PACKS": brands})
        logger.info("Foundry was added to %s, so the desk follows it now.", ", ".join(adopted))
    return adopted
