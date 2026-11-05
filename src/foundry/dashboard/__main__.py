"""Runs the dashboard: uv run --env-file .env python -m foundry.dashboard. It listens on this machine only."""

import logging
import os
from pathlib import Path

import uvicorn

from foundry.dashboard.app import create_app
from foundry.desk import Settings
from foundry.pack import PackError

# Not a setting. The dashboard shows who owes what to whoever can reach it, so it only answers on this machine.
HOST = "127.0.0.1"
DEFAULT_PORT = 8100


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings.from_env()
    except PackError as error:
        raise SystemExit(str(error)) from None
    app = create_app(settings, os.environ.get("SWITCH_URL", "http://127.0.0.1:8000"), own_login=(os.environ.get("SWITCH_EMAIL", ""), os.environ.get("SWITCH_PASSWORD", "")), env_path=Path(".env").resolve())
    uvicorn.run(app, host=HOST, port=int(os.environ.get("FOUNDRY_DASHBOARD_PORT", DEFAULT_PORT)))


if __name__ == "__main__":
    main()
