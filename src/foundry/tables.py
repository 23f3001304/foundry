"""Reads the CSV and Excel files people send as answers into tables that remember where every cell was, so a result can name the cells it came from."""

import csv
import io
import logging
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
TOO_MANY_ROWS = f"{{name}} has more than {MOST_ROWS_READ} rows, which is too many to read."
NOT_TEXT = "{name} is not a text file I can read."
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


def is_file_answer(text: str) -> bool:
    # The desk logs a file sent as an answer by the path it saved it to.
    path = Path(text)
    return path.is_absolute() and path.suffix.lower() in TABLE_KINDS


def read_file(source: Path | str) -> Table:
    path = Path(source)
    kind = path.suffix.lower()
    if kind not in TABLE_KINDS:
        raise MakerError(NOT_A_TABLE.format(kinds=" and ".join(TABLE_KINDS), name=path.name))
    if not path.is_file():
        raise MakerError(NO_FILE.format(path=source))
    table = _read_csv(path) if kind == ".csv" else _read_xlsx(path)
    if not table.columns:
        raise MakerError(NO_ROWS.format(name=path.name))
    return table


def table_text(source: Path | str) -> str | None:
    # Every cell as words, for a number check that has to know what a file said. None when the file can't be read.
    try:
        table = read_file(source)
    except MakerError as error:
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


def _table(name: str, records: list[tuple[int, list]], unsaved: set[tuple[int, int]], sheet: str = "") -> Table:
    if not records:
        raise MakerError(NO_ROWS.format(name=name))
    (_, heading), body = records[0], records[1:]
    if len(body) > MOST_ROWS_READ:
        raise MakerError(TOO_MANY_ROWS.format(name=name))
    width = max(len(heading), *(len(cells) for _, cells in body)) if body else len(heading)
    rows = [Row(number, tuple(cells) + (None,) * (width - len(cells))) for number, cells in body]
    return Table(_headings(heading, width), rows, sheet, frozenset(unsaved))


def _decode(data: bytes, name: str) -> str:
    # Excel saves a CSV with a byte order mark, or in the Windows code page when it was not asked for UTF-8.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MakerError(NOT_TEXT.format(name=name))


def _read_csv(path: Path) -> Table:
    text = _decode(path.read_bytes(), path.name)
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(DELIMITERS, key=first.count) if any(mark in first for mark in DELIMITERS) else ","
    try:
        parsed = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as error:
        raise MakerError(NOT_TEXT.format(name=path.name)) from error
    records = [(number, [cell.strip() or None for cell in cells]) for number, cells in enumerate(parsed, start=1)]
    # The headings and every row with something in it. An empty row keeps its number, so the rows after it keep theirs.
    kept = [record for record in records if any(cell is not None for cell in record[1])]
    return _table(path.name, kept, set())


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
            elif (empty := empty + 1) > MOST_EMPTY_ROWS:
                break
    except Exception as error:
        logger.warning("Could not read the spreadsheet %s: %s", path.name, error)
        raise MakerError(NOT_A_SPREADSHEET.format(name=path.name)) from error
    finally:
        values.close()
        formulas.close()
    return _table(path.name, records, unsaved, sheet.title)
