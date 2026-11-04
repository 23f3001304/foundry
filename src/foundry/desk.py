"""foundry-desk: reads every room message, acts on approvals at once and turns quiet bursts into jobs."""

import asyncio
import logging
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx

from foundry.buffer import Burst, MessageBuffer
from foundry.cleanup import CleanupFailed, ReportStore, clean_note, signoff_detail
from foundry.brand import BrandError
from foundry.delivery import DELIVERED, deliver, deliver_report
from foundry.gates import Decision, Gate, parse_reply, resolve_approver
from foundry.intake import Kind, classify
from foundry.jobs import MAX_REVISION_ROUNDS, Job, JobStore, State, advance
from foundry.pack import Pack, load_pack
from foundry.stickers import branded_sticker, sticker_for
from foundry.switch_client import Outcome, SwitchClient
from foundry.voice import Transcript, VoiceError, speak, transcribe, translate

logger = logging.getLogger(__name__)

BRANDS = Path(__file__).resolve().parents[2] / "brands"
AGENT_SENDER_PREFIX = "@switch-agent-"
BRIEF_AGENT = "foundry-brief"
MAKERS = ("foundry-deck", "foundry-visual")
REVIEWER = "foundry-reviewer"
BRIEF_READY = "BRIEF_READY"
WORK_READY = "WORK_READY"
WORK_BLOCKED = "WORK_BLOCKED"
REVIEW_PASS = "REVIEW_PASS"
REVIEW_FAIL = "REVIEW_FAIL"
# A marker must start the message. The optional #tag names the job when a room has more than one.
# Agents sometimes address the desk before the marker, so a leading mention is allowed.
MARKER = re.compile(rf"(?:@\S+\s+)*({BRIEF_READY}|{WORK_READY}|{WORK_BLOCKED}|{REVIEW_PASS}|{REVIEW_FAIL})(?:\s+#(\w+))?(?:\s+(.*))?", re.DOTALL)
FILE_KINDS = {".pptx", ".png", ".jpg", ".jpeg", ".pdf"}
SIGNOFF = "Approve to deliver this work, or ask for changes."
HOW_TO_RESTART = "Approve to try again, or ask for changes to give new notes."
STUCK = f"This job has been through {MAX_REVISION_ROUNDS} rounds of changes, so it has stopped. {HOW_TO_RESTART}"
MAKER_STUCK = "The team cannot finish this as asked."
NO_BRIEF = "I could not get this request drafted into a brief. Please send it again."
RETRY = "A person asked to try this job again. If your file is still right, reply with the same path."
NOTHING_MADE = "Nobody made a file for this job. Make what the brief asks for."
ASK_WHAT_THEY_NEED = "Do you want something made from this? If so, tell me what you need."
USE_THE_BUTTONS = "More than one approval is waiting on you here. Please use the buttons on the card you mean."
CARD_AND_QUESTION = "A card and a question are both waiting on you here. Please press the button on the card, or answer the question in words."
RESEND_VOICE = "I couldn't read that voice note. Please resend it in under 30 seconds, or type it."
NO_REPORT = "I couldn't write that up just now. Send any reply to try again."
# A question left this long is dropped, so tomorrow's note isn't read as its answer.
QUESTION_WINDOW = timedelta(hours=24)
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


def headline(text: str) -> str:
    line = re.sub(r"[*_`#]", "", text.strip().splitlines()[0]).strip()
    return line.removeprefix("What is being made:").strip()[:80]


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
    sticker_mode: str = "subtle"
    work_timeout_minutes: int = 30
    packs: dict[str, Pack] = field(default_factory=dict)
    reports_path: Path | str = "foundry-reports.db"
    utc_offset_minutes: int = 330
    brands: dict[str, str] = field(default_factory=dict)

    def pack_for(self, room_id: str) -> Pack:
        return self.packs.get(room_id, Pack())

    def workrooms_for(self, room_id: str) -> Workrooms:
        return self.workrooms.get(room_id, Workrooms(room_id, room_id))

    def inside_rooms(self) -> set[str]:
        return {room for rooms in self.workrooms.values() for room in (rooms.studio, rooms.review)}

    def all_rooms(self) -> list[str]:
        return list(dict.fromkeys([*self.workrooms, *self.inside_rooms()]))

    @classmethod
    def from_env(cls) -> "Settings":
        workrooms = _rooms_from(os.environ.get("FOUNDRY_ROOMS", ""))
        return cls(
            buffer_path=os.environ.get("FOUNDRY_BUFFER_DB", "foundry-buffer.db"),
            quiet_seconds=int(os.environ.get("FOUNDRY_QUIET_SECONDS", "60")),
            approver=os.environ.get("FOUNDRY_APPROVER") or None,
            workrooms=workrooms,
            sticker_mode=os.environ.get("FOUNDRY_STICKER_MODE", "subtle"),
            work_timeout_minutes=int(os.environ.get("FOUNDRY_WORK_TIMEOUT_MINUTES", "30")),
            packs=_packs_from(os.environ.get("FOUNDRY_PACKS", "")),
            brands=_brands_from(os.environ.get("FOUNDRY_PACKS", ""), workrooms),
            reports_path=os.environ.get("FOUNDRY_REPORTS_DB", "foundry-reports.db"),
            utc_offset_minutes=int(os.environ.get("FOUNDRY_UTC_OFFSET_MINUTES", "330")),
        )


def _rooms_from(text: str) -> dict[str, Workrooms]:
    # outside:studio:review, comma-separated. Internal mode names its projects room twice.
    parts = [entry.strip().split(":") for entry in text.split(",") if entry.strip()]
    return {outside: Workrooms(studio, review) for outside, studio, review in parts}


def _named_brands(text: str) -> dict[str, str]:
    # room:brand-slug, comma-separated.
    return dict(entry.strip().split(":") for entry in text.split(",") if entry.strip())


def _packs_from(text: str) -> dict[str, Pack]:
    return {room: load_pack(BRANDS / slug) for room, slug in _named_brands(text).items()}


def _brands_from(text: str, workrooms: dict[str, Workrooms]) -> dict[str, str]:
    brands = _named_brands(text)
    inside = {room: brands[outside] for outside, rooms in workrooms.items() if outside in brands for room in (rooms.studio, rooms.review)}
    return brands | inside


class Desk:
    def __init__(
        self,
        client: SwitchClient,
        store: JobStore,
        gate: Gate,
        llm: Callable[[str], str],
        settings: Settings,
        transcriber: Callable[[bytes, str], Transcript] = transcribe,
        cleanup_llm: Callable[[str], str] | None = None,
        speaker: Callable[[str, str], bytes | None] = speak,
        translator: Callable[[str, str], str] = translate,
    ) -> None:
        self.clock = lambda: datetime.now(UTC)
        self.client = client
        self.store = store
        self.gate = gate
        self.llm = llm
        self.settings = settings
        self.transcriber = transcriber
        self.cleanup_llm = cleanup_llm
        self.speaker = speaker
        self.translator = translator
        self.buffer = MessageBuffer(settings.buffer_path, settings.quiet_seconds)
        self.reports = ReportStore(settings.reports_path)

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
        self._stop_quiet_jobs(now)

    def _stop_quiet_jobs(self, now: datetime) -> None:
        limit = timedelta(minutes=self.settings.work_timeout_minutes)
        for job in self.store.all():
            if job.kind != "work" or not job.asked_at or now - datetime.fromisoformat(job.asked_at) <= limit:
                continue
            if job.state is State.RECEIVED:
                # No brief has been approved, so there is nothing a person could restart yet.
                job.asked_at = None
                self.client.post_message(job.room_id, NO_BRIEF)
                self.store.save(job)
            elif job.state in (State.MAKING, State.REVIEWING):
                self._stop(job, f"Nobody on the team has answered for {self.settings.work_timeout_minutes} minutes.")

    def on_agent_message(self, event: dict) -> None:
        payload = event["payload"]
        match = MARKER.fullmatch(payload["body"].strip())
        if match is None:
            return
        marker, tag, text = match.group(1), match.group(2), (match.group(3) or "").strip()
        owners, state, room_kind = {
            BRIEF_READY: ((BRIEF_AGENT,), State.RECEIVED, "studio"),
            WORK_READY: (MAKERS, State.MAKING, "studio"),
            WORK_BLOCKED: (MAKERS, State.MAKING, "studio"),
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
        elif marker == WORK_BLOCKED:
            if agent in job.waiting_on:
                self._stop(job, text or MAKER_STUCK)
        elif marker == REVIEW_PASS:
            advance(job, "review_passed")
            job.asked_at = None
            self._ask_for_signoff(job)
            self.store.save(job)
        else:
            self._fail_round(job, text or "The reviewer gave no notes.")
            self.store.save(job)

    def _job_waiting(self, room_id: str, state: State, room_kind: str, tag: str | None) -> Job | None:
        for job in self.store.all():
            in_room = getattr(self.settings.workrooms_for(job.room_id), room_kind) == room_id
            if job.kind == "work" and job.state is state and in_room and (not tag or job.id.startswith(tag)):
                return job
        return None

    def _take_brief(self, job: Job, brief: str) -> None:
        if not brief:
            logger.warning("Ignored an empty brief for job %s", job.id)
            return
        job.brief = brief
        advance(job, "brief_drafted")
        self.gate.ask(job, f"Brief: {headline(brief)}", brief, self._approval_room(job))
        self._sticker(self._approval_room(job), "needs_input")
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

    def _stop(self, job: Job, reason: str) -> None:
        advance(job, "stopped")
        job.waiting_on, job.asked_at = [], None
        room = self._approval_room(job)
        self.gate.ask(job, f"Stuck: {self._title(job)}", f"{quiet(reason)} {HOW_TO_RESTART}", room)
        self._sticker(room, "blocked")
        self.store.save(job)

    def _fail_round(self, job: Job, notes: str) -> None:
        job.revision_notes = notes
        advance(job, "review_failed")
        self._after_changes(job)

    def _after_changes(self, job: Job) -> None:
        if job.state is State.BLOCKED:
            self.gate.ask(job, f"Stuck: {self._title(job)}", STUCK, self._approval_room(job))
            self._sticker(self._approval_room(job), "blocked")
        elif job.kind == "report":
            self._clean_report(job)
        else:
            self._ask_makers(job)

    def _title(self, job: Job) -> str:
        return headline(job.brief or "this job")

    def _approval_room(self, job: Job) -> str:
        # A named approver works inside, so a client never sees what they haven't been asked about.
        return job.room_id if job.approver == job.requester else self.settings.workrooms_for(job.room_id).studio

    def _ask_makers(self, job: Job, retry: bool = False) -> None:
        job.artifacts, job.waiting_on = [], list(MAKERS)
        job.asked_at = self.clock().isoformat()
        tag = job.id[:6]
        lines = [
            f"{' '.join(f'@{maker}' for maker in MAKERS)} Job #{tag}. Make your part of what this approved brief asks for.",
            f"When you finish, start your reply with {WORK_READY} #{tag}, then the absolute path of each file on its own line. If the brief needs nothing from you, reply with {WORK_READY} #{tag} alone.",
            f"Brief:\n{quiet(job.brief)}",
        ]
        if job.revision_notes:
            lines.append(f"Changes to make:\n{quiet(job.revision_notes)}")
        elif retry:
            lines.append(RETRY)
        self.client.post_message(self.settings.workrooms_for(job.room_id).studio, "\n\n".join(lines))

    def _ask_reviewer(self, job: Job) -> None:
        job.asked_at = self.clock().isoformat()
        tag = job.id[:6]
        files = "\n".join(job.artifacts)
        last_round = f"Changes asked for last round:\n{quiet(job.revision_notes)}\n\n" if job.revision_notes else ""
        self.client.post_message(
            self.settings.workrooms_for(job.room_id).review,
            f"@{REVIEWER} Job #{tag}. Check this work against the approved brief and the brand kit.\n\n"
            f"Start your reply with {REVIEW_PASS} #{tag} if it meets both, or with {REVIEW_FAIL} #{tag}, then notes a maker can act on.\n\n"
            f"Brief:\n{quiet(job.brief)}\n\n{last_round}Files:\n{files}",
        )

    def _ask_for_signoff(self, job: Job) -> None:
        room = self._approval_room(job)
        for path in job.artifacts:
            self.client.post_file(room, path, f"For your sign-off: {Path(path).name}")
        self.gate.ask(job, f"Final work: {self._title(job)}", SIGNOFF, room)
        self._sticker(room, "needs_input")

    def _deliver(self, job: Job) -> None:
        clean_run = job.revision_rounds == 0
        self._sticker(job.room_id, "approved")
        if job.kind == "report":
            deliver_report(job, self.client, self._report_rooms(job))
            self.reports.add(job.room_id, job.report)
            self._reply_aloud(job, job.report)
        else:
            deliver(job, self.client, job.room_id)
            self._reply_aloud(job, DELIVERED)
        self._sticker(job.room_id, "shipped")
        if clean_run:
            self._sticker(job.room_id, "celebrate")

    def _report_rooms(self, job: Job) -> list[str]:
        rooms = self.settings.workrooms_for(job.room_id)
        named = self.settings.pack_for(job.room_id).report_room
        other = {"studio": rooms.studio, "review": rooms.review}.get(named, named)
        return list(dict.fromkeys(room for room in (job.room_id, other) if room))

    def _reply_aloud(self, job: Job, text: str) -> None:
        if job.language:
            self._reply(job, text)

    def _reply(self, job: Job, text: str) -> None:
        # Someone who spoke hears the answer in their own language, with the words beside it.
        if not job.language:
            self.client.post_message(job.room_id, text)
            return
        try:
            words = self.translator(text, job.language)
        except VoiceError as error:
            logger.warning("Could not translate a reply: %s", error)
            self.client.post_message(job.room_id, text)
            return
        try:
            audio = self.speaker(words, job.language)
            if audio is not None:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "reply.wav"
                    path.write_bytes(audio)
                    self.client.post_file(job.room_id, path, words)
                return
        except (VoiceError, httpx.HTTPError) as error:
            logger.warning("Could not send a spoken reply: %s", error)
        self.client.post_message(job.room_id, words)

    def _sticker_path(self, room_id: str, event: str) -> Path | None:
        brand = self.settings.brands.get(room_id)
        try:
            if brand:
                return branded_sticker(event, self.settings.sticker_mode, BRANDS / brand)
        except (OSError, BrandError) as error:
            logger.warning("Could not brand the %s sticker: %s", event, error)
        return sticker_for(event, self.settings.sticker_mode)

    def _sticker(self, room_id: str, event: str) -> None:
        path = self._sticker_path(room_id, event)
        if path is None:
            return
        try:
            self.client.post_file(room_id, path, "")
        except httpx.HTTPError as error:
            logger.warning("Could not send the %s sticker: %s", event, error)

    def _with_voice_as_text(self, event: dict) -> dict | None:
        payload = event["payload"]
        notes = [a for a in payload.get("attachments") or [] if a["mimetype"].startswith("audio/") or a["msgtype"] == "m.audio"]
        if not notes:
            return event
        caption = payload["body"].strip()
        heard = [caption] if caption and caption not in {note["filename"] for note in notes} else []
        language = None
        try:
            for note in notes:
                transcript = self.transcriber(self.client.download(event["room_id"], note), note["mimetype"])
                heard.append(transcript.text)
                language = transcript.language
        except (VoiceError, httpx.HTTPError) as error:
            logger.warning("Could not read a voice note: %s", error)
            self.client.post_message(event["room_id"], RESEND_VOICE)
            return None
        return {**event, "payload": {**payload, "body": "\n".join(heard), "spoken_language": language}}

    def _handle_person(self, event: dict) -> None:
        event = self._with_voice_as_text(event)
        if event is None:
            return
        payload = event["payload"]
        text = payload["body"].strip()
        if not text or self._answers_an_approval(event, text) or event["room_id"] in self.settings.inside_rooms():
            return
        at = datetime.fromtimestamp(payload["timestamp"] / 1000, UTC)
        self.buffer.add(event["room_id"], payload["sender"], text, at, payload.get("spoken_language"))
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
        at = datetime.fromtimestamp(event["payload"]["timestamp"] / 1000, UTC)
        asked = self._open_question(room_id, sender, at)
        if asked and not theirs:
            return False
        if asked:
            self.client.post_message(room_id, CARD_AND_QUESTION)
        elif len(theirs) > 1:
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
            self._sticker(self._approval_room(job), "revise")
            self._ask_for_brief(job)
        elif event == "unblock" and job.kind == "report":
            self._clean_report(job)
        elif event in ("brief_approved", "unblock"):
            self._sticker(self._approval_room(job), "working")
            self._ask_makers(job, retry=event == "unblock")
        elif event == "signoff_revised":
            self._sticker(self._approval_room(job), "revise")
            self._after_changes(job)
        elif event == "signoff_approved":
            self._deliver(job)
        self.store.save(job)

    def _take_burst(self, burst: Burst) -> None:
        asked = self._open_question(burst.room_id, burst.sender, burst.first_at)
        if asked:
            asked.brief += f"\nAnswered: {burst.text}"
            asked.language = burst.language or asked.language
            self._clean_report(asked)
            self.store.save(asked)
            return
        kind = classify(burst.text, self.llm, self.settings.pack_for(burst.room_id).update_rule)
        if kind is Kind.REPORT:
            self._start_report(burst)
        elif kind is Kind.REQUEST:
            job = self.store.create(burst.room_id, burst.sender, self._approver_for(burst))
            job.brief, job.language = burst.text, burst.language
            self.store.save(job)
            self._sticker(burst.room_id, "brief_received")
            self._ask_for_brief(job)
            self.store.save(job)
        elif kind is Kind.UNSURE:
            self.client.post_message(burst.room_id, ASK_WHAT_THEY_NEED)

    def _approver_for(self, burst: Burst) -> str:
        return resolve_approver(burst.sender, self.settings.pack_for(burst.room_id).approver or self.settings.approver)

    def _open_question(self, room_id: str, sender: str, now: datetime) -> Job | None:
        for job in reversed(self.store.in_room(room_id)):
            if job.kind == "report" and job.requester == sender and job.asked_at and now - datetime.fromisoformat(job.asked_at) <= QUESTION_WINDOW:
                return job
        return None

    def _start_report(self, burst: Burst) -> None:
        job = self.store.create(burst.room_id, burst.sender, self._approver_for(burst))
        local = timezone(timedelta(minutes=self.settings.utc_offset_minutes))
        job.kind, job.brief, job.sent_at, job.language = "report", burst.text, burst.first_at.astimezone(local).isoformat(), burst.language
        self.store.save(job)
        self._sticker(burst.room_id, "brief_received")
        self._clean_report(job)
        self.store.save(job)

    def _clean_report(self, job: Job) -> None:
        if job.revision_notes:
            job.brief += f"\n\nThe approver asked for these changes:\n{job.revision_notes}"
            job.revision_notes = None
        pack = self.settings.pack_for(job.room_id)
        earlier = "\n".join([pack.sources.get("reports", ""), *self.reports.recent(job.room_id)])
        try:
            result = clean_note(job.brief, datetime.fromisoformat(job.sent_at), replace(pack, sources={**pack.sources, "reports": earlier}), self.cleanup_llm or self.llm)
        except CleanupFailed as error:
            logger.warning("Could not clean up the note for job %s: %s", job.id, error)
            job.asked_at = self.clock().isoformat()
            self._reply(job, NO_REPORT)
            return
        if result.questions:
            question = "\n".join(result.questions)
            job.brief += f"\n\nAsked: {question}"
            job.asked_at = self.clock().isoformat()
            self._reply(job, quiet(question))
            return
        job.report, job.asked_at = quiet(result.text), None
        advance(job, "report_drafted")
        room = self._approval_room(job)
        self.gate.ask(job, f"Report: {headline(result.text)}", quiet(signoff_detail(result)), room)
        self._sticker(room, "needs_input")

    def _ask_for_brief(self, job: Job) -> None:
        job.asked_at = self.clock().isoformat()
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
