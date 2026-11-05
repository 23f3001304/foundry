"""Creates both fictional clients, one department to show the internal room tree, the IT firm's four rooms, the investment firm's six and the marketing agency's two clients. No real customer data.

uv run --env-file .env python scripts/demo_seed.py [demo]

With a demo's name, it_firm, investment_firm, agency or coffee_shop, only that demo's rooms are made. tools/foundry_setup.py runs it this way.

To choose the chat app for outside people, add --outside-bridge Mattermost. Left out, tools/create_rooms.py chooses one your account is linked on.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_rooms import main as create_rooms
from create_rooms import names_people_on_mattermost, remember_rooms, unfinished_rooms
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
# Which rooms each demo needs, so a machine can make one and not all of them.
DEMOS = {
    "it_firm": ("delivery", "team-a", "team-b", "team-c"),
    "investment_firm": ("analysts", "office-a", "office-b", "office-c", "office-d", "office-e"),
    "agency": ("phatakha", "ambaryug"),
    "coffee_shop": ("lalten",),
}
UNKNOWN_DEMO = "There is no demo called {demo}. The demos are {demos}."


def seed_for(demo: str | None) -> tuple[tuple[str, str, str], ...]:
    if demo is None:
        return SEED
    if demo not in DEMOS:
        raise SystemExit(UNKNOWN_DEMO.format(demo=demo, demos=", ".join(DEMOS)))
    return tuple(entry for entry in SEED if entry[1] in DEMOS[demo])


def still_to_make(existing: set[str], seed: tuple[tuple[str, str, str], ...] = SEED) -> list[tuple[str, str, str]]:
    return [entry for entry in seed if entry[1] not in existing]


def needs_bridge(brand: str) -> bool:
    return names_people_on_mattermost(BRANDS / brand)


def main(demo: str | None = None, outside_bridge: str = "") -> None:
    url = switch_url()
    seed = seed_for(demo)
    chosen = {"outside_bridge": outside_bridge} if outside_bridge else {}
    # First, because the template shows the agents the approver each pack names, and that holds the bridge's id.
    bridge = find_bridge() if any(needs_bridge(brand) for _, _, brand in seed) else None
    if bridge:
        save({"FOUNDRY_MATTERMOST_BRIDGE": bridge})
    with httpx.Client(base_url=f"{url}/gateway", timeout=60, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        rooms = gateway.get("/rooms").json()
    # A run stopped between Switch making a room and .env being written would leave a room this script skips and the desk never follows.
    remember_rooms(seed, {room["name"]: room["id"] for room in rooms})
    # A business a run left half made has its outside room, and is still to make. Its name in .env is what says so.
    for mode, name, brand in still_to_make({room["name"] for room in rooms} - set(unfinished_rooms()), seed):
        # One business that can't be made here doesn't stop the others.
        if needs_bridge(brand) and not bridge:
            print(NO_BRIDGE.format(room=name, brand=brand))
        else:
            create_rooms(mode, name, brand, **chosen)
    print("Start the desk now, or restart it if it is running, so it follows these rooms.")


def command() -> None:
    parser = argparse.ArgumentParser(description="Creates the rooms of every demo business that doesn't have them yet.")
    parser.add_argument("demo", nargs="?", default=None, help="Only this demo: it_firm, investment_firm, agency or coffee_shop.")
    parser.add_argument("--outside-bridge", default="", help="The connected chat app for the rooms outside people use, by its name in Switch or its kind. Left out, it is one your account is linked on.")
    args = parser.parse_args()
    main(args.demo, args.outside_bridge)


if __name__ == "__main__":
    command()
