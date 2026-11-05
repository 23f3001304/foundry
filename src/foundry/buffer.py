"""Holds one sender's quick messages until they go quiet, so several lines become one request."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class Burst:
    room_id: str
    sender: str
    text: str
    first_at: datetime
    language: str | None = None
    # The log entry of each message in the burst, in the order they were sent.
    entry_ids: list[int] = field(default_factory=list)
    # Where each message is held, so finishing the burst takes away those and not what was said after it was read.
    held: list[int] = field(default_factory=list, compare=False)


class MessageBuffer:
    def __init__(self, path: Path | str, quiet_seconds: int) -> None:
        self.path = str(path)
        self.quiet_seconds = quiet_seconds
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS waiting (room_id TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL, at REAL NOT NULL, language TEXT, entry_id INTEGER)")

    def add(self, room_id: str, sender: str, text: str, at: datetime, language: str | None = None, entry_id: int | None = None) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO waiting VALUES (?, ?, ?, ?, ?, ?)", (room_id, sender, text, at.timestamp(), language, entry_id))

    def ready(self, now: datetime) -> list[Burst]:
        # Read and left where it is. A burst is taken away by finish() once it has been handled, so one that could not be handled is still here next time.
        with closing(sqlite3.connect(self.path)) as db:
            quiet = db.execute(
                "SELECT room_id, sender FROM waiting GROUP BY room_id, sender HAVING MAX(at) <= ?",
                (now.timestamp() - self.quiet_seconds,),
            ).fetchall()
            bursts = []
            for room_id, sender in quiet:
                rows = db.execute(
                    "SELECT text, at, language, entry_id, rowid FROM waiting WHERE room_id = ? AND sender = ? ORDER BY at, rowid", (room_id, sender)
                ).fetchall()
                text = "\n".join(row[0] for row in rows)
                language = next((row[2] for row in reversed(rows) if row[2]), None)
                entry_ids = [row[3] for row in rows if row[3] is not None]
                bursts.append(Burst(room_id, sender, text, datetime.fromtimestamp(rows[0][1], UTC), language, entry_ids, [row[4] for row in rows]))
        return bursts

    def finish(self, burst: Burst) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany("DELETE FROM waiting WHERE rowid = ?", [(rowid,) for rowid in burst.held])
