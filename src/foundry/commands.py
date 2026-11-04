"""What the dashboard asks the desk to do. The dashboard only writes these, and the desk applies them, so jobs and cards never have a second writer."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foundry.cards import ANSWERED, Card, Trigger
from foundry.coordinator import ASK_AGAIN, ASK_SOMEONE_ELSE, GO_WITHOUT
from foundry.jobs import Job
from foundry.switch_client import Outcome, _choice_ids

ACTIONS = ("answer_card", "ask_again", "ask_someone_else", "go_without", "restart", "flag", "reload_pack")
# The due-time card's buttons, which the jobs page offers as actions of their own. Their words are the coordinator's, because that is what the card says.
DUE_ACTIONS = {"ask_again": ASK_AGAIN, "ask_someone_else": ASK_SOMEONE_ELSE, "go_without": GO_WITHOUT}
# A card with no choices of its own is an approval, and these are its two answers.
APPROVE, REVISE = "approve", "revise"
LABELS = {APPROVE: "Approve", REVISE: "Ask for changes"}
# The cards that are a job's approval. Answered here the way a typed word is.
JOB_APPROVALS = {Trigger.BRIEF, Trigger.FINAL_WORK, Trigger.STUCK}
# Nothing here came from Switch, so there is nothing to acknowledge to it.
DASHBOARD_SESSION = "dashboard"
VIA_DASHBOARD = "via dashboard"

# Why the desk refused. The dashboard shows these as they are, so each says what happened in plain words.
NO_SUCH_CARD = "Foundry has no such card."
NOT_FOR_YOU = "That card is addressed to someone else, so you can't answer it here."
VOICE_IN_CHAT = "A voice note can only be approved by the person who sent it, in chat."
NOT_OPEN = "That card isn't open, so it wasn't answered. It may be waiting behind another card, or already answered."
NOT_A_CHOICE = "That isn't one of the card's choices."
CHANGES_IN_CHAT = "Asking for changes on this card is only possible in chat."
NOTES_NEEDED = "Say what should change."
NOT_YOUR_JOB = "Foundry has no such job."
NOT_THIS_CLIENT = "That belongs to a different client than the one this was asked for."
NOT_IN_THIS_JOB = "That isn't part of this job."
NOT_STUCK = "That job isn't stuck."
NO_DUE_CARD = "No due-time card is open for that job."
NOT_THE_APPROVER = "Only the person who approves this job can flag things in it."
COULD_NOT = "Foundry couldn't do that. Try again in a moment."
# What a command holds from the moment the desk takes it until the desk says how it went. A command that keeps it was taken and never finished, or finished and not recorded.
CLAIMED = "claimed"

ANSWERED_HERE = "Got your answer on {title}, from the dashboard."
LOG_ANSWERED = "Answered {title} with {choice} {via}"
LOG_RESTARTED = "Restarted the job {via}"
LOG_FLAGGED = "{flagged} {via}"
LOG_RELOADED = "Read the pack again {via}"

COLUMNS = ("id", "action", "payload", "login", "acts_as", "created_at", "done_at", "error")


class Refused(Exception):
    """The desk won't do this. The text is what the dashboard shows."""


@dataclass(frozen=True)
class Command:
    id: int
    action: str
    payload: dict
    login: str
    acts_as: str
    created_at: datetime
    done_at: datetime | None
    error: str | None


def _command(row: tuple) -> Command:
    return Command(row[0], row[1], json.loads(row[2]), row[3], row[4], datetime.fromisoformat(row[5]), datetime.fromisoformat(row[6]) if row[6] else None, row[7])


def still_waits_on(job: Job | None, card: Card) -> bool:
    # A try that ended the card and then failed saved nothing, so the job still names it. Until the job moves on, that card can be answered again.
    if job is None or card.state != ANSWERED:
        return False
    if job.approval and job.approval["request_id"] == card.request_id:
        # An approval a press in chat ended for its notes is waiting for those words, not for this answer.
        return not job.approval["awaiting_notes"]
    return bool(job.question and job.question["request_id"] == card.request_id)


def outcome_for(card: Card, choice: str, at: datetime) -> Outcome:
    # What Switch would have sent if the person had pressed this button in chat.
    if not card.choices:
        return Outcome(DASHBOARD_SESSION, card.request_id, "answered", choice, card.person, None, at)
    picked = [{"question_id": "answer", "selected_option_ids": [_choice_ids(card.choices)[card.choices.index(choice)]], "custom_text": None}]
    return Outcome(DASHBOARD_SESSION, card.request_id, "answered", None, card.person, picked, at)


class CommandStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, payload TEXT NOT NULL, login TEXT NOT NULL,
                    acts_as TEXT NOT NULL, created_at TEXT NOT NULL, done_at TEXT, error TEXT)"""
            )

    def add(self, action: str, payload: dict, login: str, acts_as: str) -> int:
        if action not in ACTIONS:
            raise ValueError(f"{action} is not something the dashboard can ask for")
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute(
                "INSERT INTO commands (action, payload, login, acts_as, created_at) VALUES (?, ?, ?, ?, ?)",
                (action, json.dumps(payload), login, acts_as, datetime.now(UTC).isoformat()),
            )
            return cursor.lastrowid

    def next(self) -> Command | None:
        rows = self._select("WHERE done_at IS NULL ORDER BY id LIMIT 1")
        return rows[0] if rows else None

    def claim(self, command_id: int) -> None:
        # Taken before the work, so it is never done twice. It reads as taken, and not as done, until done() says how it went.
        self._write(command_id, CLAIMED)

    def done(self, command_id: int, error: str | None = None) -> None:
        self._write(command_id, error)

    def _write(self, command_id: int, error: str | None) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE commands SET done_at = ?, error = ? WHERE id = ?", (datetime.now(UTC).isoformat(), error, command_id))

    def get(self, command_id: int) -> Command | None:
        rows = self._select("WHERE id = ?", command_id)
        return rows[0] if rows else None

    def recent(self, login: str, limit: int = 8) -> list[Command]:
        # Only what this login asked for, so nobody reads another person's actions.
        return self._select("WHERE login = ? ORDER BY id DESC LIMIT ?", login, limit)

    def _select(self, clause: str, *values: str | int) -> list[Command]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"SELECT {', '.join(COLUMNS)} FROM commands {clause}", values).fetchall()
        return [_command(row) for row in rows]
