"""Writes a scene's earlier history into the log, marked as seeded, so a demo can say "3 weeks ago" with no fake clock. Nothing else can write to the log this way.

uv run --env-file .env python scripts/seed_history.py it_firm
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from foundry.log import Entry, Log

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_people import load_scene, local_only, sender_id, switch_url, username


def seed(scene: dict, log: Log, rooms: dict[str, str], bridge: str, now: datetime) -> list[Entry]:
    history = scene.get("history", [])
    if not history:
        # A scene with none, such as the agency's, has nothing to seed, and may be about more than one business.
        return []
    bucket = scene["brand"]
    missing = [entry["room"] for entry in history if entry["room"] not in rooms]
    if missing:
        raise SystemExit(f"These rooms don't exist yet: {', '.join(missing)}. Run scripts/demo_seed.py first.")
    if _already_seeded(log, bucket, history, now):
        return []
    made = []
    for entry in sorted(history, key=lambda entry: entry["days_ago"], reverse=True):
        at = now - timedelta(days=entry["days_ago"])
        made.append(log.add_seeded(at, bucket, rooms[entry["room"]], sender_id(entry["as"], bridge), "message", entry["say"], sender_name=username(entry["as"])))
    return made


def _already_seeded(log: Log, bucket: str, history: list[dict], now: datetime) -> bool:
    earliest = now - timedelta(days=max(entry["days_ago"] for entry in history) + 1)
    return any(entry.seeded for entry in log.between(bucket, earliest, now, kinds=["message"]))


def _rooms() -> dict[str, str]:
    with httpx.Client(base_url=f"{switch_url()}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        return {room["name"]: room["id"] for room in gateway.get("/rooms").raise_for_status().json()}


def main(name: str) -> None:
    local_only()
    log = Log(os.environ.get("FOUNDRY_LOG_DB", "foundry-log.db"))
    made = seed(load_scene(name), log, _rooms(), os.environ["FOUNDRY_MATTERMOST_BRIDGE"], datetime.now(UTC))
    print(f"Wrote {len(made)} seeded entries to {log.path}.")


if __name__ == "__main__":
    main(sys.argv[1])
