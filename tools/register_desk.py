"""Registers foundry-desk under the person who signs in, so that owner-agents admits it, and saves its id and key in .env."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ENV_FILE = Path(__file__).parent.parent / ".env"
THIS_MACHINE = ("localhost", "127.0.0.1", "::1")
PROFILE = {"connection_model": "always_on", "message_exchange": True, "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": []}
DESK = {"name": "foundry-desk", "description": "Takes requests in, asks for approvals and delivers approved work", "connector_type": "custom", "integration_profile": PROFILE}
TOOK_OVER = "Took over the existing foundry-desk, so restart any desk that is running."


def save(values: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [line for line in lines if line.split("=", 1)[0] not in values]
    ENV_FILE.write_text("\n".join(kept + [f"{name}={value}" for name, value in values.items()]) + "\n", encoding="utf-8")
    os.environ.update(values)


def local_url(name: str, default: str) -> str:
    # These scripts sign in as the admin, and the demo's reset the password of anyone with a scripted person's name, so they only ever talk to a stack on this machine.
    url = os.environ.get(name, default)
    host = urlsplit(url).hostname or ""
    if host not in THIS_MACHINE and not host.endswith(".localhost"):
        raise SystemExit(f"{name} points at {host or url}, which is not this machine. This script only runs against a local stack, so nothing was done.")
    return url


def main() -> None:
    url = local_url("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=30, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        minted = gateway.post("/api-keys", json={"label": "foundry-desk"})
        minted.raise_for_status()
        with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {minted.json()['key']}"}, timeout=30, trust_env=False) as switch:
            desk = switch.post("/agents", json=DESK)
            # Only a desk that is already there is overwritten, and whoever ran this is told.
            took_over = desk.status_code == 409
            if took_over:
                desk = switch.post("/agents", json={**DESK, "overwrite": True})
        desk.raise_for_status()
        # The desk reads everyone in the room. Who may approve is enforced in gates.py.
        gateway.put(f"/agents/{desk.json()['id']}/addressing-policy", json={"policy": None}).raise_for_status()
    save({"SWITCH_URL": url, "FOUNDRY_DESK_ID": desk.json()["id"], "FOUNDRY_DESK_KEY": desk.json()["api_key"]})
    print(f"Registered foundry-desk as {desk.json()['id']} and saved its key in {ENV_FILE}")
    # Registering again takes a new key, so a desk still running on the old one has to be restarted.
    if took_over:
        print(TOOK_OVER)


if __name__ == "__main__":
    main()
