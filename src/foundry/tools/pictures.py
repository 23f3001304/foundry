"""Turns a finished deck into pictures of its slides, so a maker and the reviewer see what a reader sees. A graphic already is a picture.

This never raises and never hangs. It says in one plain sentence when no pictures could be made, and the work carries on without them.
The pictures go in a folder beside the deck and are never part of the work.
"""

import base64
import hashlib
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation

logger = logging.getLogger(__name__)

# The folder the pictures go in. The desk refuses anything in it as work.
LOOKS = "foundry-looks"
PICTURE = "slide-{number:02d}.png"
STAMP = "made-from.txt"
SLIDE_WIDTH, SLIDE_HEIGHT = 1600, 900
RENDER_SECONDS = 120
OFF = "FOUNDRY_PICTURES"
GRAPHIC_KINDS = (".png", ".jpg", ".jpeg")
NO_RENDERER = "No program on this machine can turn slides into pictures, so carry on without them."
COULD_NOT = "The slides could not be turned into pictures this time, so carry on without them."
NOT_THERE = "That file is not there, so there is nothing to look at."
OFFICE_FOLDERS = ("Microsoft Office/root/Office16", "Microsoft Office/Office16")
# How long PowerPoint gets to close by itself after a call, before it is closed for it.
CLOSING_SECONDS = 5
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCK = "foundry-powerpoint.lock"


@dataclass(frozen=True)
class Pictures:
    paths: list[str] = field(default_factory=list)
    # Why there are none, when that is worth saying. A file that has no slides and is no picture, such as the copy, has nothing to say.
    why_none: str = ""


# Paths reach the script through its environment, so a file name is never read as a command. It closes PowerPoint only when no one else's deck is open in it.
POWERPOINT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
    $app.DisplayAlerts = 1
    $deck = $app.Presentations.Open($env:FOUNDRY_DECK, -1, 0, 0)
    try {
        foreach ($slide in $deck.Slides) {
            $name = 'slide-{0:d2}.png' -f $slide.SlideIndex
            $slide.Export((Join-Path $env:FOUNDRY_PICTURES_FOLDER $name), 'PNG', [int]$env:FOUNDRY_PICTURE_WIDTH, [int]$env:FOUNDRY_PICTURE_HEIGHT)
        }
    } finally {
        $deck.Close()
    }
} finally {
    if ($app.Presentations.Count -eq 0) { $app.Quit() }
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
"""


def _kill_tree(process: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=10, creationflags=NO_WINDOW, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        process.kill()


def _run(command: list[str], seconds: float, env: dict[str, str] | None = None) -> None:
    # Stops the program and whatever it started at the timeout. subprocess.run stops only the program itself, and then waits on what it started.
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW, start_new_session=sys.platform != "win32")
    try:
        code = process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        process.wait(timeout=10)
        raise
    if code:
        raise subprocess.CalledProcessError(code, command[0])


def _powerpoint_installed() -> bool:
    if sys.platform != "win32":
        return False
    roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)")]
    return any((Path(root) / folder / "POWERPNT.EXE").exists() for root in roots if root for folder in OFFICE_FOLDERS)


def _powerpoint_ids() -> set[int]:
    try:
        listed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(line.split('","')[1]) for line in listed.splitlines() if line.startswith('"') and line.count('","') >= 1}


def _kill(process_id: int) -> None:
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(process_id)], capture_output=True, timeout=10, creationflags=NO_WINDOW, check=False)
    except (OSError, subprocess.SubprocessError):
        logger.warning("Could not close PowerPoint process %s", process_id)


def _close_what_this_call_started(before: set[int], wait: float) -> None:
    # Only what was not running before this call, so nobody's own PowerPoint is ever touched.
    deadline = time.monotonic() + wait
    while (left := _powerpoint_ids() - before) and time.monotonic() < deadline:
        time.sleep(0.25)
    for process_id in sorted(left):
        _kill(process_id)


@contextmanager
def _one_at_a_time(seconds: float) -> Iterator[None]:
    # One PowerPoint serves the whole machine, and a call that closes it would pull it from under another. The operating system drops the lock if the holder dies.
    if sys.platform != "win32":
        yield
        return
    import msvcrt

    deadline = time.monotonic() + seconds
    with open(Path(tempfile.gettempdir()) / LOCK, "a+b") as lock:
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired("waiting for PowerPoint", seconds) from None
                time.sleep(0.25)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def powerpoint(deck: Path, folder: Path, seconds: float) -> bool:
    """Through PowerPoint itself, where it is installed. In a program of its own, so that a dialog or a hang inside PowerPoint can only ever cost the timeout."""
    if not _powerpoint_installed():
        return False
    started = time.monotonic()
    with _one_at_a_time(seconds):
        left = max(1.0, seconds - (time.monotonic() - started))
        before = _powerpoint_ids()
        script = base64.b64encode(POWERPOINT_SCRIPT.encode("utf-16-le")).decode("ascii")
        env = {**os.environ, "FOUNDRY_DECK": str(deck), "FOUNDRY_PICTURES_FOLDER": str(folder), "FOUNDRY_PICTURE_WIDTH": str(SLIDE_WIDTH), "FOUNDRY_PICTURE_HEIGHT": str(SLIDE_HEIGHT)}
        try:
            _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", script], left, env=env)
        except BaseException:
            _close_what_this_call_started(before, 0)
            raise
        _close_what_this_call_started(before, CLOSING_SECONDS)
    return True


def soffice(deck: Path, folder: Path, seconds: float) -> bool:
    """Through LibreOffice, which makes a PDF, and pdftoppm, which makes a picture of each page. LibreOffice alone gives only the first slide as a picture."""
    office, pages = shutil.which("soffice"), shutil.which("pdftoppm")
    if not office or not pages:
        return False
    deadline = time.monotonic() + seconds
    with tempfile.TemporaryDirectory(prefix="foundry-soffice-") as temporary:
        temp = Path(temporary)
        # A profile of its own, so a LibreOffice someone has open neither blocks this nor gets the job.
        _run([office, "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation={(temp / 'profile').as_uri()}", "--convert-to", "pdf", "--outdir", str(temp), str(deck)], seconds)
        _run([pages, "-png", "-scale-to-x", str(SLIDE_WIDTH), "-scale-to-y", str(SLIDE_HEIGHT), str(temp / f"{deck.stem}.pdf"), str(folder / "page")], max(1.0, deadline - time.monotonic()))
    # pdftoppm numbers its pages with as many digits as the last one needs, so they are named again here.
    for page in folder.glob("page-*.png"):
        page.replace(folder / PICTURE.format(number=int(page.stem.rsplit("-", 1)[1])))
    return True


RENDERERS: tuple[Callable[[Path, Path, float], bool], ...] = (powerpoint, soffice)


def _slide_count(deck: Path) -> int | None:
    # A file that is no deck is never shown to a renderer, where it could stop on a dialog until the timeout.
    try:
        return len(Presentation(str(deck)).slides)
    except Exception as error:
        logger.warning("Could not read %s as a deck: %s", deck.name, error)
        return None


def _made(folder: Path, count: int) -> list[str]:
    wanted = [folder / PICTURE.format(number=number) for number in range(1, count + 1)]
    return [str(path) for path in wanted] if all(path.is_file() for path in wanted) else []


def _clear(folder: Path) -> None:
    for old in (*folder.glob("slide-*.png"), *folder.glob("page-*.png"), folder / STAMP):
        old.unlink(missing_ok=True)


def _render(deck: Path, folder: Path, count: int, stamp: str, seconds: float) -> Pictures:
    if not RENDERERS:
        return Pictures([], NO_RENDERER)
    tried = False
    deadline = time.monotonic() + seconds
    for renderer in RENDERERS:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            ran = renderer(deck, folder, left)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            logger.warning("%s could not make pictures of %s: %s", getattr(renderer, "__name__", "A renderer"), deck.name, error)
            tried = True
            _clear(folder)
            continue
        tried = tried or ran
        if ran and (paths := _made(folder, count)):
            (folder / STAMP).write_text(stamp, encoding="ascii")
            return Pictures(paths)
        _clear(folder)
    return Pictures([], COULD_NOT if tried else NO_RENDERER)


def pictures_of(path: Path | str, seconds: float = RENDER_SECONDS) -> Pictures:
    """The pictures of a finished deck or graphic, made if they are not there for this version of the file."""
    file = Path(path)
    kind = file.suffix.lower()
    try:
        if not file.is_file():
            return Pictures([], NOT_THERE)
        if kind in GRAPHIC_KINDS:
            return Pictures([str(file)])
        if kind != ".pptx":
            return Pictures()
        if os.environ.get(OFF, "").strip().casefold() == "off":
            return Pictures([], NO_RENDERER)
        count = _slide_count(file)
        if not count:
            return Pictures([], COULD_NOT)
        folder = file.parent / LOOKS / file.stem
        stamp = hashlib.sha256(file.read_bytes()).hexdigest()
        stamped = folder / STAMP
        if stamped.is_file() and stamped.read_text(encoding="ascii") == stamp and (paths := _made(folder, count)):
            return Pictures(paths)
        folder.mkdir(parents=True, exist_ok=True)
        _clear(folder)
        return _render(file, folder, count, stamp, seconds)
    except Exception as error:
        # Pictures help a person judge the work. Nothing about making them may ever stop it.
        logger.warning("Could not make pictures of %s: %s", file.name, error)
        return Pictures([], COULD_NOT)
