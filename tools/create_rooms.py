"""Creates one client's or department's rooms from the template, gives the makers their tools and saves the room ids in .env.

uv run --env-file .env python tools/create_rooms.py agency lalten lalten-cafe
"""

import os
import sys
from pathlib import Path

import httpx
import yaml
from foundry.pack import load_pack
from register_desk import ENV_FILE, save
from setup_makers import main as setup_makers

REPO = Path(__file__).resolve().parent.parent
SLOTS = {"brief": "foundry-brief", "deck": "foundry-deck", "visual": "foundry-visual", "reviewer": "foundry-reviewer"}


def reviewer_inputs() -> dict[str, str]:
    # The template's model only exists on OpenCode, so another provider starts on its own default.
    provider, model = os.environ.get("FOUNDRY_REVIEWER_PROVIDER"), os.environ.get("FOUNDRY_REVIEWER_MODEL")
    inputs = {"reviewer_provider": provider, "reviewer_model": ""} if provider else {}
    return inputs | {"reviewer_model": model} if model else inputs


def template_approver(brand_dir: Path) -> str:
    return load_pack(brand_dir).approver or os.environ.get("FOUNDRY_APPROVER", "")


def main(mode: str, name: str, slug: str) -> None:
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    brand_dir = REPO / "brands" / slug
    kit = (brand_dir / "kit.md").read_text(encoding="utf-8")
    tokens = yaml.safe_load(kit.split("---")[1])
    with httpx.Client(base_url=f"{url}/gateway", timeout=120) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        online = next((machine for machine in gateway.get("/management/controllers").json() if machine["state"] == "online"), None)
        if online is None:
            raise SystemExit("No agent controller is online, so no rooms were made. Start it as in step 2 of the README, then run this again.")
        existing = {agent["name"] for agent in gateway.get("/management/agents").json()}
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
                "brand_dir": str(brand_dir),
                "approver": template_approver(brand_dir),
                "sticker_mode": os.environ.get("FOUNDRY_STICKER_MODE", "subtle"),
                **reviewer_inputs(),
            },
            "filled": {slot: agent for slot, agent in SLOTS.items() if agent in existing},
        })
        if answer.is_error:
            raise SystemExit(f"Switch refused the template: {answer.text}")
    setup_makers(online["status"]["machine"]["workspaces_dir"])
    rooms = {room["room_name"]: room["room_id"] for room in answer.json()["room"]["rooms"]}
    inside = (rooms[f"{name}-studio"], rooms[f"{name}-review"]) if mode == "agency" else (rooms[f"{name}-projects"],) * 2
    entry = f"{rooms[name]}:{inside[0]}:{inside[1]}"
    current = os.environ.get("FOUNDRY_ROOMS", "")
    packs = os.environ.get("FOUNDRY_PACKS", "")
    pack = f"{rooms[name]}:{slug}"
    save({"FOUNDRY_ROOMS": f"{current},{entry}" if current else entry, "FOUNDRY_PACKS": f"{packs},{pack}" if packs else pack})
    print(f"Created {', '.join(rooms)} and saved their ids in {ENV_FILE}")


if __name__ == "__main__":
    main(*sys.argv[1:])
