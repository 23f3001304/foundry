"""A business's brand folder as the dashboard shows and changes it: the kit and the source documents, and nothing else in the folder. The desk reads these files, and reads the sources again when it is asked to."""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import foundry.desk
from foundry.brand import BrandError, load_brand
from foundry.commands import KIT, SOURCE_NAME, SOURCES, is_source_name
from foundry.desk import Settings

logger = logging.getLogger(__name__)

# A source or a kit is a page or two of plain text. This is far more than that, and a sensible ceiling for a prompt.
MOST_UPLOAD = 200_000
# The most of a file one page shows.
MOST_SHOWN = 50_000

NO_FILE = "Choose a file first."
TOO_BIG = "That file is too big. A source document can be up to 200 KB."
EMPTY = "That file is empty."
NOT_TEXT = "That file isn't plain text. Save it as UTF-8 text and try again."
NAME_ENDING = "Name the file so it ends in .md."
NAME_LETTERS = "Use only letters, numbers, - and _ in the name, up to 60 of them, then .md."
NAME_TAKEN = "That name can't be added, because it is kept for something else."
IS_A_LINK = "That is a link to somewhere else, so nothing is written to it here."
NOT_WRITTEN = "Foundry couldn't write that file just now, so nothing was changed. Try again in a moment."
KIT_BROKEN = "That isn't a brand kit the makers can use: {why}"
KIT_UNREADABLE = "That isn't a brand kit the makers can use. It needs the front matter a kit starts with."


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


def folder_for(settings: Settings, bucket: str) -> Path | None:
    # Only a business the desk has a brand for has a folder, and it is named by that brand.
    root = brands_root()
    if bucket not in settings.brands.values():
        return None
    folder = root / bucket
    return folder if folder.is_dir() and not folder.is_symlink() and folder.resolve().parent == root.resolve() else None


def relative(file: str) -> str:
    # How a command and the log name it.
    return file if file == KIT else f"{SOURCES}/{file}"


def sources_folder(folder: Path) -> Path | None:
    inside = folder / SOURCES
    return inside if inside.is_dir() and not inside.is_symlink() else None


def is_plain_file(path: Path) -> bool:
    # A link could lead anywhere, so a link is never read or written through.
    return path.is_file() and not path.is_symlink()


def items(folder: Path) -> list[Item]:
    found = []
    if is_plain_file(folder / KIT):
        found.append(Item(KIT, "Brand kit", changed_at(folder / KIT), folder / KIT))
    inside = sources_folder(folder)
    for path in sorted(inside.iterdir()) if inside else []:
        if is_source_name(path.name) and is_plain_file(path):
            found.append(Item(path.name, "Source document", changed_at(path), path))
    return found


def changed_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def find(folder: Path, file: str) -> Item | None:
    # Matched against the names that are really there, so a name is never turned into a path.
    return next((item for item in items(folder) if item.file == file), None)


def read(item: Item) -> tuple[str, bool]:
    text = item.path.read_text(encoding="utf-8", errors="replace")
    return text[:MOST_SHOWN], len(text) > MOST_SHOWN


def name_problem(name: str) -> str | None:
    if not name.endswith(".md"):
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
    return ("", NOT_TEXT) if "\x00" in text else (text, None)


def kit_problem(text: str, folder: Path) -> str | None:
    # A kit the makers can't read would stop every deck and graphic for the business, so it is tried the way they read it.
    try:
        load_brand(text, folder)
    except BrandError as error:
        return KIT_BROKEN.format(why=error)
    except Exception:
        return KIT_UNREADABLE
    return None


def target_for(folder: Path, name: str) -> tuple[Path | None, str | None]:
    # Where a new source goes. A name that matches one already there in other letters is that one, so a case-blind disk and a case-sensitive one end up the same.
    inside = sources_folder(folder)
    if inside is None and (folder / SOURCES).exists():
        return None, IS_A_LINK
    same = next((path for path in sorted(inside.iterdir()) if path.name.casefold() == name.casefold()), None) if inside else None
    if same is not None and not is_plain_file(same):
        return None, IS_A_LINK
    return (same or (inside or folder / SOURCES) / name), None


def save(path: Path, text: str) -> None:
    # Written beside the file and moved over it, so the desk never reads half of one. The temporary name isn't a .md file, so it is never taken for a source.
    path.parent.mkdir(exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(text.encode("utf-8"))
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write(path: Path, text: str) -> str | None:
    # What went wrong, if the disk wouldn't take it. Nothing is left half done.
    try:
        save(path, text)
    except OSError as error:
        logger.warning("Could not write %s: %s", path.name, error)
        return NOT_WRITTEN
    return None
