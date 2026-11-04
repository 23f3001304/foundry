"""The action chain: everyone and every agent behind one flagged thing, with times. It opens for one flagged thing only, never for a person's history."""

import json
import logging
import re
from collections.abc import Collection, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from foundry.checks import carries, entry_words, shown_words
from foundry.commands import VIA_DASHBOARD
from foundry.jobs import Job
from foundry.log import Entry, Log
from foundry.switch_client import DESK_NAME
from foundry.text import ROOM_OF

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
# What code worked out for a job, and the places it says it worked it out from: the rows of a file, or the log entries of a job's answers.
CALCULATION = "calculation"
ROWS, ENTRIES = "rows", "entries"
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
    CALCULATION: "worked out by code",
}
WORKED_FROM = "worked out from"
RECORDED = "sent a voice note"
HEARD = "heard"
CONFIRMED = "confirmed what was heard"
NOT_CONFIRMED = "not confirmed"
NOBODY_CONFIRMED = "Nobody has said these words are right."
BRIEF_WRITTEN = "wrote the brief"
CLEANED = "cleaned up the note"
NOTE_CLEANED = "note_cleaned"
WROTE = "wrote a note"
MADE = "made the file"
USED = "used it in the file"
PASSED = "passed the review"
SENT_BACK = "sent it back"
SIGNED_OFF = "signed off"
DELIVERED = "delivered"
ROOM_SET_FOR_IT = "the room set for it"
NO_SOURCE = "no source found"
NO_SOURCE_DETAIL = "No entry for this job gives {needle}."
NOT_FLAGGED = "Entry {entry_id} is not a flagged item."
MOST_FLAGGED_TEXT = 60
NOT_A_TARGET = "Cannot flag {target!r}. It is not a file made for this job, a number or statement in one, or an entry in this log."
SOURCE_LINE = "Source: {parts}"
HOUR, MINUTE = r"(?:[01]?\d|2[0-3])", r"[0-5]\d"
TIME = rf"\b{HOUR}(?::{MINUTE}(?::{MINUTE})?(?:\s*[ap]m\b)?|\s*[ap]m\b)(?:\s*UTC\b)?"
DATE = r"\b\d{4}-\d{2}-\d{2}\b"
# A date, a time of day, or both, the way job_facts prints them and the ways a maker might write them: 2026-11-04 18:12 UTC, 18:12, 6:12 pm, 6 pm.
WHEN = re.compile(rf"{DATE}(?:\s+{TIME})?|{TIME}", re.IGNORECASE)
MENTION_BREAK = "\u200b"

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


def plain(name: str) -> str:
    # A name as a maker copies it from job_facts: without the break after an @, with one space between words, and in any case.
    return " ".join(name.replace(MENTION_BREAK, "").split()).casefold()


def _number(text: str) -> int | None:
    return int(text) if text.isascii() and text.isdigit() else None


def _ids(ref: str | None) -> list[int]:
    return [number for part in (ref or "").split(",") if (number := _number(part.strip())) is not None]


def _same_value(first: str, second: str) -> bool:
    # Two short values, one from a maker and one from the person who flagged, that may be written differently.
    return carries(first, second) or carries(second, first)


# Source links


def source_line(links: Iterable[Link]) -> str:
    return SOURCE_LINE.format(parts="; ".join(dict.fromkeys(f"{link.value} from {link.label}" for link in links)))


def without_times_in_source_lines(text: str, links: list[Link]) -> str:
    # The line a deck prints under a slide says when a number was given, and a date or time of day is not a figure to check. The rest of the line is a maker's words, so it is checked.
    for slide in dict.fromkeys(link.slide for link in links):
        line = source_line(link for link in links if link.slide == slide)
        text = text.replace(line, WHEN.sub("", line))
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


def _flag_text(target: Target, said: Entry | None, known: dict[str, str], inputs_dir: Path | str | None = None) -> str:
    name = Path(target.path).name
    if said is not None:
        # A file somebody sent is named by its name, because the flag is read by people and the folder it is kept in is not for them.
        words = " ".join(shown_words(said, inputs_dir).split())
        return f"Flagged what {name_of(said, known)} said: {words if len(words) <= MOST_FLAGGED_TEXT else words[:MOST_FLAGGED_TEXT].rstrip() + '...'}"
    return {FILE: f"Flagged {name}", TEXT: f"Flagged {target.needle} in {name}"}[target.kind]


def flag(log: Log, bucket: str, by: str, target: str, job_id: str, room_id: str, at: datetime, inputs_dir: Path | str | None = None) -> Entry:
    # The log only grows, so a flag that points at nothing is refused rather than kept.
    found = _parse(target, _made_paths(log.for_job(bucket, job_id)))
    said = log.get(bucket, found.entry) if found.kind == ENTRY else None
    if found.kind == ENTRY and said is None:
        raise ValueError(NOT_A_TARGET.format(target=target))
    return log.add(at, bucket, room_id, by, "flag", _flag_text(found, said, names(log, bucket), inputs_dir), job_id=job_id, ref=target)


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
    def __init__(self, log: Log, bucket: str, job: list[Entry], inputs_dir: Path | str | None = None) -> None:
        self.log, self.bucket, self.job, self.inputs_dir = log, bucket, job, inputs_dir
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
        self._notes_behind()
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
        return [(entry, BY_VALUE) for entry in self._candidates() if carries(entry_words(entry, self.inputs_dir) or "", target.needle)], {target.path: []}

    def _named(self, links: Hits) -> list[tuple[Entry, str]]:
        named = (self.log.get(self.bucket, entry_id) for entry_id in dict.fromkeys(entry_id for _, entry_id in links))
        return [(entry, DIRECT) for entry in named if entry is not None]

    def _candidates(self) -> list[Entry]:
        # This job's own words and the messages that opened it, never the rest of the log.
        opening = [self.log.get(self.bucket, entry_id) for entry in self.job if entry.kind == "job_opened" for entry_id in _ids(entry.ref)]
        chosen = {entry.id: entry for entry in [*opening, *self.job] if entry is not None and entry.kind in (*SAID, CALCULATION)}
        return sorted(chosen.values(), key=lambda entry: entry.id)

    def _add(self, entry: Entry, what: str, detail: str, label: str, who: str | None = None) -> None:
        if (entry.id, what) not in self._seen:
            self._seen.add((entry.id, what))
            self.steps.append(Step(entry.at, who or name_of(entry, self.known), what, detail, label))

    def _calculated(self, entry: Entry, label: str) -> None:
        # What code worked out, and what it worked it out from: the people whose answers it used, or the rows of the file.
        self._add(entry, WHAT[CALCULATION], entry.text, label)
        kind, _, places = (entry.ref or "").partition(" ")
        if kind == ENTRIES:
            for entry_id in _ids(places):
                found = self.log.get(self.bucket, entry_id)
                if found is not None:
                    self._said(found, DIRECT)
        elif kind == ROWS and places:
            self._add(entry, WORKED_FROM, f"{ROWS} {places}", DIRECT)

    def _said(self, entry: Entry, label: str) -> None:
        if entry.kind == CALCULATION:
            self._calculated(entry, label)
            return
        notes = self._heard(entry)
        if not notes:
            self._add(entry, WHAT.get(entry.kind, entry.kind.replace("_", " ")), self._how(entry) if entry.kind == "revision_notes" else shown_words(entry, self.inputs_dir), label)
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
                # The desk cleans a note up, whoever wrote it.
                self._add(entry, CLEANED, entry.text, DIRECT, who=DESK_NAME)
            elif has_files and entry.kind == "agent_marker" and entry.ref == BRIEF_READY:
                self._add(entry, BRIEF_WRITTEN, entry.text, DIRECT)

    def _notes_behind(self) -> None:
        # A day's report has no words of its own. Behind it are the notes it was made from: the ones the approved report lists, or failing that the ones that opened it.
        listed = [entry for kind in ("report_approved", "job_opened") for entry in self.job if entry.kind == kind and entry.ref]
        approved = [entry for entry in listed if entry.kind == "report_approved"]
        source = (approved or listed)[-1] if listed else None
        notes = (self.log.get(self.bucket, entry_id) for entry_id in _ids(source.ref)) if source else ()
        for note in notes:
            if note is not None and note.kind == NOTE_CLEANED:
                self._note(note)

    def _note(self, note: Entry) -> None:
        # What the writer said, as they said it, and then what clean-up made of it and why.
        opening = [self.log.get(self.bucket, entry_id) for entry in self.log.for_job(self.bucket, note.job_id) if entry.kind == "job_opened" for entry_id in _ids(entry.ref)] if note.job_id else []
        said = [entry for entry in opening if entry is not None and entry.kind == "message"]
        for entry in said:
            self._said(entry, DIRECT)
        if not said:
            self._add(note, WROTE, "", DIRECT)
        self._add(note, CLEANED, note.text, DIRECT, who=DESK_NAME)

    def _file(self, path: str, hits: Hits) -> None:
        name = Path(path).name
        self._add(self.copies[path].made, MADE, name, DIRECT)
        # The same number on two slides is one use of it.
        for link in {(link.text, entry_id): link for link, entry_id in hits}.values():
            self._add(link, USED, f"{name}: {link.text}", DIRECT)

    def _reviews(self, first_made: int) -> None:
        for entry in self.job:
            if entry.kind == "review" and entry.id > first_made:
                self._add(entry, PASSED if entry.ref == REVIEW_PASS else SENT_BACK, entry.text, DIRECT)

    def _how(self, entry: Entry) -> str:
        # The desk logs a dashboard answer beside the card's own answer, and the changes asked for with it, all under the same card.
        here = bool(entry.ref) and any(other.kind == "dashboard_action" and other.ref == entry.ref for other in self.job)
        return f"{entry.text} ({VIA_DASHBOARD})" if here else entry.text

    def _delivery(self, used: dict[str, Hits]) -> None:
        if self.copies and not used:
            # No file of this job used the flagged thing, so nothing the job delivered is behind it.
            return
        files = {Path(path).name for path in used}
        # A job that made no file is a report, and all it delivered is the report.
        sent = [entry for entry in self.job if entry.kind == "delivered" and (not self.copies or files & {name.strip() for name in entry.text.split(",")})]
        if not sent:
            return
        last = sent[-1]
        # The answer that came just before the delivery is the sign-off that let it go.
        answers = [entry for entry in self.job if entry.kind == "card_answered" and entry.id < last.id]
        if answers:
            self._add(answers[-1], SIGNED_OFF, self._how(answers[-1]), DIRECT)
        self._add(last, DELIVERED, f"{last.text or 'the report'} to {self._room_of(last.room_id)}", DIRECT)

    def _room_of(self, room_id: str) -> str:
        # A room's id means nothing to a person, so a room goes by who spoke in it on this job.
        people = dict.fromkeys(name_of(entry, self.known) for entry in self.job if entry.room_id == room_id and entry.kind in SAID)
        return ROOM_OF.format(people=" and ".join(people)) if people else ROOM_SET_FOR_IT


def chain_for(log: Log, bucket: str, flag_id: int, inputs_dir: Path | str | None = None) -> list[Step]:
    flagged = log.get(bucket, flag_id)
    if flagged is None or flagged.kind != "flag":
        raise NotFlagged(NOT_FLAGGED.format(entry_id=flag_id))
    job = log.for_job(bucket, flagged.job_id) if flagged.job_id else []
    trail = _Trail(log, bucket, job, inputs_dir)
    return trail.follow(_parse(flagged.ref or "", trail.copies))
