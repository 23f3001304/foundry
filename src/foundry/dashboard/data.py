"""A business's brand folder as the dashboard shows and changes it: the kit and the source documents and tables, and nothing else in the folder. The tools and checks read these files as they are, and the desk reads the documents again when it is asked to."""

import hashlib
import io
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import foundry.desk
from foundry.brand import BrandError, load_brand
from foundry.checks import cell_number
from foundry.commands import KIT, SOURCE_NAME, SOURCES, TABLE_SUFFIXES, is_source_name
from foundry.desk import Settings
from foundry.tables import read_file, read_upload
from foundry.tools.layout import MakerError

logger = logging.getLogger(__name__)

# A source or a kit is a page or two of plain text. This is far more than that, and a sensible ceiling for a prompt.
MOST_UPLOAD = 200_000
# A table is bigger than a page, and a spreadsheet is a zip file that opens into more than it weighs. The data tools read no more than 50,000 rows of one.
MOST_TABLE = 2_000_000
MOST_UNPACKED = 50 * 1024 * 1024
MOST_PARTS = 2000
# The most of a file one page shows, and of a table's columns.
MOST_SHOWN = 50_000
MOST_COLUMNS_SHOWN = 40
MOST_COLUMN_CHARS = 60
# How much of the reason a kit won't load is repeated back.
MOST_REASON = 300

NO_FILE = "Choose a file first."
TOO_BIG = "That file is too big. A source document can be up to 200 KB."
TABLE_TOO_BIG = "That table is too big. A table can be up to 2 MB."
SHEET_TOO_BIG = "That spreadsheet is too big once it is opened."
EMPTY = "That file is empty."
NOT_TEXT = "That file isn't plain text. Save it as UTF-8 text and try again."
TABLE_NO_ROWS = "That table has headings but no rows of data."
TABLE_NO_FIGURES = "That table has no figures the data tools can read."
NAME_ENDING = "Name the file so it ends in .md, .csv or .xlsx."
NAME_LETTERS = "Use only letters, numbers, - and _ in the name, up to 60 of them, then .md, .csv or .xlsx."
NAME_TAKEN = "That name can't be added, because it is kept for something else."
IS_A_LINK = "That is a link to somewhere else, so nothing is written to it here."
NOT_WRITTEN = "Foundry couldn't write that file just now, so nothing was changed. Try again in a moment."
KIT_BROKEN = "That isn't a brand kit the makers can use: {why}"
KIT_UNREADABLE = "That isn't a brand kit the makers can use. It needs the front matter a kit starts with."
TABLE_UNREADABLE = "Foundry couldn't read {name}."


@dataclass(frozen=True)
class Item:
    # What the page and the route call it: kit.md, or the source's own name.
    file: str
    kind: str
    changed: datetime
    path: Path


def brands_root() -> Path:
    # Looked up each time, as the desk does, so it is the one place the folders are named.
    return foundry.desk.BRANDS


def is_link(path: Path) -> bool:
    # A link, or a junction, which Windows keeps apart from one. Either could lead anywhere, so neither is read, listed or written through.
    return path.is_symlink() or path.is_junction()


def folder_for(settings: Settings, bucket: str) -> Path | None:
    # Only a business the desk has a brand for has a folder, and it is named by that brand.
    root = brands_root()
    if bucket not in settings.brands.values():
        return None
    folder = root / bucket
    return folder if folder.is_dir() and not is_link(folder) and folder.resolve().parent == root.resolve() else None


def relative(file: str) -> str:
    # How a command and the log name it.
    return file if file == KIT else f"{SOURCES}/{file}"


def fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:10]


def sources_folder(folder: Path) -> Path | None:
    inside = folder / SOURCES
    return inside if inside.is_dir() and not is_link(inside) else None


def is_plain_file(path: Path) -> bool:
    return path.is_file() and not is_link(path)


@lru_cache(maxsize=256)
def _named_in(kit: Path, changed: int) -> str | None:
    # Asked for on every row of a page, so a kit is only read again once it has changed.
    try:
        return load_brand(kit.read_text(encoding="utf-8"), kit.parent).name
    except Exception:
        return None


def kit_name(slug: str) -> str | None:
    # The name a business's own kit gives it. With no kit, or one that can't be read, there is none to give.
    kit = brands_root() / slug / KIT
    try:
        return _named_in(kit, kit.stat().st_mtime_ns) if is_plain_file(kit) else None
    except OSError:
        return None


def is_table(name: str) -> bool:
    return name.endswith(TABLE_SUFFIXES)


def kind_of(name: str) -> str:
    return "Brand kit" if name == KIT else "Table" if is_table(name) else "Source document"


def changed_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def items(folder: Path) -> list[Item]:
    found = []
    if is_plain_file(folder / KIT):
        found.append(Item(KIT, kind_of(KIT), changed_at(folder / KIT), folder / KIT))
    inside = sources_folder(folder)
    for path in sorted(inside.iterdir()) if inside else []:
        if is_source_name(path.name) and is_plain_file(path):
            found.append(Item(path.name, kind_of(path.name), changed_at(path), path))
    return found


def find(folder: Path, file: str) -> Item | None:
    # Matched against the names that are really there, so a name is never turned into a path.
    return next((item for item in items(folder) if item.file == file), None)


def table_summary(item: Item) -> str:
    # Its columns and how many rows, as the data tools read it. The cells themselves are not shown, since this is not a spreadsheet.
    try:
        table = read_file(item.path)
    except MakerError as error:
        return str(error)
    except Exception:
        logger.exception("Could not read the table %s.", item.file)
        return TABLE_UNREADABLE.format(name=item.file)
    shown = [column[:MOST_COLUMN_CHARS] for column in table.columns[:MOST_COLUMNS_SHOWN]]
    more = f" and {len(table.columns) - len(shown)} more" if len(table.columns) > len(shown) else ""
    lines = [f"Columns: {', '.join(shown)}{more}", f"Rows of data: {len(table.rows)}"]
    return "\n".join([*lines, f"Sheet: {table.sheet}"] if table.sheet else lines)


def read(item: Item) -> tuple[str, bool]:
    if is_table(item.file):
        return table_summary(item), False
    text = item.path.read_text(encoding="utf-8", errors="replace")
    return text[:MOST_SHOWN], len(text) > MOST_SHOWN


def name_problem(name: str) -> str | None:
    if not name.endswith((".md", *TABLE_SUFFIXES)):
        return NAME_ENDING
    if not SOURCE_NAME.fullmatch(name):
        return NAME_LETTERS
    return None if is_source_name(name) else NAME_TAKEN


def text_of(raw: bytes) -> tuple[str, str | None]:
    # The text of an upload and what is wrong with it. A byte order mark is dropped, since a kit has to start with its front matter.
    if len(raw) > MOST_UPLOAD:
        return "", TOO_BIG
    if not raw.strip():
        return "", EMPTY
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "", NOT_TEXT
    # A byte order mark alone is bytes, and decodes to nothing.
    if not text.strip():
        return "", EMPTY
    return ("", NOT_TEXT) if "\x00" in text else (text, None)


def kit_problem(text: str, folder: Path) -> str | None:
    # A kit the makers can't read would stop every deck and graphic for the business, so it is tried the way they read it.
    try:
        load_brand(text, folder)
    except BrandError as error:
        return KIT_BROKEN.format(why=str(error)[:MOST_REASON])
    except Exception:
        return KIT_UNREADABLE
    return None


def opens_too_big(raw: bytes) -> bool:
    # A spreadsheet is a zip file, and a small one can hold a sheet of gigabytes. Its own list of parts says how much, before any of it is opened.
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            parts = archive.infolist()
            return len(parts) > MOST_PARTS or sum(part.file_size for part in parts) > MOST_UNPACKED
    except (zipfile.BadZipFile, NotImplementedError, ValueError, OSError):
        # Not a spreadsheet at all, or one this machine can't open, which reading it will say in plain words.
        return False


def table_problem(name: str, raw: bytes) -> str | None:
    # Read the way the data tools read it, and only if it has a row of data and a figure to work with.
    if len(raw) > MOST_TABLE:
        return TABLE_TOO_BIG
    if not raw.strip():
        return EMPTY
    if name.endswith(".xlsx") and opens_too_big(raw):
        return SHEET_TOO_BIG
    # Read where it is, without writing a copy of a client's file anywhere to be read.
    try:
        table = read_upload(name, raw)
    except MakerError as error:
        return str(error)
    except Exception:
        logger.exception("Could not read an uploaded table.")
        return TABLE_UNREADABLE.format(name=name)
    if not table.rows:
        return TABLE_NO_ROWS
    if not any(cell_number(cell) is not None for row in table.rows for cell in row.cells):
        return TABLE_NO_FIGURES
    return None


def checked(name: str, raw: bytes, folder: Path) -> tuple[bytes, str | None]:
    # What to write for an upload of this name, and what is wrong with it. A table is kept byte for byte, and a document or a kit as plain UTF-8.
    if is_table(name):
        return raw, table_problem(name, raw)
    text, problem = text_of(raw)
    if problem is None and name == KIT:
        problem = kit_problem(text, folder)
    return text.encode("utf-8"), problem


def target_for(folder: Path, name: str) -> tuple[Path | None, str | None]:
    # Where a new source goes. A name that matches one already there in other letters is that one, so a case-blind disk and a case-sensitive one end up the same.
    inside = sources_folder(folder)
    if inside is None and (folder / SOURCES).exists():
        return None, IS_A_LINK
    same = next((path for path in sorted(inside.iterdir()) if path.name.casefold() == name.casefold()), None) if inside else None
    if same is not None and not is_plain_file(same):
        return None, IS_A_LINK
    return (same or (inside or folder / SOURCES) / name), None


def target_for_kit(folder: Path) -> tuple[Path | None, str | None]:
    # A brand with no kit can be given one. Anything else at that name is not a kit and is not written over.
    kit = folder / KIT
    return (None, IS_A_LINK) if kit.exists() or is_link(kit) else (kit, None)


def save(path: Path, content: bytes) -> None:
    # Written beside the file and moved over it, so nothing reads half of one. The temporary name isn't a source's name, so it is never taken for one.
    path.parent.mkdir(exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(content)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write(path: Path, content: bytes) -> str | None:
    # What went wrong, if the disk wouldn't take it. Nothing is left half done.
    try:
        save(path, content)
    except OSError as error:
        logger.warning("Could not write %s: %s", path.name, error)
        return NOT_WRITTEN
    return None
