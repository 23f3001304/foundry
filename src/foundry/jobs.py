"""Job states and the transitions between them. The approval gates live here, not in agent prompts."""

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MAX_REVISION_ROUNDS = 3


class State(Enum):
    RECEIVED = "received"
    BRIEF_PENDING = "brief_pending"
    MAKING = "making"
    REVIEWING = "reviewing"
    SIGNOFF_PENDING = "signoff_pending"
    APPROVED = "approved"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


class IllegalTransition(Exception):
    pass


TRANSITIONS = {
    (State.RECEIVED, "brief_drafted"): State.BRIEF_PENDING,
    (State.BRIEF_PENDING, "brief_approved"): State.MAKING,
    (State.BRIEF_PENDING, "brief_revised"): State.RECEIVED,
    (State.MAKING, "work_ready"): State.REVIEWING,
    (State.REVIEWING, "review_passed"): State.SIGNOFF_PENDING,
    (State.REVIEWING, "review_failed"): State.MAKING,
    (State.SIGNOFF_PENDING, "signoff_approved"): State.APPROVED,
    (State.SIGNOFF_PENDING, "signoff_revised"): State.MAKING,
    (State.APPROVED, "delivered"): State.DELIVERED,
    (State.BLOCKED, "unblock"): State.MAKING,
}
REVISION_EVENTS = {"review_failed", "signoff_revised"}


@dataclass
class Job:
    id: str
    room_id: str
    requester: str
    approver: str
    state: State = State.RECEIVED
    revision_rounds: int = 0
    brief: str | None = None
    artifacts: list[str] = field(default_factory=list)
    approval: dict | None = None
    revision_notes: str | None = None
    waiting_on: list[str] = field(default_factory=list)

    @property
    def approval_room(self) -> str:
        return (self.approval or {}).get("room_id") or self.room_id


def advance(job: Job, event: str) -> Job:
    target = TRANSITIONS.get((job.state, event))
    if target is None:
        raise IllegalTransition(f"{event} is not allowed from {job.state.name}")
    if event in REVISION_EVENTS:
        job.revision_rounds += 1
        if job.revision_rounds > MAX_REVISION_ROUNDS:
            target = State.BLOCKED
    if event == "unblock":
        job.revision_rounds = 0
    job.state = target
    return job


COLUMNS = ("id", "room_id", "requester", "approver", "state", "revision_rounds", "brief", "artifacts", "approval", "revision_notes", "waiting_on")


class JobStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL, requester TEXT NOT NULL, approver TEXT NOT NULL,
                    state TEXT NOT NULL, revision_rounds INTEGER NOT NULL, brief TEXT, artifacts TEXT NOT NULL,
                    approval TEXT, revision_notes TEXT, waiting_on TEXT NOT NULL)"""
            )

    def create(self, room_id: str, requester: str, approver: str) -> Job:
        job = Job(id=uuid.uuid4().hex, room_id=room_id, requester=requester, approver=approver)
        self.save(job)
        return job

    def get(self, job_id: str) -> Job:
        rows = self._select("WHERE id = ?", job_id)
        if not rows:
            raise KeyError(job_id)
        return rows[0]

    def all(self) -> list[Job]:
        return self._select("ORDER BY rowid")

    def in_room(self, room_id: str) -> list[Job]:
        return self._select("WHERE room_id = ? ORDER BY rowid", room_id)

    def save(self, job: Job) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                f"""INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET {", ".join(f"{name} = excluded.{name}" for name in COLUMNS[1:])}""",
                (job.id, job.room_id, job.requester, job.approver, job.state.value,
                 job.revision_rounds, job.brief, json.dumps(job.artifacts), json.dumps(job.approval), job.revision_notes, json.dumps(job.waiting_on)),
            )

    def _select(self, clause: str, *values: str) -> list[Job]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM jobs {clause}", values).fetchall()
        return [Job(*row[:4], State(row[4]), row[5], row[6], json.loads(row[7]), json.loads(row[8]), row[9], json.loads(row[10])) for row in rows]
