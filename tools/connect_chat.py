"""Connects Slack and Telegram to a local Switch from the values in .env. Whichever is filled in gets connected.

uv run --env-file .env python tools/connect_chat.py
"""

import os

import httpx
from register_desk import local_url

APPS = {
    "slack": ("Slack", {"bot_token": "SLACK_BOT_TOKEN", "app_token": "SLACK_APP_TOKEN", "workspace_id": "SLACK_WORKSPACE_ID"}),
    "telegram": ("Telegram", {"bot_token": "TELEGRAM_BOT_TOKEN", "bot_username": "TELEGRAM_BOT_USERNAME"}),
}
# Autocomplete of agents' names needs a paid Slack plan, and they can still be addressed by typing their names.
EXTRA = {"slack": {"agent_usergroups": False}}
SECRET = {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "TELEGRAM_BOT_TOKEN"}


def refusal(answer: httpx.Response) -> str:
    # A validation error can echo what was sent, so only a plain explanation is shown.
    detail = answer.json().get("detail") if "json" in answer.headers.get("content-type", "") else None
    return detail if isinstance(detail, str) else "Check its values in .env."


def wanted() -> list[str]:
    # An app counts as wanted once any of its secrets is set, and a half-filled one stops everything before Switch is called.
    apps = [app for app, (_, config) in APPS.items() if any(os.environ.get(name) for name in config.values() if name in SECRET)]
    if not apps:
        names = ", ".join(name for _, config in APPS.values() for name in config.values())
        raise SystemExit(f"Nothing to connect. Set these in .env first: {names}")
    missing = [name for app in apps for name in APPS[app][1].values() if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Set these in .env first: {', '.join(missing)}")
    return apps


def main() -> None:
    apps = wanted()
    url = local_url("SWITCH_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=f"{url}/gateway", timeout=60, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        listed = {bridge["bridge_type"] for bridge in gateway.get("/collaborations").json()}
        for app in apps:
            title, config = APPS[app]
            if app in listed:
                print(f"{title} is already connected.")
                continue
            answer = gateway.post("/collaborations", json={
                "bridge_type": app,
                "display_name": title,
                "connection_config": {field: os.environ[name] for field, name in config.items()} | EXTRA.get(app, {}),
                # Channels are made in the app and joined by inviting the bot, so a room in Switch makes nothing in someone's workspace.
                "channel_creation_enabled": False,
                "preconfigured": False,
            })
            if answer.is_error:
                raise SystemExit(f"Switch would not connect {title} ({answer.status_code}). {refusal(answer)}")
            print(f"{title} is connected.")


if __name__ == "__main__":
    main()
