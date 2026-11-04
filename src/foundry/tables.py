"""Reads the CSV and Excel files people send as answers into tables that remember where every cell was, so a result can name the cells it came from."""

import codecs
import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from foundry.tools.layout import MakerError

logger = logging.getLogger(__name__)

# What a person can send as an answer, and what the data tools read. Not the same list as the files makers deliver.
TABLE_KINDS = (".csv", ".xlsx")
MOST_ROWS_READ = 50_000
# A sheet can claim a million rows and hold forty, so reading stops after this many empty rows in a row.
MOST_EMPTY_ROWS = 1000
DELIMITERS = ",;\t"
NOT_A_TABLE = "I can read {kinds} files, not {name}."
NO_FILE = "There is no file at {path}."
NO_ROWS = "{name} has no rows."
TOO_MANY_ROWS = "{name} has more than {most} rows, which is too many to read."
NOT_TEXT = "{name} is not a text file I can read."
NOT_OPENED = "I couldn't open {name}. It may be in use by another program."
# A file that separates its columns with semicolons writes 1,5 for one and a half, and 1.234,5 for one thousand two hundred and thirty-four and a half.
DECIMAL_COMMA = re.compile(r"(?P<mark>[₹$€£]?\s*-?)(?P<whole>\d{1,3}(?:\.\d{3})+|\d+),(?P<part>\d+)(?P<rest>\s*%?)")
DECIMAL_COMMAS_READ = "Numbers with a comma in them were read as decimal commas, because this file separates its columns with semicolons."
# The marks at the front of a file that say how it is written. Excel's Unicode Text export begins with a UTF-16 one.
BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))
NOT_A_SPREADSHEET = "I couldn't read {name} as a spreadsheet. It may be damaged, or not really an .xlsx file."
NO_COLUMN = 'There is no column "{name}". The columns are: {columns}.'


@dataclass(frozen=True)
class Row:
    # The row's place in the file as a spreadsheet shows it, where the headings are row 1.
    number: int
    cells: tuple


@dataclass
class Table:
    columns: list[str]
    rows: list[Row]
    sheet: str = ""
    # Formula cells with no result saved in the file, as (row number, column position).
    unsaved: frozenset[tuple[int, int]] = frozenset()
    # The log entry behind each row, for a table made from a job's answers.
    entries: dict[int, int] = field(default_factory=dict)
    # What was done to read the file that a reader of it ought to be told.
    notes: tuple[str, ...] = ()
    # For a table made from a job's answers: how many people were asked, how many are in, and who is not.
    standing: dict | None = None


def squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def address(row: int, column: int) -> str:
    return f"{get_column_letter(column + 1)}{row}"


def column_named(table: Table, name: str) -> int:
    wanted = squash(name)
    for position, column in enumerate(table.columns):
        if squash(column) == wanted:
            return position
    raise MakerError(NO_COLUMN.format(name=name, columns=", ".join(table.columns)))


def safe_name(text: str, fallback: str) -> str:
    # Letters, digits, dots, dashes and underscores only, so a name can't be a folder or reach one.
    return re.sub(r"[^\w.-]+", "_", text).strip("._-") or fallback


def job_folder(inputs_dir: Path | str, bucket: str, job_id: str) -> Path:
    # Where the desk keeps the files sent as answers to one job: a folder for the client, and in it a folder for the job.
    return Path(inputs_dir) / safe_name(bucket, "client") / safe_name(job_id, "job")


def is_file_answer(text: str, inputs_dir: Path | str | None, bucket: str, job_id: str | None) -> bool:
    # A file answer is one the desk kept in this job's own folder. A path anyone typed as an answer, to anywhere else, is only the words they typed, and is never opened.
    if inputs_dir is None or not job_id or Path(text).suffix.lower() not in TABLE_KINDS:
        return False
    try:
        path = Path(text)
        return path.is_absolute() and path.resolve().is_relative_to(job_folder(inputs_dir, bucket, job_id).resolve())
    except (OSError, ValueError):
        return False


def read_file(source: Path | str) -> Table:
    path = Path(source)
    kind = path.suffix.lower()
    if kind not in TABLE_KINDS:
        raise MakerError(NOT_A_TABLE.format(kinds=" and ".join(TABLE_KINDS), name=path.name))
    if not path.is_file():
        raise MakerError(NO_FILE.format(path=source))
    try:
        table = _read_csv(path) if kind == ".csv" else _read_xlsx(path)
    except OSError as error:
        # A file another program holds open, or a disk that fails, is told in plain words like any other file that cannot be read.
        logger.warning("Could not open %s: %s", path.name, error)
        raise MakerError(NOT_OPENED.format(name=path.name)) from error
    if not table.columns:
        raise MakerError(NO_ROWS.format(name=path.name))
    return table


def table_text(source: Path | str) -> str | None:
    # Every cell as words, for a number check that has to know what a file said. None when the file can't be read.
    try:
        table = read_file(source)
    except (MakerError, OSError) as error:
        logger.warning("Could not read the answer file %s: %s", source, error)
        return None
    lines = [" ".join(table.columns), *(" ".join(words(cell) for cell in row.cells if cell is not None) for row in table.rows)]
    return "\n".join(lines)


def words(cell: object) -> str:
    return str(int(cell)) if isinstance(cell, float) and cell.is_integer() else str(cell)


def _headings(cells: list, width: int) -> list[str]:
    # A blank heading is named by its place, and a heading used twice gets a number, so every column can be asked for by name.
    named, seen = [], {}
    for position in range(width):
        cell = cells[position] if position < len(cells) else None
        text = " ".join(words(cell).split()) if cell is not None else ""
        text = text or f"column {position + 1}"
        seen[squash(text)] = seen.get(squash(text), 0) + 1
        named.append(text if seen[squash(text)] == 1 else f"{text} ({seen[squash(text)]})")
    return named


def _table(name: str, records: list[tuple[int, list]], unsaved: set[tuple[int, int]], sheet: str = "", notes: tuple[str, ...] = ()) -> Table:
    if not records:
        raise MakerError(NO_ROWS.format(name=name))
    (_, heading), body = records[0], records[1:]
    if len(body) > MOST_ROWS_READ:
        raise MakerError(TOO_MANY_ROWS.format(name=name, most=MOST_ROWS_READ))
    width = max(len(heading), *(len(cells) for _, cells in body)) if body else len(heading)
    rows = [Row(number, tuple(cells) + (None,) * (width - len(cells))) for number, cells in body]
    return Table(_headings(heading, width), rows, sheet, frozenset(unsaved), notes=notes)


def _decode(data: bytes, name: str) -> str:
    # A mark at the front says how the file is written. With none, Excel saved it as UTF-8 or in the Windows code page, and a NUL byte is neither, so it is not text.
    for mark, encoding in BOMS:
        if data.startswith(mark):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError as error:
                raise MakerError(NOT_TEXT.format(name=name)) from error
    if b"\x00" in data:
        raise MakerError(NOT_TEXT.format(name=name))
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MakerError(NOT_TEXT.format(name=name))


def _decimal_comma(cell: str | None) -> str | None:
    found = DECIMAL_COMMA.fullmatch(cell) if cell else None
    return f"{found['mark']}{found['whole'].replace('.', '')}.{found['part']}{found['rest']}" if found else None


def _read_csv(path: Path) -> Table:
    text = _decode(path.read_bytes(), path.name)
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(DELIMITERS, key=first.count) if any(mark in first for mark in DELIMITERS) else ","
    records, converted = [], False
    try:
        for number, cells in enumerate(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter), start=1):
            cells = [cell.strip() or None for cell in cells]
            # The headings and every row with something in it. An empty row keeps its number, so the rows after it keep theirs.
            if any(cell is not None for cell in cells):
                if delimiter == ";" and records:
                    changed = [_decimal_comma(cell) or cell for cell in cells]
                    converted, cells = converted or changed != cells, changed
                records.append((number, cells))
                if len(records) > MOST_ROWS_READ + 1:
                    break
    except csv.Error as error:
        raise MakerError(NOT_TEXT.format(name=path.name)) from error
    return _table(path.name, records, set(), notes=(DECIMAL_COMMAS_READ,) if converted else ())


def _plain(value: object) -> object:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip() or None
    return value


def _read_xlsx(path: Path) -> Table:
    try:
        values, formulas = load_workbook(path, data_only=True, read_only=True), load_workbook(path, data_only=False, read_only=True)
    except Exception as error:
        # Whatever stops openpyxl opening it, the file is one the desk cannot read.
        logger.warning("Could not open the spreadsheet %s: %s", path.name, error)
        raise MakerError(NOT_A_SPREADSHEET.format(name=path.name)) from error
    try:
        sheet = values.active if hasattr(values.active, "iter_rows") else values.worksheets[0]
        records, unsaved, empty = [], set(), 0
        for number, (saved, cells) in enumerate(zip(sheet.iter_rows(values_only=True), formulas[sheet.title].iter_rows()), start=1):
            row = [_plain(value) for value in saved]
            # A formula the program never calculated shows no value, and a row of only those is still a row.
            no_result = [position for position, cell in enumerate(cells) if cell.data_type == "f" and position < len(row) and row[position] is None]
            unsaved.update((number, position) for position in no_result)
            if no_result or any(value is not None for value in row):
                records.append((number, row))
                empty = 0
                # One more than the limit is enough to know it is too many, and the rest of a big sheet is never read.
                if len(records) > MOST_ROWS_READ + 1:
                    break
            elif (empty := empty + 1) > MOST_EMPTY_ROWS:
                break
    except Exception as error:
        logger.warning("Could not read the spreadsheet %s: %s", path.name, error)
        raise MakerError(NOT_A_SPREADSHEET.format(name=path.name)) from error
    finally:
        values.close()
        formulas.close()
    return _table(path.name, records, unsaved, sheet.title)
