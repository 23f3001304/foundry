"""Writes a scene's earlier history into the log, marked as seeded, so a demo can say "3 weeks ago" with no fake clock, and its overview's charts have 28 days to draw. Nothing else can write to the log this way.

uv run --env-file .env python scripts/seed_history.py it_firm
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from foundry.cards import ANSWERED, Card, CardQueue, Trigger
from foundry.log import Entry, Log
from foundry.switch_client import DESK_NAME

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_people import load_scene, local_only, sender_id, switch_url, username


# How many jobs went out on each of the last 28 days, yesterday first. Written down, so a demo shows the same shape every time, and the second fortnight is the busier one so the delta has something to say.
JOBS_PER_DAY = (2, 1, 0, 0, 3, 2, 1, 2, 1, 0, 0, 2, 1, 2, 1, 1, 0, 0, 2, 1, 1, 1, 0, 0, 0, 1, 1, 1)
# Hours from the request to the work going out, and inputs asked for on the way. These go round, so every band of the chart has something in it.
HOURS_TAKEN = (3, 0.5, 8, 2, 30, 6, 12, 1, 4, 80)
INPUTS_ASKED = (2, 0, 1, 3)


def seed(scene: dict, log: Log, rooms: dict[str, str], bridge: str, now: datetime, cards: CardQueue | None = None) -> list[Entry]:
    history = scene.get("history", [])
    if not history:
        # A scene with none, such as the agency's, has nothing to seed, and may be about more than one business.
        return []
    bucket = scene["brand"]
    earlier = scene.get("earlier_work")
    missing = [entry["room"] for entry in [*history, *([earlier] if earlier else [])] if entry["room"] not in rooms]
    if missing:
        raise SystemExit(f"These rooms don't exist yet: {', '.join(missing)}. Run scripts/demo_seed.py first.")
    if _already_seeded(log, bucket, history, now):
        return []
    made = []
    for entry in sorted(history, key=lambda entry: entry["days_ago"], reverse=True):
        at = now - timedelta(days=entry["days_ago"])
        made.append(log.add_seeded(at, bucket, rooms[entry["room"]], sender_id(entry["as"], bridge), "message", entry["say"], sender_name=username(entry["as"])))
    if earlier:
        made += _earlier_work(earlier, bucket, log, rooms[earlier["room"]], sender_id(earlier["as"], bridge), now, cards)
    return made


def _earlier_work(earlier: dict, bucket: str, log: Log, room: str, person: str, now: datetime, cards: CardQueue | None) -> list[Entry]:
    # Each job shares its id across what happened to it, so the chart can say how long it took. No job row goes with one, so none of them appears as a job to act on.
    made = []

    def entry(at: datetime, kind: str, text: str, job_id: str, sender: str = DESK_NAME, ref: str | None = None) -> None:
        made.append(log.add_seeded(at, bucket, room, sender, kind, text, sender_name=DESK_NAME if sender == DESK_NAME else "", job_id=job_id, ref=ref))

    job = 0
    for back, count in enumerate(JOBS_PER_DAY, start=1):
        for _ in range(count):
            title, took, inputs = earlier["jobs"][job % len(earlier["jobs"])], HOURS_TAKEN[job % len(HOURS_TAKEN)], INPUTS_ASKED[job % len(INPUTS_ASKED)]
            job_id, sent = f"seeded-job-{job}", now - timedelta(days=back, hours=job % 5)
            opened = sent - timedelta(hours=took)
            entry(opened, "job_opened", title, job_id)
            for asked in range(inputs):
                entry(opened + timedelta(minutes=asked + 1), "item_asked", f"An input for {title}", job_id)
            middle = opened + timedelta(hours=took / 2)
            entry(middle, "card_opened", f"Final work: {title}", job_id, ref=f"seeded-card-{job}")
            entry(middle + timedelta(minutes=5), "card_answered", f"Final work: {title}", job_id, person, f"seeded-card-{job}")
            entry(sent, "delivered", title, job_id)
            job += 1
    for number, stuck in enumerate(earlier.get("stuck", [])):
        job_id, request_id, at = f"seeded-stuck-{number}", f"seeded-stuck-card-{number}", now - timedelta(days=stuck["days_ago"])
        # A real card, because the chart counts cards. It was answered then, so it asks nothing of anybody now.
        cards.add_seeded(Card(request_id, Trigger.STUCK, person, bucket, room, stuck["title"], stuck["detail"], [], job_id, None, ANSWERED, at, at, {}))
        entry(at, "card_opened", stuck["title"], job_id, ref=request_id)
        entry(at + timedelta(hours=1), "card_answered", stuck["title"], job_id, person, request_id)
    return made


def _already_seeded(log: Log, bucket: str, history: list[dict], now: datetime) -> bool:
    earliest = now - timedelta(days=max(entry["days_ago"] for entry in history) + 1)
    return any(entry.seeded for entry in log.between(bucket, earliest, now, kinds=["message"]))


def _rooms() -> dict[str, str]:
    with httpx.Client(base_url=f"{switch_url()}/gateway", timeout=60, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        return {room["name"]: room["id"] for room in gateway.get("/rooms").raise_for_status().json()}


def main(name: str) -> None:
    local_only()
    log = Log(os.environ.get("FOUNDRY_LOG_DB", "foundry-log.db"))
    # Nothing is posted for a card that has already ended, so this queue needs no Switch.
    cards = CardQueue(os.environ.get("FOUNDRY_WORK_DB", "foundry-work.db"), None, log, lambda: datetime.now(UTC))
    made = seed(load_scene(name), log, _rooms(), os.environ["FOUNDRY_MATTERMOST_BRIDGE"], datetime.now(UTC), cards)
    print(f"Wrote {len(made)} seeded entries to {log.path}.")


if __name__ == "__main__":
    main(sys.argv[1])
