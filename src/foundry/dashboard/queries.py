"""Everything the pages show, read from the files the desk writes. Each file is opened read-only for the one question asked, so a page can't change a job, a card or the log."""

import sqlite3
from collections.abc import Collection
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from foundry.cards import ANSWERED, CLOSED, EXPIRED, IN_ROUTINE, ONE_BY_ONE, OPEN, QUEUED, Card, Trigger, _card, _latest_slot, _waiting_since
from foundry.cards import COLUMNS as CARD_COLUMNS
from foundry.checks import shown_words
from foundry.chain import LINK_MARK, SAID, NotFlagged, Step, chain_for, name_of, names
from foundry.commands import CLAIMED, DUE_ACTIONS, JOB_APPROVALS, KIT, LABELS, NO_NAME, Command, CommandStore, is_data_file, plain_name, still_waits_on
from foundry.dashboard import data as brand_data
from foundry.dashboard.auth import User
from foundry.dashboard.gateway import Bridge, Room
from foundry.desk import Settings, approving_confirms_voice
from foundry.items import Item, ItemState, _item, desk_wrote, status_line
from foundry.items import COLUMNS as ITEM_COLUMNS
from foundry.jobs import Job, State, _job
from foundry.jobs import COLUMNS as JOB_COLUMNS
from foundry.log import Entry, Log
from foundry.text import headline

# The kinds of file the desk delivers. Nothing else is served, whatever the log says a maker made.
MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PICTURES = (".png", ".jpg", ".jpeg")

STAGES = {
    State.RECEIVED: ("Drafting the brief", "apprentice"),
    State.BRIEF_PENDING: ("Brief waiting for approval", "apprentice"),
    State.COLLECTING: ("Collecting inputs from people", "reviewer"),
    State.MAKING: ("Being made", "smith"),
    State.REVIEWING: ("Being checked by the reviewer", "reviewer"),
    State.SIGNOFF_PENDING: ("Work waiting for sign-off", "designer"),
    State.APPROVED: ("Approved, being delivered", "designer"),
    State.DELIVERED: ("Delivered", "designer"),
    State.BLOCKED: ("Stuck", "smith"),
    State.DROPPED: ("Nothing to send, every note was left out", "designer"),
}
REPORT_STAGES = {State.RECEIVED: "Writing the report", State.SIGNOFF_PENDING: "Report waiting for sign-off"}
NO_BRIEF = "No brief yet"
NO_OWNER = "Nobody named yet"
CARD_KINDS = {
    Trigger.BRIEF: "Brief for approval",
    Trigger.FINAL_WORK: "Final work for sign-off",
    Trigger.VOICE: "Check of a voice note",
    Trigger.QUESTION: "Question",
    Trigger.DUE: "Decision at the due time",
    Trigger.STUCK: "Stuck job",
    Trigger.REMINDER: "Reminder",
    Trigger.LATE_FIX: "Fix after work began",
    Trigger.DAILY_REPORT: "Daily report",
    Trigger.ATTENTION_NOTE: "Note that needs attention",
    Trigger.ALREADY_TOLD: "Already told",
}
EVENTS = {
    "message": "said",
    "voice_heard": "voice note, heard as",
    "voice_confirmed": "confirmed what was heard",
    "voice_corrected": "corrected what was heard",
    "job_opened": "request received",
    "card_opened": "card opened",
    "card_answered": "card answered",
    "agent_marker": "agent update",
    "file_made": "made a file",
    "review": "review",
    "delivered": "delivered",
    "note_cleaned": "cleaned up a note",
    "report_approved": "report approved",
    "item_asked": "asked for an input",
    "item_reminded": "reminded about an input",
    "item_answer": "answered an input",
    "item_reason": "gave a reason",
    "item_passed_on": "passed on an answer",
    "availability": "said when they are away",
    "flag": "flagged",
    "dashboard_action": "acted on the dashboard",
    "revision_notes": "asked for changes",
}
MOST_TEXT = 240
TONES = {State.BLOCKED: "stuck", State.DELIVERED: "done", State.DROPPED: "done", State.BRIEF_PENDING: "waiting", State.COLLECTING: "waiting", State.SIGNOFF_PENDING: "waiting"}
WORKING = "working"
# A page that grows with every job would soon be too long to read, so it shows the newest and says what it left out.
MOST_PAST_CARDS = 200
MOST_TIMELINES = 20
FILE_GONE = "The file is no longer on this machine."
NOT_FOR_VOICE = "Only the person who sent the note can approve this, in chat."
CONFIRMS_VOICE = "This card also confirms what Foundry heard in the voice note, so it is answered in chat. Asking for changes can be done here."
STILL_WAITING = "Answered, but the job did not move on. Try again."
NOBODY_ASKED = "Nobody has been asked yet."
WAITING_FOR = "Waiting for {name} to answer."
QUEUED_BEHIND = " It is queued behind another card."
WAITS_FOR_SET_TIME = " It waits for its set time."
AWAITS_SET_TIME = "Waits for its set time"
NO_REPLY = "No reply to Foundry yet"
NOT_ASKED = "Not asked yet"
CANT_REACH = "Foundry can't reach them yet"
ITEM_STATES = {ItemState.ANSWERED: "In", ItemState.PASSED_ON: "In, passed on by the asker", ItemState.SKIPPED: "Going without"}
DELIVERED = "delivered"
WAITING_FOR_FOUNDRY = "Waiting for Foundry"
DONE = "Done"
DIDNT_DO = "Foundry didn't do it: {error}"
# Taken by the desk with no result written, so it may or may not have happened.
NOT_RECORDED = "Foundry has this, outcome not recorded"
RUNNING = "Running"
NEEDS_ATTENTION = "Needs attention: {what}"
NOT_RUNNING = "Not running (Switch says: {status})"
NO_CONNECTION = "No connection to show."
NOT_ALL_YOURS = "It also has rooms Foundry doesn't link to a business, and removing it would delete those too. Use Switch's Gateway if you mean to."
CANT_SEE_ALL = "Foundry can only see some of the rooms on it, so it can't say what removing it would delete. Use Switch's Gateway if you mean to."
SHARED = "Other businesses use this connection too, so only its health is shown here. Use Switch's Gateway to change it."


# How long a page waits for a database the desk is writing. Short, so a locked file shows a plain page and doesn't hold everything else up.
READ_TIMEOUT = 2


def open_read_only(path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=READ_TIMEOUT)


class ReadOnlyLog(Log):
    """The log as the dashboard reads it: it never creates the file and can't add to it."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        return open_read_only(self.path)

    def _insert(self, *args) -> Entry:
        raise PermissionError("The dashboard only reads the log.")

    def find(self, entry_id: int) -> Entry | None:
        rows = self._select("WHERE id = ?", entry_id)
        return rows[0] if rows else None

    def of_kind(self, bucket: str, kind: str) -> list[Entry]:
        return self._select("WHERE bucket = ? AND kind = ? ORDER BY at DESC, id DESC", bucket, kind)


@dataclass
class Offer:
    """What this login may do about one card."""

    buttons: list[tuple[str, str]] = field(default_factory=list)
    changes: bool = False
    notice: str = ""


@dataclass
class Figures:
    bucket: str
    client: str
    waiting: int
    in_chat: int
    queued: int
    open_items: int
    stuck: int


@dataclass
class JobRow:
    id: str
    bucket: str
    client: str
    title: str
    stage: str
    sprite: str
    owes: str
    waiting: list[str]
    # How the stage reads at a glance: stuck, done, waiting on a person, or working.
    tone: str


@dataclass
class ItemRow:
    owner: str
    input: str
    measure: str
    due: str
    status: str


@dataclass
class FileRow:
    name: str
    entry_id: int
    picture: bool


@dataclass
class JobPage:
    row: JobRow
    brief: str
    report: str
    attention: list[str]
    items: list[ItemRow]
    answer: Card | None
    answer_offer: Offer
    restart: Offer
    due: Card | None
    due_offer: Offer
    files: list[FileRow]
    can_flag: bool


@dataclass
class CardRow:
    request_id: str
    client: str
    title: str
    detail: str
    kind: str
    status: str
    state: str
    offer: Offer


@dataclass
class Version:
    number: int
    entry_id: int
    made_by: str
    made_at: str
    status: str
    served: bool


@dataclass
class WorkFile:
    name: str
    picture: bool
    versions: list[Version]


@dataclass
class WorkJob:
    id: str
    client: str
    title: str
    stage: str
    files: list[WorkFile]
    tone: str


@dataclass
class Moment:
    at: str
    who: str
    what: str
    text: str
    target: tuple[str, int] | None


@dataclass
class JobLog:
    id: str
    client: str
    title: str
    stage: str
    moments: list[Moment]
    files: list[FileRow]
    can_flag: bool
    tone: str


@dataclass
class Flagged:
    id: int
    text: str
    who: str
    at: str
    client: str


@dataclass
class ChainPage:
    flagged: Flagged
    steps: list[Step]
    job_id: str
    job_title: str
    via_dashboard: bool


@dataclass
class Recent:
    what: str
    status: str
    failed: bool


@dataclass
class ConnectionRow:
    id: str
    # The id as it goes in an address.
    link: str
    name: str
    kind: str
    state: str
    healthy: bool
    # The names of this login's rooms on it, and nobody else's.
    rooms: list[str]
    # How many rooms Switch says are on it in all, and how many of them are not listed above: other rooms Foundry doesn't link to a business, or can't see.
    room_total: int
    unlisted: int
    # The businesses it serves, as buckets and as the names shown.
    serves: tuple[str, ...]
    clients: str
    removable: bool
    # Why it can't be removed here, when it can't.
    why_not: str
    # Other businesses use it too. Then only its health is shown: no rooms, no counts, and no way to remove it.
    shared: bool


@dataclass
class DataFile:
    file: str
    kind: str
    changed: datetime


@dataclass
class ClientData:
    bucket: str
    client: str
    link: str
    has_folder: bool
    has_kit: bool
    files: list[DataFile]


@dataclass
class DataView:
    bucket: str
    client: str
    link: str
    file: str
    kind: str
    text: str
    cut: bool


def bucket_name(bucket: str) -> str:
    # A brand goes by the name its kit gives it, and failing that its slug reads as its name. A room id with no brand is shown as it is.
    if not bucket.replace("-", "").replace("_", "").isalnum():
        return bucket
    return brand_data.kit_name(bucket) or bucket.replace("-", " ").replace("_", " ").title()


def title_of(job: Job) -> str:
    return headline(job.brief) if job.brief and job.brief.strip() else NO_BRIEF


def stage_of(job: Job) -> tuple[str, str]:
    stage, sprite = STAGES[job.state]
    return (REPORT_STAGES.get(job.state, stage) if job.kind == "report" else stage), sprite


def tone_of(job: Job) -> str:
    return TONES.get(job.state, WORKING)


def squeeze(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MOST_TEXT else f"{text[:MOST_TEXT].rstrip()}..."


def is_made_file(entry: Entry) -> bool:
    return entry.kind == "file_made" and bool(entry.ref) and LINK_MARK not in entry.ref


class Reader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = ReadOnlyLog(settings.log_path)
        self.zone = timezone(timedelta(minutes=settings.utc_offset_minutes))
        self.clock = lambda: datetime.now(UTC)

    # What is in the files

    def _rows(self, path: Path | str, sql: str, *values: str) -> list[tuple]:
        with closing(open_read_only(path)) as db:
            return db.execute(sql, values).fetchall()

    def jobs(self, buckets: Collection[str]) -> list[Job]:
        marks = ", ".join("?" * len(buckets))
        rows = self._rows(self.settings.jobs_path, f"SELECT {', '.join(JOB_COLUMNS)} FROM jobs WHERE bucket IN ({marks}) ORDER BY rowid DESC", *buckets)
        return [_job(row) for row in rows]

    def job_of(self, user: User, job_id: str) -> Job | None:
        rows = self._rows(self.settings.jobs_path, f"SELECT {', '.join(JOB_COLUMNS)} FROM jobs WHERE id = ?", job_id)
        job = _job(rows[0]) if rows else None
        # A job of another client is not found, so nobody can tell it exists.
        return job if job is not None and job.bucket in user.businesses else None

    def items(self, job_id: str) -> list[Item]:
        return [_item(row) for row in self._rows(self.settings.work_path, f"SELECT {', '.join(ITEM_COLUMNS)} FROM items WHERE job_id = ? ORDER BY rowid", job_id)]

    def cards(self, buckets: Collection[str]) -> list[Card]:
        marks = ", ".join("?" * len(buckets))
        rows = self._rows(self.settings.work_path, f"SELECT {', '.join(CARD_COLUMNS)} FROM cards WHERE bucket IN ({marks}) AND state != ? ORDER BY rowid DESC", *buckets, IN_ROUTINE)
        return [_card(row) for row in rows]

    def card(self, request_id: str) -> Card | None:
        rows = self._rows(self.settings.work_path, f"SELECT {', '.join(CARD_COLUMNS)} FROM cards WHERE request_id = ?", request_id)
        return _card(rows[0]) if rows else None

    def open_items(self, buckets: Collection[str]) -> dict[str, int]:
        marks = ", ".join("?" * len(buckets))
        # An item only counts as open once Foundry has asked about it.
        rows = self._rows(self.settings.work_path, f"SELECT bucket, COUNT(*) FROM items WHERE bucket IN ({marks}) AND state = ? AND asked_at IS NOT NULL GROUP BY bucket", *buckets, ItemState.OPEN.value)
        return dict(rows)

    # How things are said

    def waits_for_a_set_time(self, card: Card) -> bool:
        # A routine item opens at its person's next set time. Once a set time has come since it began waiting, it is due, and what holds it up is the card in front.
        # One brought on its own, and a routine card that is already made, wait behind another card and not for a set time.
        if not (card.state == QUEUED and card.is_routine and not card.is_merged and not card.data.get(ONE_BY_ONE)):
            return False
        pack = self.settings.pack_for(self.settings.home_room(card.bucket))
        latest = _latest_slot(pack.set_times, self.settings.utc_offset_minutes, self.clock())
        return latest is None or _waiting_since(card) > latest

    def when(self, moment: datetime) -> str:
        local = moment.astimezone(self.zone)
        return f"{local.day} {local:%b}, {local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'}"

    def client(self, bucket: str) -> str:
        return bucket_name(bucket)

    def _names(self, user: User) -> dict[str, dict[str, str]]:
        return {bucket: names(self.log, bucket) for bucket in user.businesses}

    # Pages

    def overview(self, user: User) -> list[Figures]:
        if not user.businesses:
            return []
        cards, jobs, items = self.cards(user.businesses), self.jobs(user.businesses), self.open_items(user.businesses)
        return [
            Figures(
                bucket, bucket_name(bucket),
                sum(card.bucket == bucket and card.state in (OPEN, QUEUED) for card in cards),
                sum(card.bucket == bucket and card.state == OPEN for card in cards),
                sum(card.bucket == bucket and card.state == QUEUED for card in cards),
                items.get(bucket, 0),
                sum(job.bucket == bucket and job.state is State.BLOCKED for job in jobs),
            )
            for bucket in user.businesses
        ]

    def _waiting(self, job: Job, cards: list[Card], known: dict[str, str]) -> list[str]:
        lines = []
        for card in cards:
            if card.job_id == job.id and card.state in (OPEN, QUEUED):
                line = f"Waiting for an answer to {card.title}, from {known.get(card.person, card.person)}."
                lines.append(line + (WAITS_FOR_SET_TIME if self.waits_for_a_set_time(card) else QUEUED_BEHIND if card.state == QUEUED else ""))
        return lines

    def _row(self, job: Job, cards: list[Card], known: dict[str, str]) -> JobRow:
        stage, sprite = stage_of(job)
        items = self.items(job.id)
        # Nobody can have gone quiet on a request Foundry hasn't made yet, so only the people it asked count.
        asked = [item for item in items if item.asked_at is not None]
        owes = status_line(asked) if asked else ""
        if len(items) > len(asked):
            owes = f"{owes}, {len(items) - len(asked)} not asked yet" if owes else NOBODY_ASKED
        return JobRow(job.id, job.bucket, bucket_name(job.bucket), title_of(job), stage, sprite, owes, self._waiting(job, cards, known), tone_of(job))

    def job_rows(self, user: User) -> list[JobRow]:
        if not user.businesses:
            return []
        cards, known = self.cards(user.businesses), self._names(user)
        return [self._row(job, cards, known[job.bucket]) for job in self.jobs(user.businesses)]

    def offer(self, user: User, card: Card, known: dict[str, str], job: Job | None = None) -> Offer:
        # What this login may do about a card. The desk checks all of it again when it is asked.
        if card.state != OPEN and not still_waits_on(job, card):
            return Offer()
        if card.trigger is Trigger.VOICE:
            return Offer(notice=NOT_FOR_VOICE)
        if card.person != user.businesses.get(card.bucket):
            return Offer(notice=WAITING_FOR.format(name=known.get(card.person, card.person)))
        if card.choices:
            return Offer([(choice, choice) for choice in card.choices])
        if card.trigger in JOB_APPROVALS:
            if job is not None and approving_confirms_voice(job):
                return Offer(changes=True, notice=CONFIRMS_VOICE)
            return Offer([("approve", "Try again" if card.trigger is Trigger.STUCK else "Approve")], changes=True)
        return Offer([("approve", "Approve")])

    def _item_row(self, item: Item) -> ItemRow:
        if item.state in ITEM_STATES:
            status = ITEM_STATES[item.state]
        elif known := desk_wrote(item):
            status = known[0].upper() + known[1:]
        elif item.reason:
            status = f"Said: {item.reason}"
        elif item.asked_at is None:
            status = NOT_ASKED
        elif not item.reachable:
            status = CANT_REACH
        else:
            status = NO_REPLY
        return ItemRow(item.shown_owner or NO_OWNER, item.input, item.measure, self.when(item.due_at), status)

    def _files(self, entries: list[Entry]) -> list[FileRow]:
        newest = {entry.ref: entry for entry in sorted(entries, key=lambda entry: entry.id) if is_made_file(entry)}
        return [FileRow(Path(ref).name, entry.id, Path(ref).suffix.lower() in PICTURES) for ref, entry in newest.items()]

    def job_page(self, user: User, job_id: str) -> JobPage | None:
        job = self.job_of(user, job_id)
        if job is None:
            return None
        cards, known = self.cards([job.bucket]), self._names(user)[job.bucket]
        acts_as = user.businesses[job.bucket]
        items = self.items(job.id)
        by_id = {card.request_id: card for card in cards}
        approval = by_id.get(job.approval["request_id"]) if job.approval else None
        # A card an earlier try ended before it failed still stands for the job, so it can be answered again.
        answer = approval if approval is not None and approval.trigger in JOB_APPROVALS and (approval.state == OPEN or still_waits_on(job, approval)) else None
        restart = Offer()
        if job.state is State.BLOCKED and approval is not None and approval.trigger is Trigger.STUCK:
            restart = self._restart_offer(job, approval, acts_as, known)
        answer_offer = self.offer(user, answer, known, job) if answer else Offer()
        if answer is not None and answer.trigger is Trigger.STUCK:
            # The restart button is how a stuck job goes on. Notes are the other way, so there is no second button for the same thing.
            answer_offer.buttons = []
        due = next((card for card in cards if card.job_id == job.id and card.trigger is Trigger.DUE and card.state == OPEN), None)
        due_offer = self.offer(user, due, known) if due else Offer()
        if due_offer.buttons:
            # The three answers a due-time card offers, each as an action of its own.
            due_offer.buttons = [(action, label) for action, label in DUE_ACTIONS.items() if label in due.choices]
        return JobPage(
            self._row(job, cards, known), job.brief or "", job.report or "", list(job.attention), [self._item_row(item) for item in items],
            answer, answer_offer, restart, due, due_offer, self._files(self.log.for_job(job.bucket, job.id)), job.approver == acts_as,
        )

    def _restart_offer(self, job: Job, card: Card, acts_as: str, known: dict[str, str]) -> Offer:
        if card.state not in (OPEN, EXPIRED) and not still_waits_on(job, card):
            return Offer()
        if card.person != acts_as:
            return Offer(notice=WAITING_FOR.format(name=known.get(card.person, card.person)))
        return Offer([("restart", "Restart")])

    def card_rows(self, user: User) -> tuple[list[CardRow], int]:
        if not user.businesses:
            return [], 0
        known = self._names(user)
        jobs = {job.id: job for job in self.jobs(user.businesses)}
        answered = {bucket: {entry.ref: entry for entry in reversed(self.log.of_kind(bucket, "card_answered"))} for bucket in user.businesses}
        here = {bucket: {entry.ref for entry in self.log.of_kind(bucket, "dashboard_action")} for bucket in user.businesses}
        rows = []
        for card in self.cards(user.businesses):
            who = known[card.bucket].get(card.person, card.person)
            job = jobs.get(card.job_id) if card.job_id else None
            waits = still_waits_on(job, card)
            if waits:
                status = STILL_WAITING
            elif card.state == ANSWERED:
                answer = answered[card.bucket].get(card.request_id)
                where = "on the dashboard as" if card.request_id in here[card.bucket] else "in chat by"
                chosen = card.data.get("answer")
                with_ = f" with {LABELS.get(chosen, chosen)}," if chosen else ""
                status = f"Answered{with_} {where} {who}" + (f", {self.when(answer.at)}" if answer else "")
            else:
                status = {OPEN: "Open in chat", QUEUED: AWAITS_SET_TIME if self.waits_for_a_set_time(card) else "Waiting behind another card", CLOSED: "Closed by Foundry", EXPIRED: "Ran out. Nobody answered it."}[card.state]
            # What a card says matters while someone still has to answer it.
            detail = card.detail if waits or card.state in (OPEN, QUEUED) else ""
            # An answer that didn't go through is still waiting for one, so it sits with the open cards.
            rows.append(CardRow(card.request_id, bucket_name(card.bucket), card.title, detail, CARD_KINDS[card.trigger], status, OPEN if waits else card.state, self.offer(user, card, known[card.bucket], job)))
        live = [row for row in rows if row.state in (OPEN, QUEUED)]
        past = [row for row in rows if row.state not in (OPEN, QUEUED)]
        return live + past[:MOST_PAST_CARDS], max(0, len(past) - MOST_PAST_CARDS)

    # Generated work

    def _sign_off(self, entries: list[Entry], delivered: Entry, known: dict[str, str]) -> str:
        # The answer that came just before the delivery is the sign-off that let it go.
        answers = [entry for entry in entries if entry.kind == "card_answered" and entry.id < delivered.id]
        if not answers:
            return "Delivered"
        via = any(entry.kind == "dashboard_action" and entry.ref == answers[-1].ref for entry in entries)
        return f"Approved by {name_of(answers[-1], known)}{' on the dashboard' if via else ''}, {self.when(answers[-1].at)}. Delivered."

    def work(self, user: User) -> list[WorkJob]:
        if not user.businesses:
            return []
        known, found = self._names(user), []
        for job in self.jobs(user.businesses):
            entries = self.log.for_job(job.bucket, job.id)
            made = [entry for entry in entries if is_made_file(entry)]
            if not made:
                continue
            delivered = [entry for entry in entries if entry.kind == DELIVERED]
            stage = stage_of(job)[0]
            files = []
            for path in dict.fromkeys(entry.ref for entry in made):
                copies = sorted((entry for entry in made if entry.ref == path), key=lambda entry: entry.id)
                versions = []
                for number, entry in enumerate(copies, start=1):
                    newest = entry is copies[-1]
                    sent = next((out for out in reversed(delivered) if out.id > entry.id and Path(path).name in [name.strip() for name in out.text.split(",")]), None)
                    here = Path(path).is_file()
                    if not newest:
                        status = "Replaced by a newer version"
                    elif sent is not None:
                        status = self._sign_off(entries, sent, known[job.bucket])
                    else:
                        status = "Not delivered" if job.state is State.DELIVERED else "Not signed off yet"
                    if newest and not here:
                        status += f" {FILE_GONE}"
                    versions.append(Version(number, entry.id, name_of(entry, known[job.bucket]), self.when(entry.at), status, newest and here and Path(path).suffix.lower() in MEDIA))
                files.append(WorkFile(Path(path).name, Path(path).suffix.lower() in PICTURES, versions[::-1]))
            found.append(WorkJob(job.id, bucket_name(job.bucket), title_of(job), stage, files, tone_of(job)))
        return found

    def file_for(self, user: User, entry_id: int) -> tuple[Path, str] | None:
        # Only the newest copy of a file a maker made for one of this login's clients, and only the kinds the desk delivers.
        entry = self.log.find(entry_id)
        if entry is None or entry.bucket not in user.businesses or not is_made_file(entry):
            return None
        path = Path(entry.ref)
        if path.suffix.lower() not in MEDIA or not path.is_file():
            return None
        copies = [other for other in self.log.for_job(entry.bucket, entry.job_id) if other.ref == entry.ref and other.kind == "file_made"] if entry.job_id else [entry]
        return (path, path.name) if max(other.id for other in copies) == entry.id else None

    # Action log

    def entries_of(self, job: Job) -> list[Entry]:
        # The job's own entries and the messages that opened it.
        own = self.log.for_job(job.bucket, job.id)
        opening = next((entry for entry in own if entry.kind == "job_opened"), None)
        opened = [self.log.get(job.bucket, int(part)) for part in (opening.ref or "").split(",") if part.strip().isdigit()] if opening else []
        chosen = {entry.id: entry for entry in [*own, *(entry for entry in opened if entry is not None)]}
        return sorted(chosen.values(), key=lambda entry: (entry.at, entry.id))

    def job_logs(self, user: User, only: str | None = None) -> tuple[list[JobLog], bool]:
        # The newest jobs, or the one job asked for. Either way a timeline is one job's, and the log is never read as a whole.
        if not user.businesses:
            return [], False
        known, found = self._names(user), []
        jobs = self.jobs(user.businesses)
        shown = [job for job in jobs if job.id == only] if only else jobs[:MOST_TIMELINES]
        for job in shown:
            entries = [entry for entry in self.entries_of(job) if not (entry.kind == "file_made" and not is_made_file(entry))]
            moments = [self._moment(entry, known[job.bucket], user.businesses[job.bucket] == job.approver) for entry in entries]
            found.append(JobLog(job.id, bucket_name(job.bucket), title_of(job), stage_of(job)[0], moments, self._files(entries), user.businesses[job.bucket] == job.approver, tone_of(job)))
        return found, only is None and len(jobs) > MOST_TIMELINES

    def _moment(self, entry: Entry, known: dict[str, str], can_flag: bool) -> Moment:
        target = None
        if can_flag and is_made_file(entry):
            target = ("file", entry.id)
        elif can_flag and entry.kind in SAID:
            target = ("entry", entry.id)
        return Moment(self.when(entry.at), name_of(entry, known), EVENTS.get(entry.kind, entry.kind.replace("_", " ")), squeeze(shown_words(entry, self.settings.inputs_dir)), target)

    def flagged(self, user: User) -> list[Flagged]:
        known = self._names(user)
        flags = [entry for bucket in user.businesses for entry in self.log.of_kind(bucket, "flag")]
        return [Flagged(entry.id, entry.text, name_of(entry, known[entry.bucket]), self.when(entry.at), bucket_name(entry.bucket)) for entry in sorted(flags, key=lambda entry: entry.id, reverse=True)]

    def chain(self, user: User, flag_id: int) -> ChainPage | None:
        entry = self.log.find(flag_id)
        if entry is None or entry.bucket not in user.businesses or entry.kind != "flag":
            return None
        try:
            steps = chain_for(self.log, entry.bucket, flag_id, self.settings.inputs_dir)
        except (NotFlagged, ValueError, KeyError):
            return None
        known = self._names(user)[entry.bucket]
        job = self._rows(self.settings.jobs_path, f"SELECT {', '.join(JOB_COLUMNS)} FROM jobs WHERE id = ?", entry.job_id or "")
        via = any(other.ref == str(entry.id) for other in self.log.of_kind(entry.bucket, "dashboard_action"))
        flagged = Flagged(entry.id, entry.text, name_of(entry, known), self.when(entry.at), bucket_name(entry.bucket))
        return ChainPage(flagged, steps, entry.job_id or "", title_of(_job(job[0])) if job else NO_BRIEF, via)

    # Connections

    def _owners(self, room_id: str) -> set[str]:
        # Every business a room is the room of. A client's studio and review rooms are the client's, whether or not a pack names them, and a room two clients share is both's.
        settings = self.settings
        outsides = [outside for outside, rooms in settings.workrooms.items() if room_id in (rooms.studio, rooms.review) and outside != room_id]
        own = {settings.bucket_for(room_id)} if room_id in settings.brands or room_id in settings.packs or not outsides else set()
        return own | {settings.bucket_for(outside) for outside in outsides}

    def connections(self, user: User, bridges: list[Bridge], rooms: list[Room]) -> list[ConnectionRow]:
        # A connection belongs to no business by itself, so it is told from the rooms on it. A room counts as this login's only when every business it is the room of is one the login manages.
        # A connection with a room of this login's is shown. It can be removed only if every room on it is this login's and Foundry can see them all. If other businesses' rooms are on it too, only its health is shown.
        known = set(self.settings.brands) | set(self.settings.packs) | set(self.settings.all_rooms())
        found = []
        for bridge in bridges:
            on = [room for room in rooms if room.bridge_id == bridge.id]
            owners = {room.id: self._owners(room.id) for room in on if room.id in known}
            mine = [room for room in on if owners.get(room.id) and owners[room.id] <= user.businesses.keys()]
            if not mine:
                continue
            others = any(room.id in owners and not owners[room.id] <= user.businesses.keys() for room in on)
            unlinked = any(room.id not in owners for room in on)
            total = bridge.rooms if bridge.rooms is not None else len(on)
            why_not = SHARED if others else NOT_ALL_YOURS if unlinked else CANT_SEE_ALL if bridge.rooms != len(on) else ""
            healthy = bridge.status == "active" and not bridge.attention
            serves = tuple(dict.fromkeys(bucket for room in mine for bucket in sorted(owners[room.id])))
            if bridge.attention:
                state = NEEDS_ATTENTION.format(what=bridge.attention)
            else:
                state = RUNNING if healthy else NOT_RUNNING.format(status=bridge.status or "unknown")
            names = [] if others else [room.name for room in mine]
            found.append(
                ConnectionRow(
                    bridge.id, quote(bridge.id, safe=""), bridge.name, bridge.type or "unknown", state, healthy, names, 0 if others else total, 0 if others else max(total - len(mine), 0),
                    serves, ", ".join(bucket_name(bucket) for bucket in serves), not why_not, why_not, others,
                )
            )
        return found

    def health(self, user: User, rows: list[ConnectionRow]) -> dict[str, str]:
        found = {}
        for bucket in user.businesses:
            theirs = [row for row in rows if bucket in row.serves]
            running = sum(row.healthy for row in theirs)
            if not theirs:
                found[bucket] = NO_CONNECTION
                continue
            found[bucket] = f"{len(theirs)} {'connection' if len(theirs) == 1 else 'connections'}: {running} running" + (f", {len(theirs) - running} needing attention" if running < len(theirs) else "")
        return found

    # Data

    def data(self, user: User) -> list[ClientData]:
        found = []
        for bucket in user.businesses:
            folder = brand_data.folder_for(self.settings, bucket)
            files = [DataFile(item.file, item.kind, item.changed) for item in brand_data.items(folder)] if folder else []
            found.append(ClientData(bucket, bucket_name(bucket), quote(bucket, safe=""), folder is not None, any(file.file == KIT for file in files), files))
        return found

    def data_folder(self, user: User, bucket: str) -> Path | None:
        # Another client's folder is not found, so nobody can tell it exists.
        return brand_data.folder_for(self.settings, bucket) if bucket in user.businesses else None

    def data_view(self, user: User, bucket: str, file: str) -> DataView | None:
        folder = self.data_folder(user, bucket)
        item = brand_data.find(folder, file) if folder else None
        if item is None:
            return None
        text, cut = brand_data.read(item)
        return DataView(bucket, bucket_name(bucket), quote(bucket, safe=""), item.file, item.kind, text, cut)

    # What this login asked for lately

    def recent(self, commands: CommandStore, login: str) -> list[Recent]:
        found = []
        for command in commands.recent(login):
            if command.error == CLAIMED:
                status, failed = NOT_RECORDED, False
            elif command.error:
                status, failed = DIDNT_DO.format(error=command.error), True
            else:
                status, failed = (DONE if command.done_at else WAITING_FOR_FOUNDRY), False
            found.append(Recent(self._describe(command), status, failed))
        return found

    def _describe(self, command: Command) -> str:
        payload = command.payload
        if command.action == "answer_card":
            card = self.card(str(payload.get("request_id", "")))
            choice = payload.get("choice", "")
            return f"Answered {card.title if card else 'a card'} with {LABELS.get(choice, choice)}"
        if command.action == "note_connection":
            name = plain_name(payload.get("name")) or NO_NAME
            done = {("added", True): "Added", ("removed", True): "Removed", ("added", False): "Tried to add", ("removed", False): "Tried to remove"}
            return f"{done.get((payload.get('what'), payload.get('sure') is True), 'Noted')} the connection {name}"
        if command.action == "reload_pack":
            file = payload.get("file")
            return f"Changed {file} and read the business's pack again" if is_data_file(file) else "Read the business's pack again"
        rows = self._rows(self.settings.jobs_path, f"SELECT {', '.join(JOB_COLUMNS)} FROM jobs WHERE id = ?", str(payload.get("job_id", "")))
        job = title_of(_job(rows[0])) if rows else "a job"
        what = {"restart": "Restart", "flag": "Flag something in"}.get(command.action) or DUE_ACTIONS[command.action]
        return f"{what} {job}" if command.action == "flag" else f"{what}: {job}"
