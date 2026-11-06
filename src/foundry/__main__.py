"""Runs foundry-desk: uv run --env-file .env python -m foundry"""

import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path

import httpx
from foundry.adopt import adopt
from foundry.daily import check_packs
from foundry.desk import SHARED_AGENTS, Desk, Settings, run
from foundry.gates import QueuedCardGate
from foundry.intake import chat_llm, default_llm
from foundry.jobs import JobStore
from foundry.pack import PackError
from foundry.switch_client import SwitchClient


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
# The rooms a desk follows. A business added on the dashboard writes them here, and the desk starts following them without a restart.
ROOM_KEYS = ("FOUNDRY_ROOMS", "FOUNDRY_PACKS")
ROOM_CHECK_SECONDS = 30


def rooms_in_env_file() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    pairs = (line.partition("=") for line in ENV_FILE.read_text(encoding="utf-8").splitlines())
    return {key.strip(): value.strip() for key, _, value in pairs if key.strip() in ROOM_KEYS}


async def until_rooms_change(seen: dict[str, str]) -> None:
    while True:
        await asyncio.sleep(ROOM_CHECK_SECONDS)
        try:
            await asyncio.to_thread(adopt, ENV_FILE)
        except httpx.HTTPError as error:
            logging.warning("Could not look for chats Foundry was added to: %s", error)
        now = rooms_in_env_file()
        if now and now != {key: seen[key] for key in now}:
            os.environ.update(now)
            return


async def run_until_rooms_change(desk: Desk, rooms: list[str]) -> bool:
    # True when the rooms changed, so the desk is made again on the new ones.
    working = asyncio.create_task(run(desk, rooms))
    watching = asyncio.create_task(until_rooms_change({key: os.environ.get(key, "") for key in ROOM_KEYS}))
    done, _ = await asyncio.wait({working, watching}, return_when=asyncio.FIRST_COMPLETED)
    if watching in done:
        working.cancel()
        with suppress(asyncio.CancelledError):
            await working
        return True
    watching.cancel()
    working.result()
    return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    while start_desk():
        logging.info("The rooms in .env changed, so the desk now follows the new ones.")


def start_desk() -> bool:
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
    # Each kind of work gets the model it needs: quick sorting of every message, and a stronger one for judgement calls.
    deep_llm = default_llm(os.environ.get("FOUNDRY_DEEP_MODEL") or "claude-opus-5-5")
    desk = Desk(client, store, QueuedCardGate(client), default_llm(), settings, cleanup_llm=cleanup_llm, deep_llm=deep_llm, chat_llm=chat_llm(os.environ.get("FOUNDRY_CHAT_MODEL") or None))
    try:
        return asyncio.run(run_until_rooms_change(desk, settings.all_rooms()))
    except httpx.HTTPStatusError as error:
        raise SystemExit(f"Switch refused the desk ({error.response.status_code}). Check FOUNDRY_DESK_ID, FOUNDRY_DESK_KEY and FOUNDRY_ROOMS in .env. They change if Switch's data was wiped.") from None


if __name__ == "__main__":
    main()
