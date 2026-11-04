"""The card rule: only a listed trigger can open a card, one per person per bucket, and only routine items merge."""

import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import httpx

from foundry.log import Log
from foundry.switch_client import DESK_NAME, SwitchClient

logger = logging.getLogger(__name__)


class Trigger(Enum):
    BRIEF = "brief"
    FINAL_WORK = "final_work"
    VOICE = "voice"
    QUESTION = "question"
    DUE = "due"
    STUCK = "stuck"
    REMINDER = "reminder"
    LATE_FIX = "late_fix"
    DAILY_REPORT = "daily_report"
    ATTENTION_NOTE = "attention_note"
    ALREADY_TOLD = "already_told"


@dataclass(frozen=True)
class Route:
    to: str
    now: bool


ROUTE = {
    Trigger.BRIEF: Route("approver", True),
    Trigger.FINAL_WORK: Route("approver", True),
    Trigger.VOICE: Route("sender", True),
    Trigger.QUESTION: Route("sender", True),
    Trigger.DUE: Route("asker", True),
    Trigger.STUCK: Route("approver", True),
    Trigger.REMINDER: Route("owner", True),
    Trigger.LATE_FIX: Route("approver", True),
    Trigger.DAILY_REPORT: Route("approver", False),
    Trigger.ATTENTION_NOTE: Route("approver", False),
    Trigger.ALREADY_TOLD: Route("asker", False),
}
HOLDS_JOB = {Trigger.BRIEF, Trigger.FINAL_WORK, Trigger.DUE, Trigger.STUCK, Trigger.LATE_FIX}

QUEUED = "queued"
OPEN = "open"
IN_ROUTINE = "in_routine"
ANSWERED = "answered"
CLOSED = "closed"
EXPIRED = "expired"
ENDS = (ANSWERED, CLOSED, EXPIRED)

APPROVE_CLEAN = "Approve everything clean"
SHOW_NEEDS = "Show what needs me"
ROUTINE_TITLE = "Routine items"
NEEDS_YOU = " (needs you)"
ROUTINE_CLOSED = "I closed your routine card because something needs a decision first. Its items come back at the next set time."
CARD_LIMIT = 700
READ_ABOVE = "The full text is just above this card."
ROOM_GONE = (403, 404)
SLOT_FORMAT = "%Y-%m-%d %H:%M"
# Inside Card.data. A merged card lists its items. An item the person asked to see waits its turn alone, not for a set time.
ITEMS = "items"
ONE_BY_ONE = "one_by_one"
WAITING_SINCE = "waiting_since"
# Stands in for a person in set_time_runs, to record that a bucket has reached a set time at all.
EVERYONE = ""
COLUMNS =("request_id", "trigger", "person", "bucket", "room_id", "title", "detail", "choices", "job_id", "item_id", "state", "created_at", "opened_at", "data")


@dataclass
class Card:
    request_id: str
    trigger: Trigger
    person: str
    bucket: str
    room_id: str
    title: str
    detail: str
    choices: list[str]
    job_id: str | None
    item_id: str | None
    state: str
    created_at: datetime
    opened_at: datetime | None
    data: dict

    @property
    def is_routine(self) -> bool:
        return not ROUTE[self.trigger].now

    @property
    def is_merged(self) -> bool:
        return ITEMS in self.data


def fit_detail(client: SwitchClient, room_id: str, detail: str) -> str:
    # Switch takes the buttons off a card it cannot show in full.
    if len(detail) <= CARD_LIMIT:
        return detail
    client.post_message(room_id, detail)
    return READ_ABOVE


def _new_id() -> str:
    return f"card-{uuid.uuid4().hex[:8]}"


def _is_clean(card: Card) -> bool:
    # An item that doesn't say it's clean could need someone, so one press must not approve it.
    return card.data.get("clean", False)


def _waiting_since(card: Card) -> datetime:
    since = card.data.get(WAITING_SINCE)
    return datetime.fromisoformat(since) if since else card.created_at


def _latest_slot(times: tuple[str, ...], offset_minutes: int, now: datetime) -> datetime | None:
    # The latest set time at or before now on the business's own clock. Looking back a day finds one missed overnight.
    zone = timezone(timedelta(minutes=offset_minutes))
    today = now.astimezone(zone).date()
    slots = [
        datetime.combine(day, datetime.strptime(time, "%H:%M").time(), zone)
        for day in (today - timedelta(days=1), today)
        for time in times
    ]
    return max((slot for slot in slots if slot <= now), default=None)


def _row(card: Card) -> tuple:
    return (
        card.request_id, card.trigger.value, card.person, card.bucket, card.room_id, card.title, card.detail, json.dumps(card.choices),
        card.job_id, card.item_id, card.state, card.created_at.isoformat(), card.opened_at.isoformat() if card.opened_at else None, json.dumps(card.data),
    )


def _card(row: tuple) -> Card:
    return Card(row[0], Trigger(row[1]), *row[2:7], json.loads(row[7]), *row[8:11], datetime.fromisoformat(row[11]), datetime.fromisoformat(row[12]) if row[12] else None, json.loads(row[13]))


class CardQueue:
    def __init__(self, path: Path | str, client: SwitchClient, log: Log, clock: Callable[[], datetime]) -> None:
        self.path = str(path)
        self.client = client
        self.log = log
        self.clock = clock
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS cards (
                    request_id TEXT PRIMARY KEY, trigger TEXT NOT NULL, person TEXT NOT NULL, bucket TEXT NOT NULL, room_id TEXT NOT NULL,
                    title TEXT NOT NULL, detail TEXT NOT NULL, choices TEXT NOT NULL, job_id TEXT, item_id TEXT, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, opened_at TEXT, data TEXT NOT NULL)"""
            )
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_card ON cards (person, bucket) WHERE state = 'open'")
            db.execute("CREATE TABLE IF NOT EXISTS set_time_runs (bucket TEXT NOT NULL, person TEXT NOT NULL, slot TEXT NOT NULL, PRIMARY KEY (bucket, person, slot))")

    def submit(self, trigger: Trigger, person: str, bucket: str, room_id: str, title: str, detail: str, choices: tuple[str, ...] | list[str] = (), job_id: str | None = None, item_id: str | None = None, data: dict | None = None, request_id: str | None = None) -> Card:
        now = ROUTE[trigger].now
        card = Card(request_id or _new_id(), trigger, person, bucket, room_id, title, detail, list(choices), job_id, item_id, QUEUED, self.clock(), None, dict(data or {}))
        if now and self._nothing_in_the_way(person, bucket):
            # A card that can't open raises with nothing saved, so the caller's retry isn't a second card.
            self._open(card)
        else:
            self._save(card)
        return card

    def pump(self) -> None:
        queued = self._select("WHERE state = ? ORDER BY rowid", QUEUED)
        for card in [c for c in queued if not c.is_routine] + [c for c in queued if c.data.get(ONE_BY_ONE)]:
            if self.open_for(card.person, card.bucket) is not None:
                continue
            try:
                self._open(card)
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in ROOM_GONE:
                    raise
                logger.warning("Gave up on card %s for job %s: Switch refused it (%s), so its room is probably gone.", card.request_id, card.job_id, error.response.status_code)
                self.finish(card.request_id, CLOSED)

    def run_set_times(self, bucket: str, times: tuple[str, ...], offset_minutes: int, now: datetime) -> None:
        self.pump()
        slot = _latest_slot(times, offset_minutes, now)
        if slot is None:
            return
        name = slot.strftime(SLOT_FORMAT)
        arrived = self._set_time_arrived(bucket, name)
        for person, items in self._routine_waiting(bucket).items():
            if arrived:
                self._count_as_waiting_at(slot, items)
            if self._has_run(bucket, person, name) or not any(_waiting_since(item) <= slot for item in items):
                continue
            in_the_way = self.open_for(person, bucket)
            if in_the_way is None:
                self._open_routine(person, bucket, items)
            elif not in_the_way.is_routine:
                # A decision card is up. These wait behind it, and this set time stays due until it's answered.
                continue
            self._record_run(bucket, person, name)

    def known_buckets(self) -> list[str]:
        with closing(sqlite3.connect(self.path)) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT bucket FROM cards")]

    def is_open(self, request_id: str) -> bool:
        card = self.get(request_id)
        return card is not None and card.state == OPEN

    def get(self, request_id: str) -> Card | None:
        rows = self._select("WHERE request_id = ?", request_id)
        return rows[0] if rows else None

    def open_for(self, person: str, bucket: str) -> Card | None:
        rows = self._select("WHERE person = ? AND bucket = ? AND state = ?", person, bucket, OPEN)
        return rows[0] if rows else None

    def finish(self, request_id: str, state: str) -> Card:
        if state not in ENDS:
            raise ValueError(f"{state} is not how a card ends")
        card = self.get(request_id)
        if card is None:
            raise KeyError(request_id)
        # A press arriving after a card was dealt with changes nothing. One that ran out can still take a typed answer.
        if card.state in (ANSWERED, CLOSED) or card.state == state:
            return card
        card.state = state
        self._save(card)
        self._return_items(card)
        if state == ANSWERED:
            self._log(card, "card_answered", card.person)
        return card

    def requeue_routine(self, request_id: str) -> None:
        card = self.get(request_id)
        if card is None:
            raise KeyError(request_id)
        if card.state != OPEN:
            return
        self.finish(request_id, EXPIRED)
        if not card.is_merged:
            data = {key: value for key, value in card.data.items() if key != ONE_BY_ONE}
            self._save_again(card, {**data, WAITING_SINCE: self.clock().isoformat()})

    def answer_routine(self, request_id: str, choice: str | None) -> list[Card]:
        # One press only ever approves what is clean. Whatever is left goes back for the next set time.
        card = self.get(request_id)
        if card is None:
            raise KeyError(request_id)
        if card.state != OPEN:
            return []
        approved = []
        for item in (self.get(item_id) for item_id in card.data[ITEMS]):
            if choice == APPROVE_CLEAN and _is_clean(item):
                approved.append(self.finish(item.request_id, ANSWERED))
            elif choice == SHOW_NEEDS and not _is_clean(item):
                item.state, item.data[ONE_BY_ONE] = QUEUED, True
                self._save(item)
        self.finish(request_id, ANSWERED)
        self.pump()
        return approved

    def waiting(self, bucket: str) -> list[Card]:
        return self._select("WHERE bucket = ? AND state = ? ORDER BY rowid", bucket, QUEUED)

    def _nothing_in_the_way(self, person: str, bucket: str) -> bool:
        in_the_way = self.open_for(person, bucket)
        if in_the_way is None:
            return True
        if not in_the_way.is_routine:
            return False
        self._close_routine(in_the_way)
        return True

    def _close_routine(self, card: Card) -> None:
        # Switch marks a closed card "Cancelled", so say why.
        try:
            self.client.close_card(card.request_id)
            self.client.post_message(card.room_id, ROUTINE_CLOSED)
        except httpx.HTTPError as error:
            logger.warning("Could not close routine card %s: %s", card.request_id, error)
        self.finish(card.request_id, CLOSED)
        if not card.is_merged:
            self._save_again(card, card.data)

    def _save_again(self, card: Card, data: dict) -> None:
        # Switch has already seen this request id, so the item comes back under a new one.
        self._save(replace(card, request_id=_new_id(), state=QUEUED, opened_at=None, data=data))

    def _return_items(self, card: Card) -> None:
        for item_id in card.data.get(ITEMS, ()):
            item = self.get(item_id)
            if item.state == IN_ROUTINE:
                item.state = QUEUED
                item.data[WAITING_SINCE] = self.clock().isoformat()
                self._save(item)

    def _open(self, card: Card) -> None:
        detail = fit_detail(self.client, card.room_id, card.detail)
        if card.choices:
            question = "\n\n".join(part for part in (card.title, detail) if part)
            self.client.open_question_card(card.room_id, card.request_id, question, card.choices)
        else:
            self.client.open_card(card.room_id, card.request_id, card.title, detail)
        card.state, card.opened_at = OPEN, self.clock()
        self._save(card)
        self._log(card, "card_opened", DESK_NAME)

    def _open_routine(self, person: str, bucket: str, items: list[Card]) -> None:
        first = items[0]
        lines = [f"- {item.title}{'' if _is_clean(item) else NEEDS_YOU}" for item in items]
        # A merged card takes its first item's trigger, so it still comes from the list and still reads as routine.
        card = Card(_new_id(), first.trigger, person, bucket, first.room_id, ROUTINE_TITLE, "\n".join(lines), [APPROVE_CLEAN, SHOW_NEEDS], None, None, QUEUED, self.clock(), None, {ITEMS: [item.request_id for item in items]})
        try:
            self._open(card)
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in ROOM_GONE:
                raise
            logger.warning("Gave up on the routine items in room %s: Switch refused them (%s), so the room is probably gone.", first.room_id, error.response.status_code)
            for item in items:
                if item.room_id == first.room_id:
                    self.finish(item.request_id, CLOSED)
            return
        for item in items:
            item.state = IN_ROUTINE
            self._save(item)
            self._log(item, "card_opened", DESK_NAME)

    def _routine_waiting(self, bucket: str) -> dict[str, list[Card]]:
        people: dict[str, list[Card]] = {}
        for card in self.waiting(bucket):
            if card.is_routine and not card.data.get(ONE_BY_ONE):
                people.setdefault(card.person, []).append(card)
        return people

    def _set_time_arrived(self, bucket: str, slot: str) -> bool:
        # True once for each set time a bucket comes to. A bucket's very first run has no earlier one to tell it the time just came.
        with closing(sqlite3.connect(self.path)) as db, db:
            reached = [row[0] for row in db.execute("SELECT slot FROM set_time_runs WHERE bucket = ? AND person = ?", (bucket, EVERYONE))]
            if slot in reached:
                return False
            db.execute("INSERT INTO set_time_runs VALUES (?, ?, ?)", (bucket, EVERYONE, slot))
        return bool(reached)

    def _count_as_waiting_at(self, slot: datetime, items: list[Card]) -> None:
        # Whatever is here when a set time arrives is for that set time, even a report built moments after it on this same run.
        for item in items:
            if _waiting_since(item) > slot:
                item.data[WAITING_SINCE] = slot.isoformat()
                self._save(item)

    def _has_run(self, bucket: str, person: str, slot: str) -> bool:
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT 1 FROM set_time_runs WHERE bucket = ? AND person = ? AND slot = ?", (bucket, person, slot)).fetchone() is not None

    def _record_run(self, bucket: str, person: str, slot: str) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO set_time_runs VALUES (?, ?, ?)", (bucket, person, slot))

    def _log(self, card: Card, kind: str, sender: str) -> None:
        self.log.add(self.clock(), card.bucket, card.room_id, sender, kind, card.title, sender_name=DESK_NAME if sender == DESK_NAME else "", job_id=card.job_id, item_id=card.item_id, ref=card.request_id)

    def _save(self, card: Card) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                f"""INSERT INTO cards ({", ".join(COLUMNS)}) VALUES ({", ".join("?" * len(COLUMNS))})
                    ON CONFLICT(request_id) DO UPDATE SET {", ".join(f"{name} = excluded.{name}" for name in COLUMNS[1:])}""",
                _row(card),
            )

    def _select(self, clause: str, *values: str) -> list[Card]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM cards {clause}", values).fetchall()
        return [_card(row) for row in rows]
