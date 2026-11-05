"""Runs foundry-desk: uv run --env-file .env python -m foundry"""

import asyncio
import logging
import os

import httpx
from foundry.daily import check_packs
from foundry.desk import SHARED_AGENTS, Desk, Settings, run
from foundry.gates import QueuedCardGate
from foundry.intake import default_llm
from foundry.jobs import JobStore
from foundry.pack import PackError
from foundry.switch_client import SwitchClient


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except PackError as error:
        raise SystemExit(str(error)) from None
    if not settings.workrooms:
        raise SystemExit("Set FOUNDRY_ROOMS first. tools/create_rooms.py writes it for you.")
    if problems := check_packs(settings):
        raise SystemExit("\n".join(problems))
    for room in settings.shared_agency_rooms():
        logging.warning(SHARED_AGENTS.format(room=room))
    client = SwitchClient(os.environ["SWITCH_URL"], os.environ["FOUNDRY_DESK_ID"], os.environ["FOUNDRY_DESK_KEY"])
    store = JobStore(settings.jobs_path)
    cleanup_llm = default_llm(os.environ.get("FOUNDRY_CLEANUP_MODEL", "claude-sonnet-5-5"))
    desk = Desk(client, store, QueuedCardGate(client), default_llm(), settings, cleanup_llm=cleanup_llm)
    try:
        asyncio.run(run(desk, settings.all_rooms()))
    except httpx.HTTPStatusError as error:
        raise SystemExit(f"Switch refused the desk ({error.response.status_code}). Check FOUNDRY_DESK_ID, FOUNDRY_DESK_KEY and FOUNDRY_ROOMS in .env. They change if Switch's data was wiped.") from None


if __name__ == "__main__":
    main()
