"""Fixed checks on the numbers in finished work. Code decides these, and a model's confidence can add a check but never take one away."""

import logging
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median

from pptx import Presentation
from pptx.shapes.group import GroupShape

from foundry.cleanup import DATE_TOKEN, NUMBER, CleanResult
from foundry.log import Entry, Log
from foundry.tables import is_file_answer, table_text

logger = logging.getLogger(__name__)

LOW_CONFIDENCE = 0.6
# How far a figure may sit from the middle of its peers, as a share of that middle, before it needs a look. Wider than a jump, because offices differ in size.
PEER_SHARE = 0.5
# Fewer figures than this have no peers: with two, each is as far from the middle as the other.
FEWEST_PEERS = 3
NOT_SURE = "The model said it was not sure this report is right."
# Only what people said. A reviewer's note, an agent's marker or a card must not make a number look sourced.
PEOPLE_WORDS = ("message", "voice_heard", "voice_corrected", "item_answer", "item_passed_on", "revision_notes")

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b\.?"
YEAR = r"(?:19|20)\d{2}"
DAY = r"\d{1,2}(?:st|nd|rd|th)?"
# 8 Nov 2026, 8th of November, Nov 8, 2026 and 2026-11-08.
WRITTEN_DATE = re.compile(rf"\b{DAY}\s+(?:of\s+)?{MONTH}(?:,?\s+{YEAR})?|\b{MONTH}\s+{DAY}\b(?:,?\s+{YEAR})?|\b{YEAR}-\d{{2}}-\d{{2}}\b")
# A year is four plain digits. With a comma, as in 2,026, or after a currency mark or before a %, as in ₹1999 and 2000%, it is a quantity.
YEAR_ONLY = re.compile(YEAR)
CURRENCY_BEFORE = re.compile(r"(?:₹|(?<![A-Za-z])Rs\.?|[$€£])\s*$")
# Commas that group thousands, as in 1,200,000 and the Indian 12,34,567.
GROUPED = re.compile(r"\d{1,3}(?:(?:,\d{3})+|(?:,\d{2})*,\d{3})(?:\.\d+)?")
DECIMAL = re.compile(r"\d+\.\d+")
FIGURE = re.compile(rf"(-?)\s*[₹$€£]?\s*({NUMBER.pattern})\s*%?")


def _normal(token: str) -> str:
    if GROUPED.fullmatch(token):
        token = token.replace(",", "")
    if DECIMAL.fullmatch(token):
        token = token.rstrip("0").rstrip(".")
    return token


def numbers_in(text: str) -> list[str]:
    # Dates are written by code or are not measures, so neither counts as a number.
    text = WRITTEN_DATE.sub(" ", DATE_TOKEN.sub(" ", text))
    return list(dict.fromkeys(_normal(match.group()) for match in NUMBER.finditer(text) if not _is_year(text, match)))


def _is_year(text: str, number: re.Match) -> bool:
    if not YEAR_ONLY.fullmatch(number.group()):
        return False
    money = CURRENCY_BEFORE.search(text, max(0, number.start() - 8), number.start()) is not None
    return not (money or text.startswith("%", number.end()))


def unsourced_numbers(output: str, sources: list[str]) -> list[str]:
    known = {number for source in sources for number in numbers_in(source)}
    return [number for number in numbers_in(output) if number not in known]


def figure(text: str) -> Decimal | None:
    match = FIGURE.fullmatch(text.strip())
    if match is None:
        return None
    try:
        return Decimal(match.group(1) + _normal(match.group(2)))
    except InvalidOperation:
        return None


def jumped(previous: str, new: str, share: float) -> bool:
    # Moving by more than the share of the old figure. Coming from nothing always counts, and a word is never a jump.
    before, after = figure(previous), figure(new)
    if before is None or after is None:
        return False
    return abs(after - before) > abs(before) * Decimal(str(share))


def _as_figure(value: str | int | float | Decimal) -> Decimal | None:
    if isinstance(value, str):
        return figure(value)
    number = Decimal(str(value))
    return number if number.is_finite() else None


def outliers(values: Iterable[str | int | float | Decimal], share: float = PEER_SHARE) -> list[int]:
    # The places in values of figures further than the share from the middle of all of them. A word is skipped and keeps its place,
    # fewer than three figures have no peers, and a middle of nothing leaves no scale to judge by.
    figures = [(place, _as_figure(value)) for place, value in enumerate(values)]
    known = [(place, number) for place, number in figures if number is not None]
    if len(known) < FEWEST_PEERS:
        return []
    middle = median(number for _, number in known)
    if middle == 0:
        return []
    return [place for place, number in known if abs(number - middle) > abs(middle) * Decimal(str(share))]


def _shape_text(shapes) -> list[str]:
    lines = []
    for shape in shapes:
        if isinstance(shape, GroupShape):
            lines += _shape_text(shape.shapes)
        elif shape.has_text_frame:
            lines.append(shape.text_frame.text)
        elif shape.has_table:
            lines += [cell.text for row in shape.table.rows for cell in row.cells]
    return lines


def _deck_text(path: Path) -> str | None:
    try:
        lines = []
        for slide in Presentation(str(path)).slides:
            lines += _shape_text(slide.shapes)
            notes = slide.notes_slide.notes_text_frame if slide.has_notes_slide else None
            if notes is not None:
                lines.append(notes.text)
    except Exception as error:
        # Whatever stops python-pptx opening it, the file is one the desk cannot read.
        logger.warning("Could not read the deck %s: %s", path.name, error)
        return None
    return "\n".join(lines)


def file_text(path: Path | str) -> str | None:
    # A deck is read itself. Any other file is read through the record its maker saved beside it, <path>.txt.
    file = Path(path)
    if file.suffix.lower() == ".pptx":
        text = _deck_text(file)
        if text is not None:
            return text
    try:
        return Path(f"{file}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def needs_attention(result: CleanResult) -> list[str]:
    lines = list(result.warnings)
    if result.confidence is not None and result.confidence < LOW_CONFIDENCE:
        lines.append(NOT_SURE)
    return lines


def _said(entry: Entry) -> str | None:
    # A file sent as an answer is logged by its path. What the person gave is what is in the file, and the digits in a folder name are not figures anyone gave.
    if entry.kind == "item_answer" and is_file_answer(entry.text):
        return table_text(entry.text)
    return entry.text


def people_words(log: Log, bucket: str, job_id: str) -> list[str]:
    entries = log.for_job(bucket, job_id)
    # The messages that opened a job were logged before it had an id, so its opening entry names them.
    opening = [log.get(bucket, int(part)) for entry in entries if entry.kind == "job_opened" for part in (entry.ref or "").split(",") if part.strip().isdigit()]
    said = [_said(entry) for entry in [*opening, *entries] if entry is not None and entry.kind in PEOPLE_WORDS]
    return [text for text in said if text is not None]
