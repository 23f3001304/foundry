"""Registers foundry-desk under the person who signs in, so that owner-agents admits it, and saves its id and key in .env."""

import os
from pathlib import Path

import httpx

ENV_FILE = Path(__file__).parent.parent / ".env"
PROFILE = {"connection_model": "always_on", "message_exchange": True, "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": []}


def save(values: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [line for line in lines if line.split("=", 1)[0] not in values]
    ENV_FILE.write_text("\n".join(kept + [f"{name}={value}" for name, value in values.items()]) + "\n", encoding="utf-8")
    os.environ.update(values)


def main() -> None:
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=30) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        minted = gateway.post("/api-keys", json={"label": "foundry-desk"})
        minted.raise_for_status()
        desk = httpx.post(
            f"{url}/agents",
            headers={"Authorization": f"Bearer {minted.json()['key']}"},
            json={"name": "foundry-desk", "description": "Takes requests in, asks for approvals and delivers approved work", "connector_type": "custom", "integration_profile": PROFILE, "overwrite": True},
            timeout=30,
        )
        desk.raise_for_status()
        # The desk reads everyone in the room. Who may approve is enforced in gates.py.
        gateway.put(f"/agents/{desk.json()['id']}/addressing-policy", json={"policy": None}).raise_for_status()
    save({"SWITCH_URL": url, "FOUNDRY_DESK_ID": desk.json()["id"], "FOUNDRY_DESK_KEY": desk.json()["api_key"]})
    # Registering again takes a new key, so a desk still running on the old one has to be restarted.
    print(f"Registered foundry-desk as {desk.json()['id']} and saved its key in {ENV_FILE}")


if __name__ == "__main__":
    main()
