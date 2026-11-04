"""Runs foundry-desk: uv run --env-file .env python -m foundry"""

import asyncio
import logging
import os

import httpx
from foundry.desk import Desk, Settings, run
from foundry.gates import CardGate
from foundry.intake import default_llm
from foundry.jobs import JobStore
from foundry.switch_client import SwitchClient


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.workrooms:
        raise SystemExit("Set FOUNDRY_ROOMS first. tools/create_rooms.py writes it for you.")
    client = SwitchClient(os.environ["SWITCH_URL"], os.environ["FOUNDRY_DESK_ID"], os.environ["FOUNDRY_DESK_KEY"])
    store = JobStore(os.environ.get("FOUNDRY_JOBS_DB", "foundry-jobs.db"))
    cleanup_llm = default_llm(os.environ.get("FOUNDRY_CLEANUP_MODEL", "claude-sonnet-5-5"))
    desk = Desk(client, store, CardGate(client), default_llm(), settings, cleanup_llm=cleanup_llm)
    try:
        asyncio.run(run(desk, settings.all_rooms()))
    except httpx.HTTPStatusError as error:
        raise SystemExit(f"Switch refused the desk ({error.response.status_code}). Check FOUNDRY_DESK_ID, FOUNDRY_DESK_KEY and FOUNDRY_ROOMS in .env. They change if Switch's data was wiped.") from None


if __name__ == "__main__":
    main()
