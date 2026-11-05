"""Writes a scene's earlier history into the log, marked as seeded, so a demo can say "3 weeks ago" with no fake clock, and its overview's charts have 28 days to draw. Only this and try mode, in its own made-up folder, write to a log this way.

uv run --env-file .env python scripts/seed_history.py it_firm
"""

import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from foundry.cards import ANSWERED, Card, CardQueue, Trigger
from foundry.log import MOVED, Entry, Log
from foundry.switch_client import DESK_NAME

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_people import load_scene, local_only, sender_id, switch_url, username


# How many jobs went out on each of the last 28 days, yesterday first. Written down, so a demo shows the same shape every time, and the second fortnight is the busier one so the delta has something to say.
JOBS_PER_DAY = (2, 1, 0, 0, 3, 2, 1, 2, 1, 0, 0, 2, 1, 2, 1, 1, 0, 0, 2, 1, 1, 1, 0, 0, 0, 1, 1, 1)
# Hours from the request to the work going out, and inputs asked for on the way. These go round, so every band of the chart has something in it.
HOURS_TAKEN = (3, 0.5, 8, 2, 30, 6, 12, 1, 4, 80)
INPUTS_ASKED = (2, 0, 1, 3)


@dataclass
class Written:
    entries: list[Entry]
    cards: list[Card]
    moved: list[Entry] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.entries or self.cards or self.moved)


@dataclass(frozen=True)
class Planned:
    # One entry of a scene's earlier history, and how long before the run it happened.
    back: timedelta
    room: str
    sender: str
    kind: str
    text: str
    sender_name: str = ""
    job_id: str | None = None
    ref: str | None = None

    @property
    def key(self) -> tuple:
        return _key(self.kind, self.sender_name, self.text, self.job_id, self.ref)


def _key(kind: str, name: str, text: str, job_id: str | None, ref: str | None) -> tuple:
    # How this tool knows its own writing again, at any age, in any room and on any bridge. Seeded work goes by the ids this tool gave it. A seeded message has no id, because older seedings gave it none, so it goes by the name that said it and the words. A sender id won't do, because it holds the bridge's.
    return (kind, job_id, ref) if job_id else (kind, name, text)


def seed(scene: dict, log: Log, rooms: dict[str, str], bridge: str, now: datetime, cards: CardQueue | None = None) -> Written:
    # Writes only what the log and the work file don't already have from this tool, so it can run again at any age, after an older seeding that wrote only the history, or after a run that stopped partway.
    history = scene.get("history", [])
    if not history:
        # A scene with none, such as the agency's, has nothing to seed, and may be about more than one business.
        return Written([], [])
    bucket = scene["brand"]
    earlier = scene.get("earlier_work")
    missing = [entry["room"] for entry in [*history, *([earlier] if earlier else [])] if entry["room"] not in rooms]
    if missing:
        raise SystemExit(f"These rooms don't exist yet: {', '.join(missing)}. Run scripts/demo_seed.py first.")
    if earlier and earlier.get("stuck") and cards is None:
        raise ValueError("This scene seeds cards, so it needs the work file, and nothing has been written.")
    found: dict[tuple, list[Entry]] = {}
    for entry in log.seeded(bucket):
        found.setdefault(_key(entry.kind, entry.sender_name, entry.text, entry.job_id, entry.ref), []).append(entry)
    lines = [
        Planned(timedelta(days=entry["days_ago"]), rooms[entry["room"]], sender_id(entry["as"], bridge), "message", entry["say"], username(entry["as"]))
        for entry in sorted(history, key=lambda entry: entry["days_ago"], reverse=True)
    ]
    work = _earlier_work(earlier, rooms[earlier["room"]], sender_id(earlier["as"], bridge), username(earlier["as"])) if earlier else []
    # A card written by a run that stopped before any work reached the log says when that work was told from.
    written_from = _told_from(work, found, _card_said_from(earlier, cards) or now) if earlier else now
    written_cards = _stuck_cards(earlier, bucket, rooms[earlier["room"]], sender_id(earlier["as"], bridge), written_from, cards) if earlier else []
    # Each part keeps the times it started with, so a part finished later still adds up. A part that hasn't started is told from now.
    entries = _write_missing(lines, bucket, log, found, _told_from(lines, found, now))
    entries += _write_missing(work, bucket, log, found, written_from)
    return Written(entries, written_cards, _move_people([*lines, *work[:1]], bucket, log))


def _earlier_work(earlier: dict, room: str, person: str, name: str) -> list[Planned]:
    # Each job shares its id across what happened to it, so the chart can say how long it took. No job row goes with one, so none of them appears as a job to act on.
    plan = [Planned(timedelta(days=5), room, person, "message", earlier["say"], name)]

    def entry(back: timedelta, kind: str, text: str, job_id: str, sender: str = DESK_NAME, ref: str | None = None) -> None:
        plan.append(Planned(back, room, sender, kind, text, DESK_NAME if sender == DESK_NAME else "", job_id, ref))

    job = 0
    for days, count in enumerate(JOBS_PER_DAY, start=1):
        for _ in range(count):
            title, took, inputs = earlier["jobs"][job % len(earlier["jobs"])], HOURS_TAKEN[job % len(HOURS_TAKEN)], INPUTS_ASKED[job % len(INPUTS_ASKED)]
            job_id, sent = f"seeded-job-{job}", timedelta(days=days, hours=job % 5)
            opened = sent + timedelta(hours=took)
            entry(opened, "job_opened", title, job_id)
            for asked in range(inputs):
                entry(opened - timedelta(minutes=asked + 1), "item_asked", f"An input for {title}", job_id)
            middle = opened - timedelta(hours=took / 2)
            entry(middle, "card_opened", f"Final work: {title}", job_id, ref=f"seeded-card-{job}")
            entry(middle - timedelta(minutes=5), "card_answered", f"Final work: {title}", job_id, person, f"seeded-card-{job}")
            entry(sent, "delivered", title, job_id)
            job += 1
    for number, stuck in enumerate(earlier.get("stuck", [])):
        job_id, request_id, back = f"seeded-stuck-{number}", f"seeded-stuck-card-{number}", timedelta(days=stuck["days_ago"])
        entry(back, "card_opened", stuck["title"], job_id, ref=request_id)
        entry(back - timedelta(hours=1), "card_answered", stuck["title"], job_id, person, request_id)
    return plan


def _card_said_from(earlier: dict, cards: CardQueue | None) -> datetime | None:
    if cards is None:
        return None
    for number, stuck in enumerate(earlier.get("stuck", [])):
        card = cards.get(f"seeded-stuck-card-{number}")
        if card is not None:
            return card.created_at + timedelta(days=stuck["days_ago"])
    return None


def _stuck_cards(earlier: dict, bucket: str, room: str, person: str, start: datetime, cards: CardQueue | None) -> list[Card]:
    # Real cards, because the chart counts cards. They were answered then, so they ask nothing of anybody now. These go first, so a work file that's locked stops the run before it writes anything.
    made = []
    if cards is None:
        return made
    for number, stuck in enumerate(earlier.get("stuck", [])):
        request_id = f"seeded-stuck-card-{number}"
        if cards.get(request_id) is None:
            at = start - timedelta(days=stuck["days_ago"])
            card = Card(request_id, Trigger.STUCK, person, bucket, room, stuck["title"], stuck["detail"], [], f"seeded-stuck-{number}", None, ANSWERED, at, at, {})
            cards.add_seeded(card)
            made.append(card)
    return made


def _told_from(plan: list[Planned], found: dict[tuple, list[Entry]], now: datetime) -> datetime:
    # The moment a part was first told from, read back from anything of it already written. An entry that's planned more than once can't say which one it was.
    times = Counter(planned.key for planned in plan)
    return next((found[planned.key][0].at + planned.back for planned in plan if times[planned.key] == 1 and planned.key in found), now)


def _write_missing(plan: list[Planned], bucket: str, log: Log, found: dict[tuple, list[Entry]], start: datetime) -> list[Entry]:
    have = Counter({key: len(entries) for key, entries in found.items()})
    made = []
    for planned in plan:
        if have[planned.key]:
            have[planned.key] -= 1
            continue
        made.append(log.add_seeded(start - planned.back, bucket, planned.room, planned.sender, planned.kind, planned.text, sender_name=planned.sender_name, job_id=planned.job_id, ref=planned.ref))
    return made


def _move_people(lines: list[Planned], bucket: str, log: Log) -> list[Entry]:
    # A person's newest seeded line says where Foundry asks them. The log only grows, so a line that's already there can't take on a scene's fresh rooms or a new bridge's id, and writing it again would double it. What goes in is a note of where they are now, at the time of that line, so they last wrote when they last wrote.
    planned = {(line.sender_name, line.text): line for line in lines}
    newest: dict[str, Entry] = {}
    for entry in log.seeded(bucket):
        if entry.kind in ("message", MOVED) and (entry.sender_name not in newest or entry.at >= newest[entry.sender_name].at):
            newest[entry.sender_name] = entry
    moved = []
    for name, entry in newest.items():
        line = planned.get((name, entry.text))
        if line is not None and (line.room, line.sender) != (entry.room_id, entry.sender):
            moved.append(log.add_seeded(entry.at, bucket, line.room, line.sender, MOVED, entry.text, sender_name=name, ref=entry.sender))
    return moved


def outcome(scene: dict, written: Written, path: object) -> str:
    if not scene.get("history"):
        return "This scene has no earlier history, so there is nothing to write."
    if not written:
        return f"This scene's earlier history is already all in {path}, so nothing was written."
    entries, cards, moved = len(written.entries), len(written.cards), len(written.moved)
    wrote = f"Wrote {entries} seeded {'entry' if entries == 1 else 'entries'} and {cards} seeded {'card' if cards == 1 else 'cards'} to {path}." if entries or cards else f"This scene's earlier history is already all in {path}, so none of it was written again."
    return f"{wrote} {moved} {'person' if moved == 1 else 'people'} moved to this scene's rooms and ids, so that is where they are asked." if moved else wrote


def _rooms() -> dict[str, str]:
    with httpx.Client(base_url=f"{switch_url()}/gateway", timeout=60, trust_env=False) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        return {room["name"]: room["id"] for room in gateway.get("/rooms").raise_for_status().json()}


def main(name: str) -> None:
    local_only()
    log = Log(os.environ.get("FOUNDRY_LOG_DB", "foundry-log.db"))
    # Nothing is posted for a card that has already ended, so this queue needs no Switch.
    cards = CardQueue(os.environ.get("FOUNDRY_WORK_DB", "foundry-work.db"), None, log, lambda: datetime.now(UTC))
    scene = load_scene(name)
    print(outcome(scene, seed(scene, log, _rooms(), os.environ["FOUNDRY_MATTERMOST_BRIDGE"], datetime.now(UTC), cards), log.path))


if __name__ == "__main__":
    main(sys.argv[1])
