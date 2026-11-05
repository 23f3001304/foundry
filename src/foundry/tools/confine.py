"""Where a client's own maker tools may write and read. Tools with no brand pin, which a department's shared makers have, go where they are told as they always did.

A client's makers are set up with two folders in their tools' environment: the client's brand folder (FOUNDRY_BRAND_DIR) and the maker's own working folder (FOUNDRY_MAKER_DIR).
Their tools then write only inside the maker's own folder, and read a picture only from it or from the brand folder. Where a path really is decides, so a junction, a link, a `..`
or a spelling in other letters leads to the same place it does on the disk. This confines the tools. An agent's own file access outside its tools is not confined by it.
"""

import os
from pathlib import Path

from foundry.brand import pinned_folder
from foundry.text import on_the_network
from foundry.tools.layout import MakerError

MAKER_PIN = "FOUNDRY_MAKER_DIR"

NO_MAKER_FOLDER = (
    f"{MAKER_PIN} is not set, so this tool does not know which folder is your own, and it will not write or read anywhere. "
    "The makers' tools are set up again with tools/setup_makers.py."
)
OUTSIDE = "Make files only in your own folder, {folder}. {name} is not in it."
PICTURE_OUTSIDE = "A picture must be in your own folder or in this client's brand folder, and {name} is in neither."


def pinned() -> bool:
    return pinned_folder() is not None


def _maker_folder() -> Path:
    text = os.environ.get(MAKER_PIN, "").strip()
    if not text:
        raise MakerError(NO_MAKER_FOLDER)
    return Path(text)


def _real(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(real: str, folder: Path) -> bool:
    outer = _real(folder)
    return real != outer and real.startswith(outer + os.sep)


def _resolved(text: str, folder: Path) -> Path:
    # A short path is the maker's own folder's, so "poster.png" is made there and not wherever the tool happens to be running.
    path = Path(text)
    return path if path.is_absolute() else folder / path


def output(out_path: str | Path) -> Path:
    """The real path a tool may write. With no pin, where it was asked. With one, only inside the maker's own folder."""
    if not pinned():
        return Path(out_path).resolve()
    folder, text = _maker_folder(), str(out_path)
    # A path on another machine is refused as written, because finding out where it leads would contact the machine.
    if on_the_network(text) or not _inside(_real(_resolved(text, folder)), folder):
        raise MakerError(OUTSIDE.format(folder=folder, name=Path(text).name))
    return Path(os.path.realpath(_resolved(text, folder)))


def picture(text: str) -> Path:
    """The path of a picture a tool may read. With no pin, as it was given. With one, only from the maker's own folder or the client's brand folder."""
    brand = pinned_folder()
    if brand is None:
        return Path(text)
    folder = _maker_folder()
    if on_the_network(text):
        raise MakerError(PICTURE_OUTSIDE.format(name=Path(text).name))
    path = _resolved(text, folder)
    real = _real(path)
    if not (_inside(real, folder) or _inside(real, brand)):
        raise MakerError(PICTURE_OUTSIDE.format(name=Path(text).name))
    return Path(os.path.realpath(path))
