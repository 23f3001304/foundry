"""Who may approve, and how an answer becomes a decision. Enforced in code, not in agent prompts."""

import logging
import re
import unicodedata
import uuid
from enum import Enum
from pathlib import Path

import httpx

from foundry.cards import ANSWERED, CARD_LIMIT, FILES, READ_ABOVE, CardQueue, Trigger, fit_detail, post_files  # noqa: F401
from foundry.jobs import Job, State
from foundry.switch_client import Outcome, SwitchClient

logger = logging.getLogger(__name__)

NONE_OF_THESE = "None of these, I'll give notes"


class Decision(Enum):
    APPROVE = "approve"
    REVISE = "revise"
    NOT_APPROVER = "not_approver"
    EXPIRED = "expired"
    NONE = "none"


ENDING_PUNCTUATION = ".,!;:।॥…"
REVISE_PATTERN = re.compile(r"\s*revise\s*:(.*)", re.IGNORECASE | re.DOTALL)
HOW_TO_ANSWER = "Reply yes to approve, or revise: <what to change>."
ASK_FOR_NOTES = "What should change? Reply with your notes."
ONLY_APPROVER = "Only the approver can answer this, so it is still waiting."


def _clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split()).rstrip(ENDING_PUNCTUATION).strip()


DEFAULT_WORDS = {
    **{_clean(word): Decision.APPROVE for word in (
        "yes", "ok", "okay", "approve", "approved", "haan", "han", "haan ji",
        "theek hai", "thik hai", "sahi hai", "हाँ", "हां", "हाँ जी", "हां जी", "ठीक है", "सही है",
    )},
    **{_clean(word): Decision.REVISE for word in ("no", "nahi", "नहीं")},
}


# Switch reads these as an answer to a card when they are the whole message, and parse_reply doesn't. Its full list is _DECISIONS in bridges/collaboration/session/text.py.
ONLY_SWITCH_READS = frozenset({"y", "n", "allow", "deny", "denied", "decline", "reject"})


def only_switch_reads(text: str) -> bool:
    return _clean(text) in ONLY_SWITCH_READS


def resolve_approver(requester: str, setting: str | None) -> str:
    return setting or requester


def parse_reply(text: str, extra_words: dict[str, Decision] | None = None) -> Decision:
    if REVISE_PATTERN.fullmatch(text):
        return Decision.REVISE
    words = DEFAULT_WORDS | {_clean(word): decision for word, decision in (extra_words or {}).items()}
    return words.get(_clean(text), Decision.NONE)


def revise_notes(text: str) -> str | None:
    match = REVISE_PATTERN.fullmatch(text)
    return (match.group(1).strip() or None) if match else None


class Gate:
    def __init__(self, client: SwitchClient, extra_words: dict[str, Decision] | None = None) -> None:
        self.client = client
        self.extra_words = extra_words

    def ask(self, job: Job, title: str, detail: str, room_id: str | None = None, files: list[str] | None = None, choices: list[str] | None = None) -> None:
        # The files go out with the card itself, on every platform, so the approver sees the work right where they answer.
        job.approval = {"request_id": f"{job.id}-{uuid.uuid4().hex[:8]}", "title": title, "detail": detail, "awaiting_notes": False, "room_id": room_id or job.room_id, "files": list(files or [])}
        if choices:
            # Each of the files as a choice, in their order, and a last one for none of them.
            job.approval["choices"] = [*choices, NONE_OF_THESE]
        job.revision_notes = None
        self._show(job)

    def check(self, job: Job, update: Outcome | dict) -> Decision:
        if job.approval is None:
            return Decision.NONE
        if isinstance(update, Outcome):
            return self._check_outcome(job, update)
        return self._check_message(job, update["payload"]["sender"], update["payload"]["body"])

    def _check_outcome(self, job: Job, outcome: Outcome) -> Decision:
        if outcome.request_id != job.approval["request_id"]:
            return Decision.NONE
        if outcome.state == "expired":
            title = job.approval["title"]
            self.client.post_message(job.approval_room, f"The approval for {title} ran out, so this job is on hold. {HOW_TO_ANSWER}")
            return Decision.EXPIRED
        if outcome.state != "answered":
            return Decision.NONE
        if outcome.answered_by != job.approver:
            self.ask(job, job.approval["title"], job.approval["detail"], job.approval_room, job.approval.get("files"), job.approval.get("choices", [])[:-1])
            return Decision.NOT_APPROVER
        if job.approval.get("choices"):
            return self._take_pick(job, outcome.chosen_from(job.approval["choices"]))
        if outcome.answer == "approve":
            return self._finish(job, Decision.APPROVE)
        return self._ask_for_notes(job)

    def _take_pick(self, job: Job, picked: str | None) -> Decision:
        # A pick card's choices are its files in order, then a last one for none of them. The file picked is the work, and nothing goes back to be made again.
        choices, files = job.approval["choices"], job.approval.get("files", [])
        if picked is None or picked == NONE_OF_THESE or choices.index(picked) >= len(files):
            return self._ask_for_notes(job)
        job.artifacts = [files[choices.index(picked)]]
        return self._finish(job, Decision.APPROVE)

    def _picked_in(self, job: Job, text: str) -> str | None:
        # "I'll take mark 1" or the file's own name, typed instead of pressed.
        said = re.sub(r"[_\-.]+", " ", text.casefold())
        named = [choice for choice, path in zip(job.approval["choices"], job.approval.get("files", [])) if choice.casefold() in said or re.sub(r"[_\-.]+", " ", Path(path).stem.casefold()) in said]
        return named[0] if len(named) == 1 else None

    def _check_message(self, job: Job, sender: str, text: str) -> Decision:
        if job.approval.get("choices") and sender == job.approver and (picked := self._picked_in(job, text)):
            self._close(job)
            return self._take_pick(job, picked)
        decision = parse_reply(text, self.extra_words)
        notes = revise_notes(text)
        if job.approval["awaiting_notes"]:
            if sender != job.approver:
                return Decision.NONE
            if decision is Decision.NONE:
                return self._finish(job, Decision.REVISE, text.strip())
            if decision is Decision.REVISE and notes is None:
                return Decision.NONE
            return self._finish(job, decision, notes)
        if decision is Decision.NONE:
            return Decision.NONE
        if sender != job.approver:
            self._refuse(job)
            return Decision.NOT_APPROVER
        self._close(job)
        if decision is Decision.REVISE and notes is None:
            return self._ask_for_notes(job)
        return self._finish(job, decision, notes)

    def _ask_for_notes(self, job: Job) -> Decision:
        job.approval["awaiting_notes"] = True
        self.client.post_message(job.approval_room, ASK_FOR_NOTES)
        return Decision.NONE

    def _finish(self, job: Job, decision: Decision, notes: str | None = None) -> Decision:
        job.approval = None
        job.revision_notes = notes
        return decision

    def _show(self, job: Job) -> None:
        raise NotImplementedError

    def _close(self, job: Job) -> None:
        raise NotImplementedError

    def _refuse(self, job: Job) -> None:
        raise NotImplementedError


class CardGate(Gate):
    def _show(self, job: Job) -> None:
        post_files(self.client, job.approval_room, job.approval.get("files", []))
        detail = fit_detail(self.client, job.approval_room, job.approval["detail"])
        self.client.open_card(job.approval_room, job.approval["request_id"], job.approval["title"], detail)

    def _close(self, job: Job) -> None:
        # Switch marks a closed card "Cancelled", so say the answer did arrive.
        try:
            self.client.close_card(job.approval["request_id"])
        except httpx.HTTPError as error:
            # A typed word has no retry, and a press on a card left open finds nothing waiting.
            logger.warning("Could not close the card for job %s: %s", job.id, error)
        self.client.post_message(job.approval_room, f"Got your answer on {job.approval['title']}.")

    def _refuse(self, job: Job) -> None:
        self.client.post_message(job.approval_room, ONLY_APPROVER)


class QueuedCardGate(CardGate):
    """Approvals wait their turn in the queue, under the same request id. The desk hands it the queue."""

    cards: CardQueue

    def _show(self, job: Job) -> None:
        approval = job.approval
        trigger = {State.BRIEF_PENDING: Trigger.BRIEF, State.BLOCKED: Trigger.STUCK}.get(job.state, Trigger.FINAL_WORK)
        # Nothing comes round to ask again about a job's answers once it has moved on, so a card Switch refuses stays in the queue, which also keeps its long text from being posted twice.
        keep = job.makes_nothing and job.state is State.SIGNOFF_PENDING
        self.cards.submit(trigger, job.approver, job.bucket, job.approval_room, approval["title"], approval["detail"], job_id=job.id, request_id=approval["request_id"], choices=approval.get("choices", ()), keep_refused=keep, data={FILES: approval.get("files", [])})

    def _close(self, job: Job) -> None:
        super()._close(job)
        if self.cards.get(job.approval["request_id"]) is not None:
            self.cards.finish(job.approval["request_id"], ANSWERED)


class ReplyGate(Gate):
    def _show(self, job: Job) -> None:
        self.client.post_message(job.approval_room, f"{job.approval['title']}\n\n{job.approval['detail']}\n\n{HOW_TO_ANSWER}")

    def _close(self, job: Job) -> None:
        pass

    def _refuse(self, job: Job) -> None:
        self._show(job)
