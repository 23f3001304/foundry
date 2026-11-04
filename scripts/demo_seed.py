"""Creates both fictional clients, then one department to show the internal room tree. No real customer data.

uv run --env-file .env python scripts/demo_seed.py
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from create_rooms import main as create_rooms

SEED = (
    ("agency", "lalten", "lalten-cafe"),
    ("agency", "green-valley", "shilagate-homes"),
    ("internal", "marketing", "lalten-cafe"),
)


def still_to_make(existing: set[str]) -> list[tuple[str, str, str]]:
    return [entry for entry in SEED if entry[1] not in existing]


def main() -> None:
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        rooms = gateway.get("/rooms").json()
    for mode, name, brand in still_to_make({room["name"] for room in rooms}):
        create_rooms(mode, name, brand)
    print("Start the desk now, or restart it if it is running, so it follows these rooms.")


if __name__ == "__main__":
    main()
