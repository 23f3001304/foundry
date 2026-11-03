"""foundry-desk: reads every room message, acts on approvals at once and turns quiet bursts into jobs."""

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foundry.buffer import Burst, MessageBuffer
from foundry.gates import Decision, Gate, parse_reply, resolve_approver
from foundry.intake import Kind, classify
from foundry.jobs import Job, JobStore, State, advance
from foundry.switch_client import Outcome, SwitchClient

logger = logging.getLogger(__name__)

AGENT_SENDER_PREFIX = "@switch-agent-"
BRIEF_AGENT = "foundry-brief"
BRIEF_READY = "BRIEF_READY"
ASK_WHAT_THEY_NEED = "Do you want something made from this? If so, tell me what you need."
USE_THE_BUTTONS = "More than one approval is waiting on you here. Please use the buttons on the card you mean."
DECISION_EVENTS = {
    (State.BRIEF_PENDING, Decision.APPROVE): "brief_approved",
    (State.BRIEF_PENDING, Decision.REVISE): "brief_revised",
    (State.SIGNOFF_PENDING, Decision.APPROVE): "signoff_approved",
    (State.SIGNOFF_PENDING, Decision.REVISE): "signoff_revised",
}


def sender_kind(payload: dict) -> str:
    # Switch often sends no kind on the live stream. Agent ids have a prefix no bridged person can get.
    if payload.get("sender_kind"):
        return payload["sender_kind"]
    return "agent" if payload["sender"].startswith(AGENT_SENDER_PREFIX) else "user"


@dataclass
class Settings:
    buffer_path: Path | str
    quiet_seconds: int = 60
    approver: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            buffer_path=os.environ.get("FOUNDRY_BUFFER_DB", "foundry-buffer.db"),
            quiet_seconds=int(os.environ.get("FOUNDRY_QUIET_SECONDS", "60")),
            approver=os.environ.get("FOUNDRY_APPROVER") or None,
        )


class Desk:
    def __init__(self, client: SwitchClient, store: JobStore, gate: Gate, llm: Callable[[str], str], settings: Settings) -> None:
        self.client = client
        self.store = store
        self.gate = gate
        self.llm = llm
        self.settings = settings
        self.buffer = MessageBuffer(settings.buffer_path, settings.quiet_seconds)

    def handle(self, event: dict | Outcome) -> None:
        if isinstance(event, Outcome):
            self._handle_outcome(event)
        elif event.get("type") != "message":
            return
        elif sender_kind(event["payload"]) == "user":
            self._handle_person(event)
        elif sender_kind(event["payload"]) == "agent":
            self.on_agent_message(event)

    def tick(self, now: datetime) -> None:
        for burst in self.buffer.ready(now):
            self._take_burst(burst)
        for outcome in self.client.outcomes():
            self._handle_outcome(outcome)

    def on_agent_message(self, event: dict) -> None:
        payload = event["payload"]
        body = payload["body"]
        if payload["sender_name"] != BRIEF_AGENT or not body.startswith(BRIEF_READY):
            return
        brief = body.removeprefix(BRIEF_READY).strip()
        job = next((job for job in self.store.in_room(event["room_id"]) if job.state is State.RECEIVED), None)
        if job is None or not brief:
            logger.warning("Ignored a brief with no text or no job waiting in room %s", event["room_id"])
            return
        job.brief = brief
        advance(job, "brief_drafted")
        self.gate.ask(job, f"Brief: {brief.splitlines()[0][:80]}", brief)
        self.store.save(job)

    def _handle_person(self, event: dict) -> None:
        payload = event["payload"]
        text = payload["body"].strip()
        if not text or self._answers_an_approval(event, text):
            return
        at = datetime.fromtimestamp(payload["timestamp"] / 1000, UTC)
        self.buffer.add(event["room_id"], payload["sender"], text, at)
        if self.settings.quiet_seconds == 0:
            self.tick(at)

    def _answers_an_approval(self, event: dict, text: str) -> bool:
        room_id, sender = event["room_id"], event["payload"]["sender"]
        waiting = [job for job in self.store.in_room(room_id) if job.approval]
        theirs = [job for job in waiting if job.approver == sender]
        for job in theirs:
            if job.approval["awaiting_notes"]:
                self._apply(job, self.gate.check(job, event))
                return True
        if parse_reply(text, self.gate.extra_words) is Decision.NONE:
            return False
        if len(theirs) > 1:
            self.client.post_message(room_id, USE_THE_BUTTONS)
        elif theirs or waiting:
            job = theirs[0] if theirs else waiting[-1]
            self._apply(job, self.gate.check(job, event))
        return True

    def _handle_outcome(self, outcome: Outcome) -> None:
        try:
            job = self.store.get(outcome.request_id.rsplit("-", 1)[0])
        except KeyError:
            logger.warning("Answer for an unknown job: %s", outcome.request_id)
        else:
            self._apply(job, self.gate.check(job, outcome))
        self.client.ack_outcome(outcome.session_id, outcome.request_id)

    def _apply(self, job: Job, decision: Decision) -> None:
        event = DECISION_EVENTS.get((job.state, decision))
        if event:
            advance(job, event)
        self.store.save(job)
        if event == "brief_revised":
            self._ask_for_brief(job)

    def _take_burst(self, burst: Burst) -> None:
        kind = classify(burst.text, self.llm)
        if kind is Kind.REQUEST:
            job = self.store.create(burst.room_id, burst.sender, resolve_approver(burst.sender, self.settings.approver))
            job.brief = burst.text
            self.store.save(job)
            self._ask_for_brief(job)
        elif kind is Kind.UNSURE:
            self.client.post_message(burst.room_id, ASK_WHAT_THEY_NEED)

    def _ask_for_brief(self, job: Job) -> None:
        lines = [
            f"@{BRIEF_AGENT} Draft a brief for this request. Start your reply with {BRIEF_READY}, then the brief.",
            f"Request:\n{job.brief}",
            f"Recent room messages:\n{self.client.read_context(job.room_id)}",
        ]
        if job.revision_notes:
            lines.append(f"The approver asked for these changes:\n{job.revision_notes}")
        self.client.post_message(job.room_id, "\n\n".join(lines))


async def run(desk: Desk, rooms: list[str], tick_seconds: float = 3) -> None:
    turn = asyncio.Lock()

    async def step(call: Callable, *args) -> None:
        async with turn:
            try:
                await asyncio.to_thread(call, *args)
            except Exception:
                logger.exception("Desk step failed")

    async def read() -> None:
        async for event in desk.client.events(rooms):
            await step(desk.handle, event)

    async def beat() -> None:
        while True:
            await asyncio.sleep(tick_seconds)
            await step(desk.tick, datetime.now(UTC))

    await asyncio.gather(read(), beat())
