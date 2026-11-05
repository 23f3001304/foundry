"""Turns a finished deck into pictures of its slides, so a maker and the reviewer see what a reader sees. A graphic already is a picture.

This never raises and never hangs. It says in one plain sentence when no pictures could be made, and the work carries on without them.
The pictures go in a folder beside the deck and are never part of the work.

It never closes or disturbs anything a person has open. A renderer only ever sees a temporary copy of the deck, PowerPoint is used only when none is running already, nothing is ever forced closed, and one that hangs is left as it is.
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
POWERPOINT_OPEN = "PowerPoint is open on this machine, so no pictures are available and it was left alone; carry on without them."
LEFT_STUCK = "PowerPoint stopped answering, so it was left as it is and no more pictures will be made until these tools restart; carry on without them."
NOT_MADE = "No pictures of this file were made, so judge what you can from its words and say that you had no pictures."
OFFICE_FOLDERS = ("Microsoft Office/root/Office16", "Microsoft Office/Office16")
# What the script exits with when it finds a PowerPoint it did not start.
OPEN_ALREADY = 3
# What it exits with when the PowerPoint it quit last time still hasn't gone.
STILL_GOING = 4
STILL_LEAVING = "PowerPoint was still closing after the last pictures, so none are available this time and it was left alone; carry on without them."
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCK = "foundry-powerpoint.lock"
# Which PowerPoint this render quit, as its process number and start time, and the same for one not yet seen to go. Makers are separate processes, so the second lives beside the lock.
QUIT_NOTE = "quit-note.txt"
LEAVING = Path(tempfile.gettempdir()) / "foundry-powerpoint-leaving.txt"
# The scripts wait 20 seconds for PowerPoint to go. This is the longer limit on the step that only watches.
WATCH_SECONDS = 30


@dataclass(frozen=True)
class Pictures:
    paths: list[str] = field(default_factory=list)
    # Why there are none, when that is worth saying. A file that has no slides and is no picture, such as the copy, has nothing to say.
    why_none: str = ""


class Unavailable(RuntimeError):
    """A renderer that can't be used now, and the one plain sentence that says why. Stuck means something may still hold the temporary copy."""

    def __init__(self, why: str, stuck: bool = False) -> None:
        super().__init__(why)
        self.why, self.stuck = why, stuck


# Paths reach the script through its environment, so a file name is never read as a command.
# It leaves at once if any PowerPoint is running, because that may be a person's. So the one it starts is its own, until a person opens a deck in it: PowerPoint is one process for the whole machine.
# The one exception is the PowerPoint a render quit and did not see go, named by its process number and start time, alone and with no window. It only ever waits for that one, and starts its own only once nothing is running. So a wrong call costs a wait and touches nothing.
# It closes only the temporary copy it opened, gives PowerPoint its prompts back, and quits only if nothing at all is left that a person could be using. If it can't tell, it leaves it running.
# The pause is for whatever a person asked of PowerPoint while it was busy, which only happens once it is free: seen with real PowerPoint, a window asked for during the slides opened after them.
# It notes which PowerPoint it is quitting, and doesn't wait: with real PowerPoint a wait in here ran its whole length with PowerPoint still there. Watching it go is the separate step below.
POWERPOINT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$running = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $leaving = $false
    try {
        $leaving = $env:FOUNDRY_LEAVING_ID -and ($running.Count -eq 1) -and ("$($running[0].Id)" -eq $env:FOUNDRY_LEAVING_ID) -and ("$($running[0].StartTime.Ticks)" -eq $env:FOUNDRY_LEAVING_START) -and ($running[0].MainWindowHandle -eq 0)
    } catch { $leaving = $false }
    if (-not $leaving) { exit 3 }
    try { $running[0] | Wait-Process -Timeout 20 -ErrorAction Stop } catch { exit 4 }
    if (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue) { exit 3 }
}
$app = New-Object -ComObject PowerPoint.Application
$ours = $null
try {
    $found = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
    if ($found.Count -eq 1) { $ours = $found[0] }
    $app.DisplayAlerts = 1
    $deck = $null
    try {
        $deck = $app.Presentations.Open($env:FOUNDRY_DECK, -1, 0, 0)
        foreach ($slide in $deck.Slides) {
            $name = 'slide-{0:d2}.png' -f $slide.SlideIndex
            $slide.Export((Join-Path $env:FOUNDRY_PICTURES_FOLDER $name), 'PNG', [int]$env:FOUNDRY_PICTURE_WIDTH, [int]$env:FOUNDRY_PICTURE_HEIGHT)
        }
    } finally {
        if ($deck) { $deck.Close() }
    }
} finally {
    $quit = $false
    try {
        $app.DisplayAlerts = 2
        Start-Sleep -Seconds 2
        $now = @(Get-Process -Name POWERPNT)
        $quit = $ours -and ($now.Count -eq 1) -and ($now[0].Id -eq $ours.Id) -and ($app.Visible -eq 0) -and ($app.Presentations.Count -eq 0) -and ($app.Windows.Count -eq 0) -and ($app.ProtectedViewWindows.Count -eq 0)
    } catch { $quit = $false }
    if ($quit) { try { [IO.File]::WriteAllText($env:FOUNDRY_RENDER_NOTE, "$($ours.Id) $($ours.StartTime.Ticks)") } catch { } }
    if ($quit) { $app.Quit() }
    $slide = $null
    $deck = $null
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    $app = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
}
exit 0
"""

# Watches the PowerPoint a render just quit, and can do nothing else to it. It has gone if nothing has that number and start time.
LEAVING_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$found = Get-Process -Id ([int]$env:FOUNDRY_LEAVING_ID) -ErrorAction SilentlyContinue
if (-not $found) { exit 0 }
if ("$($found.StartTime.Ticks)" -ne $env:FOUNDRY_LEAVING_START) { exit 0 }
try { $found | Wait-Process -Timeout 20 -ErrorAction Stop } catch { exit 4 }
exit 0
"""

# True once PowerPoint has hung in this process, so no later call waits on it again.
_gave_up = False
# What was left running after a hang. Held so it is never tidied away while it may still finish by itself.
_left_running: list[subprocess.Popen] = []


def _start(command: list[str], env: dict[str, str] | None) -> subprocess.Popen:
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW, start_new_session=sys.platform != "win32")


def _run(command: list[str], seconds: float, env: dict[str, str] | None = None) -> None:
    # Stops the program this call started at the timeout. Where a process group exists, it goes with what it started. Elsewhere that goes on alone, in a profile and a folder of its own.
    process = _start(command, env)
    try:
        code = process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        raise
    if code:
        raise subprocess.CalledProcessError(code, command[0])


def _wait_alone(command: list[str], seconds: float, env: dict[str, str] | None = None) -> int:
    # Waits for the program and gives its exit code. Past the timeout it is left running, because stopping it could take a person's PowerPoint with it.
    process = _start(command, env)
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        _left_running.append(process)
        raise


def _powerpoint_installed() -> bool:
    if sys.platform != "win32":
        return False
    roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)")]
    return any((Path(root) / folder / "POWERPNT.EXE").exists() for root in roots if root for folder in OFFICE_FOLDERS)


@contextmanager
def _one_at_a_time(seconds: float) -> Iterator[None]:
    # One PowerPoint serves the whole machine, so a second call would find the first's running and take it for a person's. The operating system drops the lock if the holder dies.
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


def _powershell(script: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")]


def _read_note(path: Path) -> tuple[str, str] | None:
    # A note that can't be read or makes no sense is no evidence of anything.
    try:
        parts = path.read_text(encoding="ascii").split()
    except (OSError, ValueError):
        return None
    return (parts[0], parts[1]) if len(parts) == 2 and all(part.isdigit() for part in parts) else None


def _named(note: tuple[str, str] | None) -> dict[str, str]:
    process, started = note or ("", "")
    return {"FOUNDRY_LEAVING_ID": process, "FOUNDRY_LEAVING_START": started}


def _forget_leaving() -> None:
    try:
        LEAVING.unlink(missing_ok=True)
    except OSError as error:
        logger.warning("Could not clear the note of a PowerPoint leaving: %s", error)


def _watch_it_go(quit_note: Path) -> None:
    # Only for a PowerPoint this render quit, and still inside the lock, so the next call doesn't take it for a person's. The pictures are made by now, so nothing here can cost them.
    ours = _read_note(quit_note)
    if not ours:
        return
    try:
        # Written first, so the evidence is there even if this process dies while watching.
        LEAVING.write_text(" ".join(ours), encoding="ascii")
        code = _wait_alone(_powershell(LEAVING_SCRIPT), WATCH_SECONDS, env={**os.environ, **_named(ours)})
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not see PowerPoint go after making pictures: %s", error)
        return
    if code == 0:
        _forget_leaving()


def powerpoint(deck: Path, folder: Path, seconds: float) -> bool:
    """Through PowerPoint itself, where it is installed and not already open. In a program of its own, so that a dialog or a hang inside PowerPoint can only ever cost the timeout, and only once."""
    global _gave_up
    if not _powerpoint_installed():
        return False
    if _gave_up:
        raise Unavailable(LEFT_STUCK)
    started = time.monotonic()
    with _one_at_a_time(seconds):
        left = max(1.0, seconds - (time.monotonic() - started))
        quit_note = folder / QUIT_NOTE
        env = {**os.environ, "FOUNDRY_DECK": str(deck), "FOUNDRY_PICTURES_FOLDER": str(folder), "FOUNDRY_PICTURE_WIDTH": str(SLIDE_WIDTH), "FOUNDRY_PICTURE_HEIGHT": str(SLIDE_HEIGHT), "FOUNDRY_RENDER_NOTE": str(quit_note), **_named(_read_note(LEAVING))}
        try:
            code = _wait_alone(_powershell(POWERPOINT_SCRIPT), left, env=env)
        except subprocess.TimeoutExpired:
            _gave_up = True
            logger.warning("PowerPoint did not finish %s in %.0f seconds. It was left running, and this process will not use it again.", deck.name, left)
            raise Unavailable(LEFT_STUCK, stuck=True) from None
        # Past the first look, whichever one the note named has gone.
        if code not in (OPEN_ALREADY, STILL_GOING):
            _forget_leaving()
        _watch_it_go(quit_note)
    if code == OPEN_ALREADY:
        raise Unavailable(POWERPOINT_OPEN)
    if code == STILL_GOING:
        raise Unavailable(STILL_LEAVING)
    if code:
        raise subprocess.CalledProcessError(code, "powershell.exe")
    return True


def soffice(deck: Path, folder: Path, seconds: float) -> bool:
    """Through LibreOffice, which makes a PDF, and pdftoppm, which makes a picture of each page. LibreOffice alone gives only the first slide as a picture."""
    office, pages = shutil.which("soffice"), shutil.which("pdftoppm")
    if not office or not pages:
        return False
    deadline = time.monotonic() + seconds
    with tempfile.TemporaryDirectory(prefix="foundry-soffice-", ignore_cleanup_errors=True) as temporary:
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


def _publish(made: Path, folder: Path, count: int, stamp: str) -> Pictures:
    # Only a finished set replaces what is there, so a render that fails never empties the folder under another. The stamp goes last, because it says the set is whole.
    folder.mkdir(parents=True, exist_ok=True)
    _clear(folder)
    for number in range(1, count + 1):
        name = PICTURE.format(number=number)
        shutil.move(str(made / name), str(folder / name))
    (folder / STAMP).write_text(stamp, encoding="ascii")
    return Pictures(_made(folder, count))


def _render(deck: Path, folder: Path, count: int, stamp: str, seconds: float) -> Pictures:
    if not RENDERERS:
        return Pictures([], NO_RENDERER)
    # A temporary copy, always. A deck someone has open in PowerPoint comes back as their own window if it is opened by its path, and closing it would close theirs.
    work = Path(tempfile.mkdtemp(prefix="foundry-render-"))
    held, tried, why = False, False, ""
    try:
        copy = work / "deck.pptx"
        shutil.copyfile(deck, copy)
        deadline = time.monotonic() + seconds
        for renderer in RENDERERS:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            made = Path(tempfile.mkdtemp(dir=work))
            try:
                ran = renderer(copy, made, left)
            except Unavailable as error:
                why, held = why or error.why, held or error.stuck
                continue
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                logger.warning("%s could not make pictures of %s: %s", getattr(renderer, "__name__", "A renderer"), deck.name, error)
                tried = True
                continue
            tried = tried or ran
            if ran and _made(made, count):
                return _publish(made, folder, count, stamp)
        return Pictures([], why or (COULD_NOT if tried else NO_RENDERER))
    finally:
        # After a hang something may still hold the copy, and may yet finish with it.
        if not held:
            shutil.rmtree(work, ignore_errors=True)


def _stored(folder: Path, count: int, stamp: str) -> list[str]:
    stamped = folder / STAMP
    return _made(folder, count) if stamped.is_file() and stamped.read_text(encoding="ascii") == stamp else []


def fresh_pictures(path: Path | str) -> Pictures:
    """The pictures already made for this version of a file, and never any new ones. The desk uses this, because it does everything on one loop and a render would stop every card and message."""
    file = Path(path)
    kind = file.suffix.lower()
    try:
        if not file.is_file() or kind not in (*GRAPHIC_KINDS, ".pptx"):
            return Pictures()
        if kind in GRAPHIC_KINDS:
            return Pictures([str(file)])
        count = _slide_count(file)
        if count and (paths := _stored(file.parent / LOOKS / file.stem, count, hashlib.sha256(file.read_bytes()).hexdigest())):
            return Pictures(paths)
    except Exception as error:
        logger.warning("Could not read the pictures of %s: %s", file.name, error)
    return Pictures([], NOT_MADE)


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
        if paths := _stored(folder, count, stamp):
            return Pictures(paths)
        return _render(file, folder, count, stamp, seconds)
    except Exception as error:
        # Pictures help a person judge the work. Nothing about making them may ever stop it.
        logger.warning("Could not make pictures of %s: %s", file.name, error)
        return Pictures([], COULD_NOT)
