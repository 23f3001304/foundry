"""Creates both fictional clients, one department to show the internal room tree, the IT firm's four rooms, the investment firm's six and the marketing agency's two clients. No real customer data.

uv run --env-file .env python scripts/demo_seed.py
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_rooms import main as create_rooms
from demo_people import find_bridge, switch_url
from register_desk import save

BRANDS = Path(__file__).resolve().parent.parent / "brands"
NO_BRIDGE = "Skipped {room}: the pack for {brand} names its approver through the Mattermost bridge, and this stack has none."
SEED = (
    ("agency", "lalten", "lalten-cafe"),
    ("agency", "green-valley", "shilagate-homes"),
    ("internal", "marketing", "lalten-cafe"),
    ("internal", "delivery", "demo-it-firm"),
    ("internal", "team-a", "demo-it-firm"),
    ("internal", "team-b", "demo-it-firm"),
    ("internal", "team-c", "demo-it-firm"),
    ("internal", "analysts", "demo-investment-firm"),
    ("internal", "office-a", "demo-investment-firm"),
    ("internal", "office-b", "demo-investment-firm"),
    ("internal", "office-c", "demo-investment-firm"),
    ("internal", "office-d", "demo-investment-firm"),
    ("internal", "office-e", "demo-investment-firm"),
    # The agency's two clients. Each gets agents of its own, and the agency's own folder, brands/demo-agency, has no rooms.
    ("agency", "phatakha", "demo-agency-client-a"),
    ("agency", "ambaryug", "demo-agency-client-b"),
)


def still_to_make(existing: set[str]) -> list[tuple[str, str, str]]:
    return [entry for entry in SEED if entry[1] not in existing]


def needs_bridge(brand: str) -> bool:
    pack = BRANDS / brand / "pack.md"
    return pack.is_file() and "{bridge}" in pack.read_text(encoding="utf-8")


def main() -> None:
    url = switch_url()
    # First, because the template shows the agents the approver each pack names, and that holds the bridge's id.
    bridge = find_bridge() if any(needs_bridge(brand) for _, _, brand in SEED) else None
    if bridge:
        save({"FOUNDRY_MATTERMOST_BRIDGE": bridge})
    with httpx.Client(base_url=f"{url}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        rooms = gateway.get("/rooms").json()
    for mode, name, brand in still_to_make({room["name"] for room in rooms}):
        # One business that can't be made here doesn't stop the others.
        if needs_bridge(brand) and not bridge:
            print(NO_BRIDGE.format(room=name, brand=brand))
        else:
            create_rooms(mode, name, brand)
    print("Start the desk now, or restart it if it is running, so it follows these rooms.")


if __name__ == "__main__":
    main()
