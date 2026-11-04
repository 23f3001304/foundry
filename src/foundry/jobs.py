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
    COLLECTING = "collecting"
    REVIEWING = "reviewing"
    SIGNOFF_PENDING = "signoff_pending"
    APPROVED = "approved"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


class IllegalTransition(Exception):
    pass


TRANSITIONS = {
    (State.RECEIVED, "brief_drafted"): State.BRIEF_PENDING,
    (State.RECEIVED, "report_drafted"): State.SIGNOFF_PENDING,
    (State.MAKING, "report_drafted"): State.SIGNOFF_PENDING,
    (State.BRIEF_PENDING, "brief_approved"): State.MAKING,
    (State.BRIEF_PENDING, "brief_revised"): State.RECEIVED,
    # An approved brief that needs other people's input waits here until every item is closed.
    (State.MAKING, "collect"): State.COLLECTING,
    (State.COLLECTING, "inputs_closed"): State.MAKING,
    (State.MAKING, "work_ready"): State.REVIEWING,
    (State.MAKING, "stopped"): State.BLOCKED,
    (State.REVIEWING, "stopped"): State.BLOCKED,
    (State.REVIEWING, "review_passed"): State.SIGNOFF_PENDING,
    (State.REVIEWING, "review_failed"): State.MAKING,
    (State.SIGNOFF_PENDING, "signoff_approved"): State.APPROVED,
    (State.SIGNOFF_PENDING, "signoff_revised"): State.MAKING,
    (State.APPROVED, "delivered"): State.DELIVERED,
    # A note filed in a day's report that isn't built yet is cleaned again when its sender corrects it.
    (State.DELIVERED, "note_reopened"): State.RECEIVED,
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
    asked_at: str | None = None
    kind: str = "work"
    sent_at: str | None = None
    report: str | None = None
    language: str | None = None
    question: dict | None = None
    bucket: str = ""
    token: str = ""
    heard: str | None = None
    attention: list[str] = field(default_factory=list)
    # A sender's fix that came while an ask was out. It waits for that ask to come back, then goes out.
    pending_fix: str = ""

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


COLUMNS = ("id", "room_id", "requester", "approver", "state", "revision_rounds", "brief", "artifacts", "approval", "revision_notes", "waiting_on", "asked_at", "kind", "sent_at", "report", "language", "question", "bucket", "token", "heard", "attention", "pending_fix")


class JobStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL, requester TEXT NOT NULL, approver TEXT NOT NULL,
                    state TEXT NOT NULL, revision_rounds INTEGER NOT NULL, brief TEXT, artifacts TEXT NOT NULL,
                    approval TEXT, revision_notes TEXT, waiting_on TEXT NOT NULL, asked_at TEXT,
                    kind TEXT NOT NULL, sent_at TEXT, report TEXT, language TEXT, question TEXT,
                    bucket TEXT NOT NULL, token TEXT NOT NULL, heard TEXT, attention TEXT NOT NULL, pending_fix TEXT NOT NULL)"""
            )

    def create(self, room_id: str, requester: str, approver: str, bucket: str = "") -> Job:
        # A room with no client of its own is its own bucket.
        job = Job(id=uuid.uuid4().hex, room_id=room_id, requester=requester, approver=approver, bucket=bucket or room_id, token=uuid.uuid4().hex)
        self.save(job)
        return job

    def get(self, job_id: str) -> Job:
        rows = self._select("WHERE id = ?", job_id)
        if not rows:
            raise KeyError(job_id)
        return rows[0]

    def all(self) -> list[Job]:
        return self._select("ORDER BY rowid")

    def by_token(self, token: str) -> Job | None:
        rows = self._select("WHERE token = ?", token) if token else []
        return rows[0] if rows else None

    def in_room(self, room_id: str) -> list[Job]:
        return self._select("WHERE room_id = ? ORDER BY rowid", room_id)

    def save(self, job: Job) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                f"""INSERT INTO jobs VALUES ({", ".join("?" * len(COLUMNS))})
                    ON CONFLICT(id) DO UPDATE SET {", ".join(f"{name} = excluded.{name}" for name in COLUMNS[1:])}""",
                (job.id, job.room_id, job.requester, job.approver, job.state.value,
                 job.revision_rounds, job.brief, json.dumps(job.artifacts), json.dumps(job.approval), job.revision_notes, json.dumps(job.waiting_on), job.asked_at, job.kind, job.sent_at, job.report, job.language, json.dumps(job.question),
                 job.bucket, job.token, job.heard, json.dumps(job.attention), job.pending_fix),
            )

    def _select(self, clause: str, *values: str) -> list[Job]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM jobs {clause}", values).fetchall()
        return [Job(*row[:4], State(row[4]), row[5], row[6], json.loads(row[7]), json.loads(row[8]), row[9], json.loads(row[10]), *row[11:16], json.loads(row[16]), row[17], row[18], row[19], json.loads(row[20]), row[21]) for row in rows]
