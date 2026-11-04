"""Registers the WhatsApp connection in Switch from the WHATSAPP_ values in .env, and prints the address to give Meta.

uv run --env-file .env python tools/connect_whatsapp.py
"""

import os

import httpx

CONFIG = {
    "access_token": "WHATSAPP_ACCESS_TOKEN",
    "app_id": "WHATSAPP_APP_ID",
    "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID",
    "app_secret": "WHATSAPP_APP_SECRET",
    "verify_token": "WHATSAPP_VERIFY_TOKEN",
}


def refusal(answer: httpx.Response) -> str:
    # A validation error can echo what was sent, so only a plain explanation is shown.
    detail = answer.json().get("detail") if "json" in answer.headers.get("content-type", "") else None
    return detail if isinstance(detail, str) else "Check the WHATSAPP_ values in .env and that the adapter is loaded."


def main() -> None:
    missing = [name for name in CONFIG.values() if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Set these in .env first: {', '.join(missing)}")
    url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        bridge = next((listed for listed in gateway.get("/collaborations").json() if listed["bridge_type"] == "whatsapp"), None)
        if bridge is None:
            answer = gateway.post("/collaborations", json={
                "bridge_type": "whatsapp",
                "display_name": "WhatsApp",
                "connection_config": {field: os.environ[name] for field, name in CONFIG.items()},
                "channel_creation_enabled": False,
                "preconfigured": False,
            })
            if answer.is_error:
                raise SystemExit(f"Switch would not connect WhatsApp ({answer.status_code}). {refusal(answer)}")
            bridge = answer.json()
    print(f"In Meta's webhook settings, use callback URL {bridge['webhook_url']} with your WHATSAPP_VERIFY_TOKEN, and subscribe to the messages field.")


if __name__ == "__main__":
    main()
