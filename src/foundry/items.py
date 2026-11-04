"""Who owes what: the items a job waits on, the OWES lines a brief carries, and the status built from them."""

import logging
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import Enum
from pathlib import Path

from foundry.text import quiet

logger = logging.getLogger(__name__)

OWES_FORMAT = "OWES: <person> | <input> | <measure> | <ISO 8601 due time>"
OWES_LINE = re.compile(r"[ \t]*OWES:(.*)")


class ItemState(Enum):
    OPEN = "open"
    ANSWERED = "answered"
    PASSED_ON = "passed_on"
    SKIPPED = "skipped"


# An item the asker went without is closed too, but nothing came in for it.
IN = (ItemState.ANSWERED, ItemState.PASSED_ON)


@dataclass
class Item:
    id: str
    job_id: str
    bucket: str
    owner: str
    owner_name: str
    room_id: str
    input: str
    measure: str
    due_at: datetime
    state: ItemState
    reason: str | None
    answer: str | None
    answer_entry: int | None
    asked_at: datetime | None
    reminded_at: datetime | None
    reachable: bool
    confirmed: bool
    # The item that took this one's place when the asker, or the owner, said to ask someone else.
    handed_to: str | None = None


@dataclass(frozen=True)
class Owed:
    owner_ref: str
    input: str
    measure: str
    due: datetime


def _owed_from(fields: str, zone: tzinfo) -> Owed | None:
    parts = [part.strip() for part in fields.split("|")]
    if len(parts) != 4:
        return None
    person, what, measure, due = parts
    if not what or not measure:
        return None
    try:
        when = datetime.fromisoformat(due)
    except ValueError:
        return None
    return Owed(person, what, measure, when if when.tzinfo else when.replace(tzinfo=zone))


def parse_owes(brief: str, zone: tzinfo = UTC) -> tuple[str, list[Owed]]:
    # A due time with no offset is read on the business clock. A line that can't be read stays in the brief, so the approver sees it.
    kept, owed = [], []
    for line in brief.split("\n"):
        match = OWES_LINE.fullmatch(line)
        found = _owed_from(match.group(1), zone) if match else None
        if found:
            owed.append(found)
            continue
        if match:
            logger.warning("Left a malformed OWES line in the brief: %s", line.strip())
        kept.append(line)
    if not owed:
        return brief, []
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), owed


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _handed_over(item: Item) -> bool:
    # Skipped because someone else was asked in its place, so it is neither owed nor gone without. Two owners asked for the same input are not each other's.
    return item.state is ItemState.SKIPPED and item.handed_to is not None


def going_without(items: list[Item]) -> list[Item]:
    return [item for item in items if item.state is ItemState.SKIPPED and not _handed_over(item)]


def status_line(items: list[Item]) -> str:
    # Built by code from the list, and everything people wrote in it is quieted here.
    items = [item for item in items if not _handed_over(item)]
    parts = [f"{sum(item.state in IN for item in items)} of {len(items)} in"]
    # An answer that came in by voice and was never confirmed is in, and the work used it, but nobody has said it is right.
    unsure = [quiet(item.owner_name) for item in items if item.state in IN and not item.confirmed]
    if unsure:
        parts[0] += f" (not confirmed: {_names(list(dict.fromkeys(unsure)))})"
    open_items = [item for item in items if item.state is ItemState.OPEN]
    # A voice answer nobody has confirmed yet is neither silence nor an answer.
    heard = [item for item in open_items if item.answer is not None and not item.confirmed]
    parts += [f'{quiet(item.owner_name)} said "{quiet(item.reason)}"' for item in open_items if item.reason and item not in heard]
    if heard:
        parts.append(f"waiting for {_names(list(dict.fromkeys(quiet(item.owner_name) for item in heard)))} to confirm what Foundry heard")
    silent = [quiet(item.owner_name) if item.owner_name else f"whoever owes {quiet(item.input)}" for item in open_items if not item.reason and item not in heard]
    if silent:
        parts.append(f"no reply to Foundry yet from {_names(list(dict.fromkeys(silent)))}")
    without = [quiet(item.input) for item in items if item.state is ItemState.SKIPPED]
    if without:
        parts.append(f"going without {_names(without)}")
    return ", ".join(parts)


COLUMNS = ("id", "job_id", "bucket", "owner", "owner_name", "room_id", "input", "measure", "due_at", "state", "reason", "answer", "answer_entry", "asked_at", "reminded_at", "reachable", "confirmed", "handed_to")


class ItemStore:
    """An item only counts as open once Foundry has asked about it. Until then it is a draft on a brief nobody has approved."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, bucket TEXT NOT NULL, owner TEXT NOT NULL, owner_name TEXT NOT NULL,
                    room_id TEXT NOT NULL, input TEXT NOT NULL, measure TEXT NOT NULL, due_at TEXT NOT NULL, state TEXT NOT NULL,
                    reason TEXT, answer TEXT, answer_entry INTEGER, asked_at TEXT, reminded_at TEXT, reachable INTEGER NOT NULL, confirmed INTEGER NOT NULL,
                    handed_to TEXT)"""
            )

    def create(self, job_id: str, bucket: str, owner: str, owner_name: str, room_id: str, input: str, measure: str, due_at: datetime, reachable: bool = True) -> Item:
        item = Item(uuid.uuid4().hex, job_id, bucket, owner, owner_name, room_id, input, measure, due_at, ItemState.OPEN, None, None, None, None, None, reachable, True)
        self.save(item)
        return item

    def get(self, item_id: str) -> Item:
        rows = self._select("WHERE id = ?", item_id)
        if not rows:
            raise KeyError(item_id)
        return rows[0]

    def for_job(self, job_id: str) -> list[Item]:
        return self._select("WHERE job_id = ? ORDER BY rowid", job_id)

    def open_for(self, owner: str, bucket: str) -> list[Item]:
        return self._select("WHERE owner = ? AND bucket = ? AND state = ? AND asked_at IS NOT NULL ORDER BY rowid", owner, bucket, ItemState.OPEN.value)

    def open_in(self, bucket: str) -> list[Item]:
        return self._select("WHERE bucket = ? AND state = ? AND asked_at IS NOT NULL ORDER BY rowid", bucket, ItemState.OPEN.value)

    def answered_for(self, owner: str, bucket: str) -> list[Item]:
        # Items this person has given an answer for, whether they gave it or the asker passed it on. A later answer replaces it.
        return self._select("WHERE owner = ? AND bucket = ? AND state IN (?, ?) ORDER BY rowid", owner, bucket, ItemState.ANSWERED.value, ItemState.PASSED_ON.value)

    def drop_unasked(self, job_id: str) -> None:
        # A new draft of a brief replaces the last one. An item Foundry has already asked about is never dropped.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM items WHERE job_id = ? AND asked_at IS NULL", (job_id,))

    def save(self, item: Item) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                f"""INSERT INTO items ({", ".join(COLUMNS)}) VALUES ({", ".join("?" * len(COLUMNS))})
                    ON CONFLICT(id) DO UPDATE SET {", ".join(f"{name} = excluded.{name}" for name in COLUMNS[1:])}""",
                (
                    item.id, item.job_id, item.bucket, item.owner, item.owner_name, item.room_id, item.input, item.measure, item.due_at.isoformat(), item.state.value,
                    item.reason, item.answer, item.answer_entry, _stamp(item.asked_at), _stamp(item.reminded_at), int(item.reachable), int(item.confirmed), item.handed_to,
                ),
            )

    def _select(self, clause: str, *values: str) -> list[Item]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM items {clause}", values).fetchall()
        return [_item(row) for row in rows]


def _stamp(when: datetime | None) -> str | None:
    return when.isoformat() if when else None


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _item(row: tuple) -> Item:
    return Item(*row[:8], datetime.fromisoformat(row[8]), ItemState(row[9]), *row[10:13], _when(row[13]), _when(row[14]), bool(row[15]), bool(row[16]), row[17])
