"""foundry-desk: reads every room message, acts on approvals at once and turns quiet bursts into jobs."""

import asyncio
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from foundry.buffer import Burst, MessageBuffer
from foundry.gates import Decision, Gate, parse_reply, resolve_approver
from foundry.intake import Kind, classify
from foundry.jobs import MAX_REVISION_ROUNDS, Job, JobStore, State, advance
from foundry.switch_client import Outcome, SwitchClient
from foundry.voice import Transcript, VoiceError, transcribe

logger = logging.getLogger(__name__)

AGENT_SENDER_PREFIX = "@switch-agent-"
BRIEF_AGENT = "foundry-brief"
MAKERS = ("foundry-deck", "foundry-visual")
REVIEWER = "foundry-reviewer"
BRIEF_READY = "BRIEF_READY"
WORK_READY = "WORK_READY"
REVIEW_PASS = "REVIEW_PASS"
REVIEW_FAIL = "REVIEW_FAIL"
# A marker must start the message. The optional #tag names the job when a room has more than one.
MARKER = re.compile(rf"({BRIEF_READY}|{WORK_READY}|{REVIEW_PASS}|{REVIEW_FAIL})(?:\s+#(\w+))?(?:\s+(.*))?", re.DOTALL)
FILE_KINDS = {".pptx", ".png", ".jpg", ".jpeg", ".pdf"}
SIGNOFF = "Approve to deliver this work, or ask for changes."
STUCK = f"This job has been through {MAX_REVISION_ROUNDS} rounds of changes, so it has stopped. Approve to try again, or ask for changes to give new notes."
NOTHING_MADE = "Nobody made a file for this job. Make what the brief asks for."
ASK_WHAT_THEY_NEED = "Do you want something made from this? If so, tell me what you need."
USE_THE_BUTTONS = "More than one approval is waiting on you here. Please use the buttons on the card you mean."
RESEND_VOICE = "I couldn't read that voice note. Please resend it in under 30 seconds, or type it."
DECISION_EVENTS = {
    (State.BRIEF_PENDING, Decision.APPROVE): "brief_approved",
    (State.BRIEF_PENDING, Decision.REVISE): "brief_revised",
    (State.SIGNOFF_PENDING, Decision.APPROVE): "signoff_approved",
    (State.SIGNOFF_PENDING, Decision.REVISE): "signoff_revised",
    (State.BLOCKED, Decision.APPROVE): "unblock",
    (State.BLOCKED, Decision.REVISE): "unblock",
}


def sender_kind(payload: dict) -> str:
    # Switch often sends no kind on the live stream. Agent ids have a prefix no bridged person can get.
    if payload.get("sender_kind"):
        return payload["sender_kind"]
    return "agent" if payload["sender"].startswith(AGENT_SENDER_PREFIX) else "user"


def quiet(text: str | None) -> str:
    # What people wrote must not wake an agent when the desk passes it on.
    return (text or "").replace("@", "@\u200b")


def deliverable(path: str) -> bool:
    file = Path(path)
    return file.is_absolute() and file.suffix.lower() in FILE_KINDS and file.is_file()


def file_paths(text: str) -> list[str]:
    return [path for line in text.splitlines() for path in ([line.strip()] if deliverable(line.strip()) else line.split())]


@dataclass(frozen=True)
class Workrooms:
    studio: str
    review: str


@dataclass
class Settings:
    buffer_path: Path | str
    quiet_seconds: int = 60
    approver: str | None = None
    workrooms: dict[str, Workrooms] = field(default_factory=dict)

    def workrooms_for(self, room_id: str) -> Workrooms:
        return self.workrooms.get(room_id, Workrooms(room_id, room_id))

    def inside_rooms(self) -> set[str]:
        return {room for rooms in self.workrooms.values() for room in (rooms.studio, rooms.review)}

    def all_rooms(self) -> list[str]:
        return list(dict.fromkeys([*self.workrooms, *self.inside_rooms()]))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            buffer_path=os.environ.get("FOUNDRY_BUFFER_DB", "foundry-buffer.db"),
            quiet_seconds=int(os.environ.get("FOUNDRY_QUIET_SECONDS", "60")),
            approver=os.environ.get("FOUNDRY_APPROVER") or None,
            workrooms=_rooms_from(os.environ.get("FOUNDRY_ROOMS", "")),
        )


def _rooms_from(text: str) -> dict[str, Workrooms]:
    # outside:studio:review, comma-separated. Internal mode names its projects room twice.
    parts = [entry.strip().split(":") for entry in text.split(",") if entry.strip()]
    return {outside: Workrooms(studio, review) for outside, studio, review in parts}


class Desk:
    def __init__(
        self,
        client: SwitchClient,
        store: JobStore,
        gate: Gate,
        llm: Callable[[str], str],
        settings: Settings,
        transcriber: Callable[[bytes, str], Transcript] = transcribe,
    ) -> None:
        self.client = client
        self.store = store
        self.gate = gate
        self.llm = llm
        self.settings = settings
        self.transcriber = transcriber
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
        match = MARKER.fullmatch(payload["body"].strip())
        if match is None:
            return
        marker, tag, text = match.group(1), match.group(2), (match.group(3) or "").strip()
        owners, state, room_kind = {
            BRIEF_READY: ((BRIEF_AGENT,), State.RECEIVED, "studio"),
            WORK_READY: (MAKERS, State.MAKING, "studio"),
            REVIEW_PASS: ((REVIEWER,), State.REVIEWING, "review"),
            REVIEW_FAIL: ((REVIEWER,), State.REVIEWING, "review"),
        }[marker]
        agent = payload["sender_name"]
        if agent not in owners:
            return
        job = self._job_waiting(event["room_id"], state, room_kind, tag)
        if job is None:
            logger.warning("Ignored %s from %s: no job is waiting for it in room %s", marker, agent, event["room_id"])
        elif marker == BRIEF_READY:
            self._take_brief(job, text)
        elif marker == WORK_READY:
            self._take_work(job, agent, text)
        elif marker == REVIEW_PASS:
            advance(job, "review_passed")
            self._ask_for_signoff(job)
            self.store.save(job)
        else:
            self._fail_round(job, text or "The reviewer gave no notes.")
            self.store.save(job)

    def _job_waiting(self, room_id: str, state: State, room_kind: str, tag: str | None) -> Job | None:
        for job in self.store.all():
            in_room = getattr(self.settings.workrooms_for(job.room_id), room_kind) == room_id
            if job.state is state and in_room and (not tag or job.id.startswith(tag)):
                return job
        return None

    def _take_brief(self, job: Job, brief: str) -> None:
        if not brief:
            logger.warning("Ignored an empty brief for job %s", job.id)
            return
        job.brief = brief
        advance(job, "brief_drafted")
        self.gate.ask(job, f"Brief: {brief.splitlines()[0][:80]}", brief, self._approval_room(job))
        self.store.save(job)

    def _take_work(self, job: Job, maker: str, text: str) -> None:
        if maker not in job.waiting_on:
            return
        paths = file_paths(text)
        refused = [path for path in paths if not deliverable(path)]
        if refused:
            kinds = ", ".join(sorted(FILE_KINDS))
            self.client.post_message(
                self.settings.workrooms_for(job.room_id).studio,
                f"@{maker} I can't use {', '.join(refused)}. Give the absolute path of each file, ending in {kinds}. Start your reply with {WORK_READY} #{job.id[:6]}.",
            )
            return
        job.artifacts += paths
        job.waiting_on.remove(maker)
        if not job.waiting_on:
            advance(job, "work_ready")
            if job.artifacts:
                self._ask_reviewer(job)
            else:
                self._fail_round(job, NOTHING_MADE)
        self.store.save(job)

    def _fail_round(self, job: Job, notes: str) -> None:
        job.revision_notes = notes
        advance(job, "review_failed")
        self._after_changes(job)

    def _after_changes(self, job: Job) -> None:
        if job.state is State.BLOCKED:
            self.gate.ask(job, f"Stuck: {self._title(job)}", STUCK, self._approval_room(job))
        else:
            self._ask_makers(job)

    def _title(self, job: Job) -> str:
        return (job.brief or "this job").splitlines()[0][:80]

    def _approval_room(self, job: Job) -> str:
        # A named approver works inside, so a client never sees what they haven't been asked about.
        return job.room_id if job.approver == job.requester else self.settings.workrooms_for(job.room_id).studio

    def _ask_makers(self, job: Job) -> None:
        job.artifacts, job.waiting_on = [], list(MAKERS)
        tag = job.id[:6]
        lines = [
            f"{' '.join(f'@{maker}' for maker in MAKERS)} Job #{tag}. Make your part of what this approved brief asks for.",
            f"When you finish, start your reply with {WORK_READY} #{tag}, then the absolute path of each file on its own line. If the brief needs nothing from you, reply with {WORK_READY} #{tag} alone.",
            f"Brief:\n{quiet(job.brief)}",
        ]
        if job.revision_notes:
            lines.append(f"Changes to make:\n{quiet(job.revision_notes)}")
        self.client.post_message(self.settings.workrooms_for(job.room_id).studio, "\n\n".join(lines))

    def _ask_reviewer(self, job: Job) -> None:
        tag = job.id[:6]
        files = "\n".join(job.artifacts)
        self.client.post_message(
            self.settings.workrooms_for(job.room_id).review,
            f"@{REVIEWER} Job #{tag}. Check this work against the approved brief and the brand kit.\n\n"
            f"Start your reply with {REVIEW_PASS} #{tag} if it meets both, or with {REVIEW_FAIL} #{tag}, then notes a maker can act on.\n\n"
            f"Brief:\n{quiet(job.brief)}\n\nFiles:\n{files}",
        )

    def _ask_for_signoff(self, job: Job) -> None:
        room = self._approval_room(job)
        for path in job.artifacts:
            self.client.post_file(room, path, f"For your sign-off: {Path(path).name}")
        self.gate.ask(job, f"Final work: {self._title(job)}", SIGNOFF, room)

    def _with_voice_as_text(self, event: dict) -> dict | None:
        payload = event["payload"]
        notes = [a for a in payload.get("attachments") or [] if a["mimetype"].startswith("audio/") or a["msgtype"] == "m.audio"]
        if not notes:
            return event
        caption = payload["body"].strip()
        heard = [caption] if caption and caption not in {note["filename"] for note in notes} else []
        try:
            for note in notes:
                heard.append(self.transcriber(self.client.download(event["room_id"], note), note["mimetype"]).text)
        except (VoiceError, httpx.HTTPError) as error:
            logger.warning("Could not read a voice note: %s", error)
            self.client.post_message(event["room_id"], RESEND_VOICE)
            return None
        return {**event, "payload": {**payload, "body": "\n".join(heard)}}

    def _handle_person(self, event: dict) -> None:
        event = self._with_voice_as_text(event)
        if event is None:
            return
        payload = event["payload"]
        text = payload["body"].strip()
        if not text or self._answers_an_approval(event, text) or event["room_id"] in self.settings.inside_rooms():
            return
        at = datetime.fromtimestamp(payload["timestamp"] / 1000, UTC)
        self.buffer.add(event["room_id"], payload["sender"], text, at)
        if self.settings.quiet_seconds == 0:
            self.tick(at)

    def _answers_an_approval(self, event: dict, text: str) -> bool:
        room_id, sender = event["room_id"], event["payload"]["sender"]
        waiting = [job for job in self.store.all() if job.approval and job.approval_room == room_id]
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
        if event == "brief_revised":
            self._ask_for_brief(job)
        elif event in ("brief_approved", "unblock"):
            self._ask_makers(job)
        elif event == "signoff_revised":
            self._after_changes(job)
        self.store.save(job)

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
            f"@{BRIEF_AGENT} Job #{job.id[:6]}. Draft a brief for this request. Start your reply with {BRIEF_READY} #{job.id[:6]}, then the brief.",
            f"Request:\n{quiet(job.brief)}",
            f"Recent room messages:\n{quiet(self.client.read_context(job.room_id))}",
        ]
        if job.revision_notes:
            lines.append(f"The approver asked for these changes:\n{quiet(job.revision_notes)}")
        self.client.post_message(self.settings.workrooms_for(job.room_id).studio, "\n\n".join(lines))


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
