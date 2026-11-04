"""The log: everything that reached or left Foundry, in time order, one bucket per client. It only grows."""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

KINDS = (
    "message", "voice_heard", "voice_confirmed", "voice_corrected", "job_opened", "card_opened", "card_answered", "agent_marker",
    "file_made", "review", "delivered", "note_cleaned", "report_approved", "item_asked", "item_reminded", "item_answer",
    "item_reason", "item_passed_on", "availability", "flag", "dashboard_action",
)
# What a person wrote or said in a room. Only these show that Foundry can reach them there.
WRITTEN = ("message", "voice_heard")
COLUMNS = ("id", "at", "bucket", "room_id", "sender", "sender_name", "kind", "text", "job_id", "item_id", "ref", "seeded")


@dataclass(frozen=True)
class Entry:
    id: int
    at: datetime
    bucket: str
    room_id: str
    sender: str
    sender_name: str
    kind: str
    text: str
    job_id: str | None
    item_id: str | None
    ref: str | None
    seeded: bool


@dataclass(frozen=True)
class Writer:
    sender: str
    sender_name: str
    room_id: str
    last_at: datetime


def _entry(row: tuple) -> Entry:
    return Entry(row[0], datetime.fromtimestamp(row[1], UTC), *row[2:11], bool(row[11]))


class Log:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, bucket TEXT NOT NULL, room_id TEXT NOT NULL,
                    sender TEXT NOT NULL, sender_name TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                    job_id TEXT, item_id TEXT, ref TEXT, seeded INTEGER NOT NULL)"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS entries_by_time ON entries (bucket, at)")
            db.execute("CREATE INDEX IF NOT EXISTS entries_by_job ON entries (bucket, job_id)")
            for change in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS entries_no_{change.lower()} BEFORE {change} ON entries BEGIN SELECT RAISE(ABORT, 'The log only grows.'); END")

    def add(self, at: datetime, bucket: str, room_id: str, sender: str, kind: str, text: str = "", *, sender_name: str = "", job_id: str | None = None, item_id: str | None = None, ref: str | None = None) -> Entry:
        return self._insert(False, at, bucket, room_id, sender, kind, text, sender_name, job_id, item_id, ref)

    def add_seeded(self, at: datetime, bucket: str, room_id: str, sender: str, kind: str, text: str = "", *, sender_name: str = "", job_id: str | None = None, item_id: str | None = None, ref: str | None = None) -> Entry:
        # Earlier history for a demo. Only scripts/seed_history.py may call this.
        return self._insert(True, at, bucket, room_id, sender, kind, text, sender_name, job_id, item_id, ref)

    def get(self, bucket: str, entry_id: int) -> Entry | None:
        rows = self._select("WHERE bucket = ? AND id = ?", bucket, entry_id)
        return rows[0] if rows else None

    def for_job(self, bucket: str, job_id: str) -> list[Entry]:
        return self._select("WHERE bucket = ? AND job_id = ? ORDER BY at, id", bucket, job_id)

    def between(self, bucket: str, since: datetime, until: datetime, kinds: Iterable[str] | None = None, room_id: str | None = None) -> list[Entry]:
        # Both ends count, so an entry made at the moment of asking is found.
        clause, values = "WHERE bucket = ? AND at >= ? AND at <= ?", [bucket, since.timestamp(), until.timestamp()]
        if kinds is not None:
            kinds = list(kinds)
            clause += f" AND kind IN ({', '.join('?' * len(kinds))})"
            values += kinds
        if room_id is not None:
            clause += " AND room_id = ?"
            values.append(room_id)
        return self._select(f"{clause} ORDER BY at, id", *values)

    def writers(self, bucket: str) -> list[Writer]:
        marks = ", ".join("?" * len(WRITTEN))
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                f"""SELECT sender, sender_name, room_id, at FROM entries AS e WHERE bucket = ? AND kind IN ({marks}) AND id = (
                        SELECT id FROM entries WHERE bucket = e.bucket AND sender = e.sender AND kind IN ({marks}) ORDER BY at DESC, id DESC LIMIT 1)
                    ORDER BY at DESC, id DESC""",
                (bucket, *WRITTEN, *WRITTEN),
            ).fetchall()
        return [Writer(sender, name, room_id, datetime.fromtimestamp(at, UTC)) for sender, name, room_id, at in rows]

    def last_answer(self, bucket: str, sender: str, measure: str) -> Entry | None:
        rows = self._select("WHERE bucket = ? AND sender = ? AND kind = 'item_answer' AND ref = ? ORDER BY at DESC, id DESC LIMIT 1", bucket, sender, measure)
        return rows[0] if rows else None

    def _insert(self, seeded: bool, at: datetime, bucket: str, room_id: str, sender: str, kind: str, text: str, sender_name: str, job_id: str | None, item_id: str | None, ref: str | None) -> Entry:
        if kind not in KINDS:
            raise ValueError(f"{kind} is not a kind of log entry")
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute(
                f"INSERT INTO entries ({', '.join(COLUMNS[1:])}) VALUES ({', '.join('?' * (len(COLUMNS) - 1))})",
                (at.timestamp(), bucket, room_id, sender, sender_name, kind, text, job_id, item_id, ref, int(seeded)),
            )
            entry_id = cursor.lastrowid
        return Entry(entry_id, at.astimezone(UTC), bucket, room_id, sender, sender_name, kind, text, job_id, item_id, ref, seeded)

    def _select(self, clause: str, *values: str | int | float) -> list[Entry]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM entries {clause}", values).fetchall()
        return [_entry(row) for row in rows]
