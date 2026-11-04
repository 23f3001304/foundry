"""Creates both fictional clients, one department to show the internal room tree, and the IT firm's four rooms. No real customer data.

uv run --env-file .env python scripts/demo_seed.py
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_rooms import main as create_rooms
from demo_people import bridge_id
from register_desk import save

SEED = (
    ("agency", "lalten", "lalten-cafe"),
    ("agency", "green-valley", "shilagate-homes"),
    ("internal", "marketing", "lalten-cafe"),
    ("internal", "delivery", "demo-it-firm"),
    ("internal", "team-a", "demo-it-firm"),
    ("internal", "team-b", "demo-it-firm"),
    ("internal", "team-c", "demo-it-firm"),
)


def still_to_make(existing: set[str]) -> list[tuple[str, str, str]]:
    return [entry for entry in SEED if entry[1] not in existing]


def main() -> None:
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    # First, because the template shows the agents the approver each pack names, and that holds the bridge's id.
    save({"FOUNDRY_MATTERMOST_BRIDGE": bridge_id()})
    with httpx.Client(base_url=f"{url}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        rooms = gateway.get("/rooms").json()
    for mode, name, brand in still_to_make({room["name"] for room in rooms}):
        create_rooms(mode, name, brand)
    print("Start the desk now, or restart it if it is running, so it follows these rooms.")


if __name__ == "__main__":
    main()
