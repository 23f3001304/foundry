"""The action chain: everyone and every agent behind one flagged thing, with times. It opens for one flagged thing only, never for a person's history."""

import json
import logging
import re
from collections.abc import Collection, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from foundry.checks import numbers_in
from foundry.jobs import Job
from foundry.log import Entry, Log
from foundry.switch_client import DESK_NAME

logger = logging.getLogger(__name__)

DIRECT = "direct"
BY_VALUE = "matched by value"
# The one step with no label: it says that nothing matched.
NOTHING_MATCHED = ""
FOREVER = datetime.max.replace(tzinfo=UTC)

# A maker's source links sit beside the deck as <deck>.sources.json. A link the desk accepted is logged as a file_made entry whose ref is <path>|<entry id>.
SOURCES_SUFFIX = ".sources.json"
LINK_MARK = "|"
# What an agent may draw on besides its job's own entries: the asker's recent messages and the bucket's approved reports.
MEMORY = timedelta(days=30)
MOST_MESSAGES = 100

# What people said that a number can come from. voice_heard is left out, because the message it became carries the same words.
SAID = ("message", "voice_corrected", "item_answer", "item_passed_on", "revision_notes")
# The markers the desk logs for agents.
BRIEF_READY = "BRIEF_READY"
REVIEW_PASS = "REVIEW_PASS"

WHAT = {
    "message": "said",
    "voice_corrected": "corrected what was heard",
    "item_answer": "answered",
    "item_passed_on": "passed on an answer",
    "revision_notes": "asked for changes",
    "report_approved": "is in the approved report",
}
RECORDED = "sent a voice note"
HEARD = "heard"
CONFIRMED = "confirmed what was heard"
NOT_CONFIRMED = "not confirmed"
NOBODY_CONFIRMED = "Nobody has said these words are right."
BRIEF_WRITTEN = "wrote the brief"
CLEANED = "cleaned up the note"
MADE = "made the file"
USED = "used it in the file"
PASSED = "passed the review"
SENT_BACK = "sent it back"
SIGNED_OFF = "signed off"
DELIVERED = "delivered"
NO_SOURCE = "no source found"
NO_SOURCE_DETAIL = "No entry for this job gives {needle}."
NOT_FLAGGED = "Entry {entry_id} is not a flagged item."
NOT_A_TARGET = "Cannot flag {target!r}. It is not a file made for this job, a number or statement in one, or an entry in this log."
SOURCE_LINE = "Source: {parts}"
TIME_OF_DAY = re.compile(r"\d{1,2}:\d{2}\s*[ap]m", re.IGNORECASE)

FILE, TEXT, ENTRY = "file", "text", "entry"


class NotFlagged(Exception):
    pass


@dataclass(frozen=True)
class Step:
    at: datetime
    who: str
    what: str
    detail: str
    label: str


@dataclass(frozen=True)
class Link:
    """One number on one slide and the entry its maker says it came from."""

    slide: int
    value: str
    entry: int
    label: str


@dataclass(frozen=True)
class Target:
    kind: str
    path: str = ""
    needle: str = ""
    entry: int = 0


def names(log: Log, bucket: str) -> dict[str, str]:
    # The name each sender last wrote under in this bucket. Some entries, such as an answered card, are logged with the sender's id and no name.
    return {writer.sender: writer.sender_name for writer in log.writers(bucket) if writer.sender_name}


def name_of(entry: Entry, known: dict[str, str]) -> str:
    return entry.sender_name or known.get(entry.sender) or entry.sender


def _number(text: str) -> int | None:
    return int(text) if text.isascii() and text.isdigit() else None


def _ids(ref: str | None) -> list[int]:
    return [number for part in (ref or "").split(",") if (number := _number(part.strip())) is not None]


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def carries(text: str, value: str) -> bool:
    # A number is there when every number in the value is in the text, however each is written. Words are there when they appear as written.
    if not value.strip():
        return False
    wanted = numbers_in(value)
    if wanted:
        return set(wanted) <= set(numbers_in(text))
    return _squash(value) in _squash(text)


def _same_value(first: str, second: str) -> bool:
    # Two short values, one from a maker and one from the person who flagged, that may be written differently.
    return carries(first, second) or carries(second, first)


# Source links


def source_line(links: Iterable[Link]) -> str:
    return SOURCE_LINE.format(parts="; ".join(f"{link.value} from {link.label}" for link in links))


def without_times_in_source_lines(text: str, links: list[Link]) -> str:
    # The line a deck prints under a slide says when a number was given, and a time of day is not a figure to check. The rest of the line is a maker's words, so it is checked.
    for slide in dict.fromkeys(link.slide for link in links):
        line = source_line(link for link in links if link.slide == slide)
        text = text.replace(line, TIME_OF_DAY.sub("", line))
    return text


def link_ref(path: str, entry_id: int) -> str:
    return f"{path}{LINK_MARK}{entry_id}"


def _linked(entry: Entry) -> tuple[str, int] | None:
    path, mark, tail = (entry.ref or "").rpartition(LINK_MARK)
    number = _number(tail) if mark and entry.kind == "file_made" else None
    return (path, number) if number is not None else None


def write_links(path: str | Path, links: list[Link]) -> None:
    file = Path(f"{path}{SOURCES_SUFFIX}")
    if links:
        file.write_text(json.dumps([asdict(link) for link in links], indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        # A deck made again without sources must not keep the links of the one before.
        file.unlink(missing_ok=True)


def _whole(number: object) -> bool:
    return isinstance(number, int) and not isinstance(number, bool)


def _link_from(item: object) -> Link | None:
    if not isinstance(item, dict):
        return None
    slide, value, entry, label = (item.get(name) for name in ("slide", "value", "entry", "label"))
    if _whole(slide) and _whole(entry) and isinstance(value, str) and isinstance(label, str):
        return Link(slide, value, entry, label)
    return None


def read_links(path: str | Path) -> list[Link]:
    try:
        data = json.loads(Path(f"{path}{SOURCES_SUFFIX}").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as error:
        # A file nested deeper than the parser can follow raises RecursionError, which is not a ValueError.
        logger.warning("Could not read the source links for %s: %s", Path(path).name, error)
        return []
    if not isinstance(data, list):
        logger.warning("The source links for %s are not a list.", Path(path).name)
        return []
    return [link for item in data if (link := _link_from(item)) is not None]


def visible_entries(log: Log, job: Job, now: datetime) -> list[Entry]:
    # What a job's makers may read and cite: its own entries, the bucket's approved reports and what its asker wrote in its room lately.
    since = now - MEMORY
    own = log.for_job(job.bucket, job.id)
    reports = log.between(job.bucket, since, now, kinds=["report_approved"])
    asked = [entry for entry in log.between(job.bucket, since, now, kinds=["message"], room_id=job.room_id) if entry.sender == job.requester]
    chosen = {entry.id: entry for entry in [*own, *reports, *asked[-MOST_MESSAGES:]]}
    return sorted(chosen.values(), key=lambda entry: (entry.at, entry.id))


# Flagging


def _made_paths(job: list[Entry]) -> set[str]:
    return {entry.ref for entry in job if entry.kind == "file_made" and entry.ref and LINK_MARK not in entry.ref}


def _parse(target: str, paths: Collection[str]) -> Target:
    kind, _, rest = target.partition(":")
    if kind == ENTRY and _number(rest) is not None:
        return Target(kind, entry=int(rest))
    if kind == FILE and rest in paths:
        return Target(kind, path=rest)
    if kind == TEXT:
        # A path can hold a colon, and so can a statement, so the path is whichever file of this job the target starts with.
        path = max((known for known in paths if rest.startswith(f"{known}:")), key=len, default=None)
        needle = rest[len(path) + 1:].strip() if path else ""
        if needle:
            return Target(kind, path, needle)
    raise ValueError(NOT_A_TARGET.format(target=target))


def _flag_text(target: Target) -> str:
    name = Path(target.path).name
    return {ENTRY: f"Flagged entry {target.entry}", FILE: f"Flagged {name}", TEXT: f"Flagged {target.needle} in {name}"}[target.kind]


def flag(log: Log, bucket: str, by: str, target: str, job_id: str, room_id: str, at: datetime) -> Entry:
    # The log only grows, so a flag that points at nothing is refused rather than kept.
    found = _parse(target, _made_paths(log.for_job(bucket, job_id)))
    if found.kind == ENTRY and log.get(bucket, found.entry) is None:
        raise ValueError(NOT_A_TARGET.format(target=target))
    return log.add(at, bucket, room_id, by, "flag", _flag_text(found), job_id=job_id, ref=target)


# The chain


# Each is the entry the desk logged for a link, and the number of the entry that link names.
Hits = list[tuple[Entry, int]]


@dataclass(frozen=True)
class Copy:
    """The newest copy of a file a maker made, and the links that copy came with."""

    made: Entry
    links: Hits


def _copies(job: list[Entry]) -> dict[str, Copy]:
    copies: dict[str, Copy] = {}
    for entry in sorted(job, key=lambda entry: entry.id):
        if entry.kind != "file_made" or not entry.ref:
            continue
        if (found := _linked(entry)) is None:
            # A new copy starts again. The links of the one it replaced belong to work that was thrown away.
            copies[entry.ref] = Copy(entry, [])
        elif found[0] in copies:
            copies[found[0]].links.append((entry, found[1]))
    return copies


class _Trail:
    def __init__(self, log: Log, bucket: str, job: list[Entry]) -> None:
        self.log, self.bucket, self.job = log, bucket, job
        self.known = names(log, bucket)
        self.copies = _copies(job)
        self.steps: list[Step] = []
        self._seen: set[tuple[int, str]] = set()

    def follow(self, target: Target) -> list[Step]:
        sources, used = self._sources(target)
        for entry, label in sources:
            self._said(entry, label)
        since = min((step.at for step in self.steps), default=None)
        if since is not None:
            self._upstream(since, bool(used))
        for path, hits in used.items():
            self._file(path, hits)
        if target.kind == TEXT and not sources:
            made = self.copies[target.path].made
            self._add(made, NO_SOURCE, NO_SOURCE_DETAIL.format(needle=target.needle), NOTHING_MATCHED, who=DESK_NAME)
        if used:
            self._reviews(min(self.copies[path].made.id for path in used))
        self._delivery(used)
        # Steps made at the same moment keep the order they were found in.
        return sorted(self.steps, key=lambda step: step.at)

    def _sources(self, target: Target) -> tuple[list[tuple[Entry, str]], dict[str, Hits]]:
        # The entries behind the flagged thing, and the files whose links say they used them.
        if target.kind == ENTRY:
            found = self.log.get(self.bucket, target.entry)
            used = {path: hits for path, copy in self.copies.items() if (hits := [pair for pair in copy.links if pair[1] == target.entry])}
            return ([(found, DIRECT)] if found else []), used
        copy = self.copies[target.path]
        if target.kind == FILE:
            return self._named(copy.links), {target.path: copy.links}
        hits = [pair for pair in copy.links if _same_value(target.needle, pair[0].text)]
        if hits:
            return self._named(hits), {target.path: hits}
        # With no link, every entry of this job that gives the value is shown, and labelled as a guess.
        return [(entry, BY_VALUE) for entry in self._candidates() if carries(entry.text, target.needle)], {target.path: []}

    def _named(self, links: Hits) -> list[tuple[Entry, str]]:
        named = (self.log.get(self.bucket, entry_id) for entry_id in dict.fromkeys(entry_id for _, entry_id in links))
        return [(entry, DIRECT) for entry in named if entry is not None]

    def _candidates(self) -> list[Entry]:
        # This job's own words and the messages that opened it, never the rest of the log.
        opening = [self.log.get(self.bucket, entry_id) for entry in self.job if entry.kind == "job_opened" for entry_id in _ids(entry.ref)]
        chosen = {entry.id: entry for entry in [*opening, *self.job] if entry is not None and entry.kind in SAID}
        return sorted(chosen.values(), key=lambda entry: entry.id)

    def _add(self, entry: Entry, what: str, detail: str, label: str, who: str | None = None) -> None:
        if (entry.id, what) not in self._seen:
            self._seen.add((entry.id, what))
            self.steps.append(Step(entry.at, who or name_of(entry, self.known), what, detail, label))

    def _said(self, entry: Entry, label: str) -> None:
        notes = self._heard(entry)
        if not notes:
            self._add(entry, WHAT.get(entry.kind, entry.kind.replace("_", " ")), entry.text, label)
        for note in notes:
            self._add(note, RECORDED, "", label)
            self._add(note, HEARD, note.text, label, who=DESK_NAME)
            self._approvals(note, label)

    def _heard(self, entry: Entry) -> list[Entry]:
        if entry.kind == "voice_heard":
            return [entry]
        notes = (self.log.get(self.bucket, entry_id) for entry_id in _ids(entry.ref)) if entry.kind == "message" else ()
        return [note for note in notes if note is not None and note.kind == "voice_heard"]

    def _approvals(self, note: Entry, label: str) -> None:
        # A voice note is unconfirmed when no confirmation or correction points at it. Nothing else marks it.
        answers = [entry for entry in self.log.between(self.bucket, note.at, FOREVER, kinds=("voice_confirmed", "voice_corrected")) if note.id in _ids(entry.ref)]
        for answer in answers:
            self._add(answer, CONFIRMED if answer.kind == "voice_confirmed" else WHAT[answer.kind], answer.text, label)
        if not answers:
            self._add(note, NOT_CONFIRMED, NOBODY_CONFIRMED, label)

    def _upstream(self, since: datetime, has_files: bool) -> None:
        # The clean-up and the agent that wrote the brief only count if they came after what was said.
        for entry in self.job:
            if entry.at < since:
                continue
            if entry.kind == "note_cleaned":
                self._add(entry, CLEANED, entry.text, DIRECT)
            elif has_files and entry.kind == "agent_marker" and entry.ref == BRIEF_READY:
                self._add(entry, BRIEF_WRITTEN, entry.text, DIRECT)

    def _file(self, path: str, hits: Hits) -> None:
        name = Path(path).name
        self._add(self.copies[path].made, MADE, name, DIRECT)
        for link, _ in hits:
            self._add(link, USED, f"{name}: {link.text}", DIRECT)

    def _reviews(self, first_made: int) -> None:
        for entry in self.job:
            if entry.kind == "review" and entry.id > first_made:
                self._add(entry, PASSED if entry.ref == REVIEW_PASS else SENT_BACK, entry.text, DIRECT)

    def _delivery(self, used: dict[str, Hits]) -> None:
        if self.copies and not used:
            # No file of this job used the flagged thing, so nothing the job delivered is behind it.
            return
        names = {Path(path).name for path in used}
        # A job that made no file is a report, and all it delivered is the report.
        sent = [entry for entry in self.job if entry.kind == "delivered" and (not self.copies or names & {name.strip() for name in entry.text.split(",")})]
        if not sent:
            return
        last = sent[-1]
        # The answer that came just before the delivery is the sign-off that let it go.
        answers = [entry for entry in self.job if entry.kind == "card_answered" and entry.id < last.id]
        if answers:
            self._add(answers[-1], SIGNED_OFF, answers[-1].text, DIRECT)
        self._add(last, DELIVERED, f"{last.text or 'the report'} to {last.room_id}", DIRECT)


def chain_for(log: Log, bucket: str, flag_id: int) -> list[Step]:
    flagged = log.get(bucket, flag_id)
    if flagged is None or flagged.kind != "flag":
        raise NotFlagged(NOT_FLAGGED.format(entry_id=flag_id))
    job = log.for_job(bucket, flagged.job_id) if flagged.job_id else []
    trail = _Trail(log, bucket, job)
    return trail.follow(_parse(flagged.ref or "", trail.copies))
