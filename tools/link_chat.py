"""Links a chat that opened its own room, such as someone writing to a WhatsApp number, to a client's rooms, and saves it in .env.

uv run --env-file .env python tools/link_chat.py "SiteEngineerA_15550001111" green-valley
"""

import os
import sys

import httpx
from register_desk import ENV_FILE, save


def find_room(listed: list[dict], wanted: str) -> dict:
    matches = [room for room in listed if wanted in (room["id"], room["name"])]
    if len(matches) != 1:
        problem = "No room is called" if not matches else "More than one room is called"
        raise SystemExit(f"{problem} {wanted}. Rooms: {', '.join(sorted(room['name'] for room in listed))}")
    return matches[0]


def linked_settings(rooms: str, packs: str, chat: str, client: str) -> dict[str, str]:
    workrooms = dict(entry.split(":", 1) for entry in rooms.split(",") if entry)
    if chat in workrooms:
        raise SystemExit("That chat is already linked to a client.")
    if client not in workrooms:
        raise SystemExit("That room is not a client's outside room in FOUNDRY_ROOMS. Create it with tools/create_rooms.py first.")
    values = {"FOUNDRY_ROOMS": f"{rooms},{chat}:{workrooms[client]}"}
    slug = dict(entry.split(":") for entry in packs.split(",") if entry).get(client)
    if slug:
        values["FOUNDRY_PACKS"] = f"{packs},{chat}:{slug}"
    return values


def main(chat_name: str, client_name: str) -> None:
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=30) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        listed = gateway.get("/rooms").json()
        chat, client = find_room(listed, chat_name), find_room(listed, client_name)
        values = linked_settings(os.environ.get("FOUNDRY_ROOMS", ""), os.environ.get("FOUNDRY_PACKS", ""), chat["id"], client["id"])
        added = gateway.post(f"/rooms/{chat['id']}/agents", json={"agent_ids": [os.environ["FOUNDRY_DESK_ID"]]})
        if added.is_error:
            raise SystemExit(f"Switch would not add the desk to {chat_name}: {added.text}")
    save(values)
    print(f"Linked {chat_name} to {client_name} and saved it in {ENV_FILE}. Restart the desk so it follows the new room.")


if __name__ == "__main__":
    main(*sys.argv[1:])
