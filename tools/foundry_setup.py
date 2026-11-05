"""One command from a fresh clone to a running Foundry: ./setup.sh on macOS and Linux, setup.ps1 on Windows. Those two only find uv and run this.

Each step checks whether it is already done, so a run that stopped halfway is finished by running it again. What it makes is in .foundry and the git-ignored .env and .venv, under a Docker project name of its own, in the agents' folder under ~/.switch, and in uv's own Python and cache. --stop stops only processes it recorded starting, checked by number and start time, and --reset removes only what it recorded making.

This file uses only the standard library, because it runs before Foundry's packages are installed.
"""

import argparse
import dataclasses
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

REPO = Path(__file__).resolve().parent.parent

SWITCH_GIT = "https://github.com/sandbox-quantum/switch"
# The commit these steps were tested at.
PINNED_COMMIT = "2d72c57596506e510bcfea5bb5b267a482403ed0"
SHORT_COMMIT = PINNED_COMMIT[:7]
# Switch's compose file takes one version for all its images, and its example says latest, which moves. These are the images Foundry's demos were run on, so a judge gets the same ones.
IMAGES = {
    "switch": "ghcr.io/sandbox-quantum/switch-core@sha256:03b2ea9caa38f235878f3d872ca99dee74c6bda7a731ea01a209edc739699c1d",
    "gateway": "ghcr.io/sandbox-quantum/gateway@sha256:f9049a07c35d0e17253116fa0b2bca9872005bb06e38735a7a52093963732079",
    "setup": "ghcr.io/sandbox-quantum/setup@sha256:4e046b650cc79fb8a1d3495e3393278b3658ca538f4ece6eae89caf033f79e27",
}
COMPOSE_FILE = Path("deploy") / "local" / "standalone-docker-compose.yml"
LONG_RUNNING = ("postgres", "mattermost", "switch", "gateway")
CONTROLLER_PACKAGE = "@switch-console/agent-controller"
CONTROLLER_CLI = "packages/agent-controller/dist/cli.mjs"

# The keys Switch's deploy/local/generate-env-secrets.sh fills at the pinned commit, with SECRET_KEYS and the controller's secret after them.
SWITCH_SECRETS = ("DB_PASSWORD", "DB_OWNER_PASSWORD", "AGENT_REGISTRATION_TOKEN", "GATEWAY_ADMIN_PASSWORD", "MATTERMOST_ADMIN_PASSWORD", "MATTERMOST_USER_PASSWORD", "SECRET_KEYS", "CONTROLLER_TOKEN_SECRET")
# What is never to reach the screen from Foundry's own .env.
FOUNDRY_SECRETS = ("SWITCH_PASSWORD", "MATTERMOST_ADMIN_PASSWORD", "FOUNDRY_DESK_KEY", "FOUNDRY_DEMO_PASSWORD", "FOUNDRY_DASHBOARD_SECRET")
# Where Foundry keeps its data, by the setting that says so. A real setup's are under .foundry/data.
FOUNDRY_DATA = {"FOUNDRY_BUFFER_DB": "foundry-buffer.db", "FOUNDRY_LOG_DB": "foundry-log.db", "FOUNDRY_WORK_DB": "foundry-work.db", "FOUNDRY_JOBS_DB": "foundry-jobs.db", "FOUNDRY_INPUTS_DIR": "foundry-inputs"}
# What setup itself puts in .foundry. state.json goes last, so a reset that stops halfway can be run again.
OWN_IN_HOME = ("switch", "controller-data", "data", "logs", "corepack", "pnpm-store", "try", "try.json", "images.yml", "images.yml.tmp", "state.json.tmp")
PORT_NAMES = {"api": "Switch API", "mattermost": "Mattermost", "gateway": "Switch gateway", "postgres": "Postgres", "dashboard": "Foundry dashboard"}
WINDOWS_TIME = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z")
# What ps prints for a start time in the C locale, as in Thu Nov 5 12:00:00 2026 once its padding is gone.
PS_TIME = re.compile(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2} \d\d:\d\d:\d\d \d{4}")
# What asking about a process number can come back with. Not being able to ask is a third answer, and nothing is stopped or dropped on the strength of it.
OURS, GONE, OTHERS, UNKNOWN = "ours", "gone", "someone else's", "can't tell"
DEFAULT_PORTS = {"api": 8000, "mattermost": 8065, "gateway": 3000, "postgres": 5432, "dashboard": 8100}
PORT_SETTINGS = {"api": "API_HOST_PORT", "mattermost": "MATTERMOST_HOST_PORT", "gateway": "GATEWAY_HOST_PORT", "postgres": "POSTGRES_HOST_PORT"}
# The console's own package.json asks for it, and for pnpm 10.28, which corepack gets from the same file.
NODE_MAJOR = 24
# Switch's images, the console packages and Foundry's Python packages, with some room.
DISK_GB = 10
LINKS = {
    "git": "https://git-scm.com/downloads",
    "docker": "https://docs.docker.com/get-docker/",
    "node": "https://nodejs.org/en/download",
    "claude": "https://claude.com/claude-code",
}


@dataclass(frozen=True)
class Demo:
    label: str
    # The scripted scene that plays it, if it has one.
    scene: str | None
    plays: str


# The same names as DEMOS in scripts/demo_seed.py, which says which rooms each one needs.
DEMOS = {
    "it_firm": Demo("IT firm: a Delivery Manager and three Team Leads who owe figures", "it_firm", "uv run --env-file .env python scripts/demo_people.py play it_firm, after setting FOUNDRY_SET_TIMES as the README's step 7 says"),
    "investment_firm": Demo("Investment firm: an Analyst Lead and five offices", "investment_firm", "uv run --env-file .env python scripts/demo_people.py play investment_firm"),
    "agency": Demo("Marketing agency: two clients, each with agents of its own", "agency", "uv run --env-file .env python scripts/demo_people.py play agency"),
    "coffee_shop": Demo("Coffee shop: one room, and you type the request yourself", None, "open the lalten room in Mattermost and ask for a deck, as the README's step 6 says"),
}

FAIL_ENV_NOT_OURS = "There is already a .env here that setup did not write, so nothing was changed. Run this from a fresh clone, or move that .env somewhere else first."
FAIL_CLONE = "Git could not fetch Switch. Check your internet connection."
FAIL_COMPOSE = "Docker could not start Switch's containers. The usual causes are Docker having stopped or a full disk."
FAIL_HEALTHY = "Switch's containers started but Switch did not become healthy in time. It can be slow the first time, so give it a minute."
FAIL_BRIDGE = "Switch came up but its Mattermost connection did not appear in time. It can be slow the first time, so give it a minute."
FAIL_BUILD = "The agent controller did not build. Check your internet connection and disk space."
FAIL_ENROLL = "The agent controller could not enrol with Switch."
FAIL_CONTROLLER = "The agent controller did not come online."
FAIL_FILE_IN_USE = "{path} could not be changed, most likely because something still has it open. Close whatever is using it and run this again."
FAIL_CLAUDE_NOT_READY = "The agent controller is running but says Claude Code is not ready. Sign in with claude auth login in this same terminal."
FAIL_SYNC = "uv could not install Foundry's Python packages. Check your internet connection."
FAIL_DESK_REGISTER = "Switch would not register the desk."
FAIL_ROOMS = "The demo's rooms and agents could not all be made."
FAIL_DESK = "The desk stopped as soon as it started."
FAIL_DASHBOARD = "The dashboard did not start."
FAIL_SWITCH_UNREADABLE = "Git could not read Switch's copy in .foundry/switch, so it was left as it is, with its settings. To see why, run git -C .foundry/switch status."
FAIL_OLD_VOLUME_RECORDED = "Docker still has this Foundry's database in volume {volume}, but the settings with its passwords are gone, and new passwords can't open it. To start over, run this with --reset."
FAIL_OLD_VOLUME = "Docker still has a database in volume {volume} from an earlier Foundry in this same folder, and new passwords can't open it. Setup has no record of making it, so it left it. If you don't need it, run docker compose -p {project} down -v and docker volume rm {volume}."
FAIL_STATE = ".foundry/state.json can't be read, so setup can't tell what it made, and nothing was changed. To start over, end what is running from here yourself and delete the .foundry folder."
FAIL_ENV_TEXT = "{name} isn't plain UTF-8 text, so setup can't read it. PowerShell's > can write a file that way. Save it as UTF-8."
FAIL_RESET_NO_DOCKER = "Docker isn't answering, so setup can't remove its containers and nothing was changed: start Docker and run this again."
FAIL_RESET_DOWN = "Docker could not remove the containers and data of project {project}, so nothing else was removed. The details are in {log}. Run this again when Docker is working."
FAIL_PORT_CHOSEN = "Port {port}, which this setup chose for the {service}, is taken by something else now. Close whatever is using it. To start over on other ports, run this with --reset."
FAIL_SWITCH_NOT_OURS = "There is already a .foundry/switch folder that setup did not make, so it left it exactly as it is and changed nothing. Move it somewhere else, or run this from a fresh clone."
FAIL_LOCK = "Git left a lock file at .foundry/switch/.git/index.lock, and setup can't show that no git is using it, so it left it. If no git is running, delete that file."
AGENTS_NO_ENV = "The agents' folder {path} stays, because Switch's settings in .foundry/switch, which show the port it belongs to, are gone. Delete it yourself if you don't need it."
AGENTS_NO_MARK = "The agents' folder {path} stays, because it has no mark saying setup made it for this folder. Delete it yourself if it is yours."
AGENTS_SHARED = "The agents' folder {path} stays, because another Foundry folder on this machine also uses it. Only this folder's mark in it was removed."
# A file with this start in the agents' folder says which clone uses it. The controller names its own folders there from a name that starts with a letter or digit and never lists the folder, so it can't meet one.
OWNER_PREFIX = ".foundry-owner-"
FAIL_UNSAFE ="Setup won't remove {path}, because it can't show that setup made it: it is not where setup would have put it, so .foundry/state.json or a link may have been changed. Nothing was removed. Look at it, remove it yourself if it is yours, and run this again."
FAIL_CANT_TELL = "Setup could not check whether the {name} it started earlier is still running, so it started nothing new. This is usually a busy computer, so give it a minute."
FAIL_NO_START_TIME = "Setup could not ask the computer when the program it just started began, so it ended it again. This is usually a busy computer, so wait a minute and run this again."
WARN_NOT_PRIVATE = "Setup could not make {name} readable only by you, so anyone who can open this folder can read it."
FAIL_PORT_REFUSED = "Port {port} for the {service} is in use, and setup can't go on without a port for it. Close whatever is using it."
FAIL_PORT_NOBODY = "Port {port} for the {service} is in use. Nobody is here to ask, so nothing was changed. To use {alternative} instead, run this with --yes."
FAIL_UNKNOWN_DEMO = "There is no demo called {demo}. The demos are {demos}."
RUN_AGAIN = "When that is fixed, run this again. It carries on from here."
STOPPED = "stopped"
NOT_RUNNING = "was not running"
NOT_CONFIRMED = "left alone, because process {pid} can't be confirmed as the one setup started"
WOULD_NOT_STOP = "would not stop (process {pid}). Close it yourself and run this again"
CANT_TELL = "can't be checked just now (process {pid}), so setup kept its record of it and did nothing to it"
CANT_TELL_AGAIN = "Setup could not ask the computer about everything it started, so it kept its record of that and stopped only what it could be sure of. This is usually a busy computer: run this again in a minute."
MAKERS_LEFT = "  Left running, because setup can't prove they are its own: makers' tool servers from this folder, with process numbers {pids}. To close them, close the agent sessions using them or end those numbers yourself."
UNEXPECTED = "Something unexpected stopped this step. The details are in {log}."


class Failure(Exception):
    """What went wrong and what to do, in words for the person running this."""


@dataclass(frozen=True)
class Result:
    code: int
    output: str


@dataclass(frozen=True)
class Reply:
    # 0 when nothing answered.
    status: int
    data: object
    cookies: Mapping[str, str]


@dataclass(frozen=True)
class Process:
    pid: int
    # When it started, so a number that now belongs to another program is never stopped.
    started: str


@dataclass(frozen=True)
class Clash:
    service: str
    port: int
    alternative: int


@dataclass(frozen=True)
class Step:
    name: str
    # How long it honestly takes, when it is slow enough to say.
    time: str
    done: Callable[[], bool]
    run: Callable[[], None]


class Machine:
    """Everything setup asks of the computer it runs on."""

    _me: str | None = None

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def home(self) -> Path:
        return Path.home()

    def free_gb(self, path: Path) -> float:
        return shutil.disk_usage(path).free / 1024**3

    def port_free(self, port: int) -> bool:
        windows = os.name == "nt"
        # On the other systems, bind alone can be fooled both ways: a port whose last connection is still closing refuses it for a minute though a server could bind it, and, with the option below, a listener on every address doesn't refuse it. So whether something answers is asked first.
        if not windows and self._answers(port):
            return False
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if windows:
                # Without this, Windows lets a second program bind a port another already holds. SO_REUSEADDR there does the same thing, so it is never set.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                # A port just stopped is in TIME_WAIT here, which refuses a plain bind for about a minute though uvicorn and Docker bind it fine.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    @staticmethod
    def _answers(port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(1)
            return probe.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False
        finally:
            probe.close()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def keep_private(self, path: Path) -> bool:
        """Whether the file is now readable only by this user, which the caller says when it isn't."""
        if os.name == "nt":
            return self._private_windows(path)
        self._private_posix(path)
        return True

    def _private_posix(self, path: Path) -> None:
        os.chmod(path, 0o600)

    def _private_windows(self, path: Path) -> bool:
        # Mode bits mean nothing here. What protects a file is its access list, which otherwise inherits whatever the folder allows.
        if self._me is None:
            found = re.search(r"S-1-[\d-]+", self.run(["whoami", "/user", "/fo", "csv", "/nh"], timeout=30).output)
            self._me = found.group() if found else ""
        return bool(self._me) and self.run(["icacls", path, "/inheritance:r", "/grant:r", f"*{self._me}:F"], timeout=30).code == 0

    def run(self, command: list, cwd: Path | None = None, env: Mapping[str, str] | None = None, log: Path | None = None, timeout: float | None = None) -> Result:
        # With a log, what the command says goes there and only there. The caller reads the output only of commands that are asking a question.
        words = [str(part) for part in command]
        try:
            if log is None:
                done = subprocess.run(words, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", timeout=timeout, check=False)
                return Result(done.returncode, done.stdout or "")
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8", errors="replace") as written:
                written.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {Path(words[0]).name} {words[1] if len(words) > 1 else ''}\n")
                written.flush()
                return Result(subprocess.run(words, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=written, stderr=subprocess.STDOUT, timeout=timeout, check=False).returncode, "")
        except subprocess.TimeoutExpired:
            return Result(124, "")
        except OSError:
            return Result(127, "")

    def http(self, method: str, url: str, body: object = None, cookies: Mapping[str, str] | None = None) -> Reply:
        # No proxy: these addresses are all on this machine, and a proxy named in the environment is never sent a password.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if cookies:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        request = urllib.request.Request(url, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with opener.open(request, timeout=15) as answer:
                return Reply(answer.status, _json(answer.read()), _cookies(answer.headers))
        except urllib.error.HTTPError as answer:
            return Reply(answer.code, None, {})
        except (urllib.error.URLError, http.client.HTTPException, OSError):
            return Reply(0, None, {})

    def spawn(self, command: list, cwd: Path, env: Mapping[str, str], log: Path) -> Process:
        # Starts it to outlive this script. On Windows it gets a console no window shows, which everything it starts then shares, so the screen stays clear of flashing windows.
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", errors="replace") as written:
            written.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} started\n")
            written.flush()
            options: dict = {"cwd": cwd, "env": dict(env), "stdin": subprocess.DEVNULL, "stdout": written, "stderr": subprocess.STDOUT, "close_fds": True}
            words = [str(part) for part in command]
            if os.name == "nt":
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                try:
                    process = subprocess.Popen(words, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
                except OSError:
                    process = subprocess.Popen(words, creationflags=flags, **options)
            else:
                process = subprocess.Popen(words, start_new_session=True, **options)
        # Without its start time there is no telling it from a later program with the same number, and a record without one would be useless. A short wait first, because a busy machine can be slow to answer. If it still can't be asked, what was just started is ended again, since it is not recorded and a second run would start another.
        started = None
        for attempt in range(3):
            started = self.started(process.pid)
            if started is not None:
                break
            self.sleep(1)
        if started is None:
            self._end_new(process)
            raise Failure(FAIL_NO_START_TIME)
        return Process(process.pid, started)

    def _end_new(self, process: subprocess.Popen) -> None:
        # Only ever what this machine has just started and still holds, so its number cannot have gone to anything else.
        try:
            if os.name == "nt":
                self.run(["taskkill", "/F", "/T", "/PID", process.pid])
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.kill()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def identity(self, process: Process) -> str:
        """Whether this is the process that was recorded: OURS, GONE when nothing has its number, OTHERS when something else does, and UNKNOWN when the computer could not be asked."""
        if not process.started:
            return OTHERS
        found = self.started(process.pid)
        if found is None:
            return UNKNOWN
        if found == "":
            return GONE
        return OURS if found == process.started else OTHERS

    def alive(self, process: Process) -> bool:
        return self.identity(process) == OURS

    def gone(self, process: Process) -> bool:
        # Nothing has that number now. Not being able to ask is a different answer, and never counts as gone.
        return self.identity(process) == GONE

    def kill(self, process: Process) -> None:
        # The one way anything is stopped: its number and its start time must still match what was recorded, and only then does what it started go with it.
        if process.pid == os.getpid() or not self.alive(process):
            return
        table = self._process_table()
        # The table is read some seconds later on Windows, and the number could have gone to a new program in between.
        if os.name == "nt" and table.get(process.pid, (0, ""))[1] != process.started:
            return
        family = [pid for pid in family_of(table, process.pid) if pid != os.getpid()]
        if os.name == "nt":
            self.run(["taskkill", "/F", *(word for pid in reversed(family) for word in ("/PID", pid))])
            return
        self._signal(process.pid, family, signal.SIGTERM)
        for _ in range(10):
            if not self.alive(process):
                return
            self.sleep(0.5)
        self._signal(process.pid, family, signal.SIGKILL)

    @staticmethod
    def _signal(leader: int, family: list[int], sent: int) -> None:
        # Setup started its processes each in a group of its own, which also reaches a child whose parent has gone. Try mode's is not a leader, so it gets only the signal to its own number.
        try:
            if os.getpgid(leader) == leader:
                os.killpg(leader, sent)
        except OSError:
            pass
        for pid in family:
            try:
                os.kill(pid, sent)
            except OSError:
                pass

    def leftovers(self, repo: Path) -> list[int]:
        # Only ever said out loud, never stopped: a maker's tool server from this folder whose line back to the controller is broken, as a session can outlive what started it. A person running one by hand looks exactly the same.
        wanted = _fold(f"--directory {repo} run python -m foundry.tools.")
        return [pid for pid, line in _processes(self) if pid != os.getpid() and wanted in _fold(line)]

    def git_in_use(self, folder: Path) -> bool | None:
        """Whether any git has this folder in its command line. None when the process list couldn't be read, which shows as this script's own process missing from it."""
        rows = _processes(self)
        if not any(pid == os.getpid() for pid, _ in rows):
            return None
        wanted = _fold(str(folder))
        return any(pid != os.getpid() and "git" in _fold(line).casefold() and wanted in _fold(line) for pid, line in rows)

    def remove_tree(self, path: Path) -> None:
        # A package folder goes deeper than Windows' usual path limit, and git keeps its files read-only.
        target = str(path)
        if os.name == "nt" and not target.startswith("\\\\?\\"):
            target = "\\\\?\\" + target

        def writable(function, name, _error) -> None:
            os.chmod(name, stat.S_IWRITE)
            function(name)

        for attempt in range(5):
            try:
                shutil.rmtree(target, onexc=writable)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(2)

    def started(self, pid: int) -> str | None:
        """When the process with this number started, which no later process with the same number can share. "" when nothing has that number, and None when it couldn't be found out."""
        if os.name == "nt":
            shown = self.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", f'Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}" | ForEach-Object {{ $_.CreationDate.ToUniversalTime().ToString("o") }}'], timeout=30)
            if shown.code != 0:
                return None
            found = WINDOWS_TIME.search(shown.output)
            return found.group() if found else ("" if not shown.output.strip() else None)
        return self._started_posix(pid)

    def _started_posix(self, pid: int) -> str | None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return ""
        except OSError:
            pass
        # Linux keeps it in ticks since boot, which never moves. What ps prints there is worked out from the clock and can differ by a second between two asks.
        try:
            fields = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace").rpartition(")")[2].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            return "" if fields[0] == "Z" else f"{boot}:{fields[19]}"
        except (OSError, IndexError):
            pass
        return self._ps_started(pid)

    def _ps_started(self, pid: int) -> str | None:
        # One flag for each field. Two in one flag (stat=,lstart=) is read differently by different systems, and on a Mac that has never been run, so it is not relied on.
        shown = self.run(["ps", "-o", "stat=", "-o", "lstart=", "-p", pid], env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}, timeout=10)
        return parse_ps_start(shown.output) if shown.code == 0 else None

    def _process_table(self) -> dict[int, tuple[int, str]]:
        # Each process's parent, and when it started where a number can outlive its process as someone's parent.
        rows: dict[int, tuple[int, str]] = {}
        if os.name == "nt":
            shown = self.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", 'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId) $($_.CreationDate.ToUniversalTime().ToString(\'o\'))" }'], timeout=60)
        else:
            shown = self.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], timeout=30)
        for line in shown.output.splitlines():
            words = line.split()
            if len(words) >= 2 and words[0].isdigit() and words[1].isdigit():
                rows[int(words[0])] = (int(words[1]), words[2] if len(words) > 2 else "")
        return rows


def _is_port(value: object) -> bool:
    return type(value) is int and 1 <= value <= 65535


def _is_list_of(value: object, ok: Callable[[str], bool] = lambda text: True) -> bool:
    return isinstance(value, list) and all(isinstance(entry, str) and ok(entry) for entry in value)


def state_is_sound(found: Mapping) -> bool:
    """Whether every value in the state file is of the kind setup writes. A path, a name or a number from a hand-edited or damaged file never gets as far as something that deletes, so what reset removes is only ever built from values that passed this."""
    ports = found.get("ports")
    if "ports" in found and not (isinstance(ports, dict) and set(ports) == set(DEFAULT_PORTS) and all(_is_port(port) for port in ports.values())):
        return False
    processes = found.get("processes", {})
    if not isinstance(processes, dict) or not all(isinstance(entry, dict) and type(entry.get("pid")) is int and entry["pid"] > 0 and isinstance(entry.get("started"), str) for entry in processes.values()):
        return False
    created = found.get("created", {})
    if not isinstance(created, dict) or not all(isinstance(value, bool) for value in created.values()):
        return False
    # An image name is handed to docker image rm, so it can't be taken for a flag.
    if not _is_list_of(found.get("pulled_images", []), lambda name: bool(name) and not name.startswith("-") and not any(letter.isspace() for letter in name)):
        return False
    if not (_is_list_of(found.get("before", [])) and _is_list_of(found.get("rooms_made", []))):
        return False
    following = found.get("following", {})
    if not isinstance(following, dict) or not all(isinstance(value, str) for value in following.values()):
        return False
    return all(isinstance(found.get(name, ""), str) for name in ("demo", "packages")) and isinstance(found.get("stack_started", False), bool)


def parse_ps_start(output: str) -> str | None:
    """The start time out of what `ps -o stat= -o lstart= -p N` printed: "" for a process that has ended but not been collected, None when the line isn't one it can read. Padding is dropped, so the same process reads the same."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    state, _, rest = lines[0].strip().partition(" ")
    when = " ".join(rest.split())
    if not state or not PS_TIME.fullmatch(when):
        return None
    return "" if state.startswith("Z") else when


def is_inside(path: Path, parent: Path) -> bool:
    """Whether path, with every .. and link in it followed, is somewhere below parent and not parent itself."""
    try:
        found, root = Path(os.path.realpath(path)), Path(os.path.realpath(parent))
    except (OSError, ValueError):
        return False
    return found != root and found.is_relative_to(root)


def family_of(rows: Mapping[int, tuple[int, str]], root: int) -> list[int]:
    """The process and everything it started, parents first. On Windows a dead parent's number stays on its children and can be reused, so a process older than its supposed parent is not its child. On macOS and Linux an orphan moves to another parent, so this never comes up there."""
    family = [root]
    for parent in family:
        for pid, (ppid, started) in rows.items():
            if ppid == parent and pid not in family and parent in rows and started >= rows[parent][1]:
                family.append(pid)
    return family


def _powershell() -> str:
    return shutil.which("powershell") or shutil.which("pwsh") or "powershell"


def _fold(line: str) -> str:
    # Windows quotes a word with a space in it, and doesn't care about case in a path.
    return line.replace('"', "").casefold() if os.name == "nt" else line


def _processes(machine: Machine) -> list[tuple[int, str]]:
    if os.name == "nt":
        shown = machine.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"], timeout=60)
    else:
        # Twice wide, because macOS cuts a line to fit otherwise.
        shown = machine.run(["ps", "-A", "-ww", "-o", "pid=", "-o", "args="], timeout=30)
    rows = []
    for line in shown.output.splitlines():
        number, _, words = line.strip().partition(" ")
        if number.isdigit():
            rows.append((int(number), words))
    return rows


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _cookies(headers) -> dict[str, str]:
    found = {}
    for line in headers.get_all("Set-Cookie") or []:
        name, _, rest = line.partition("=")
        found[name.strip()] = rest.split(";", 1)[0]
    return found


class Ui:
    """The screen. Everything said goes through here, so a secret it has been told of can't reach it, whatever a message was built from."""

    def __init__(self, out: TextIO | None = None, answers: list[str] | None = None, stdin: bool = False) -> None:
        self.out = out or sys.stdout
        self.answers, self.stdin = answers, stdin
        self.hidden: set[str] = set()

    def secret(self, value: str) -> None:
        if len(value) >= 6:
            self.hidden.add(value)

    def write(self, text: str) -> None:
        for value in sorted(self.hidden, key=len, reverse=True):
            text = text.replace(value, "(hidden)")
        self.out.write(text)
        self.out.flush()

    def say(self, text: str = "") -> None:
        self.write(text + "\n")

    def ask(self, question: str) -> str | None:
        # None when there is nobody to ask, and setup is never left waiting on a pipe.
        self.write(question + " ")
        if self.answers:
            answer = self.answers.pop(0)
            self.write(answer + "\n")
            return answer
        if self.stdin and sys.stdin is not None and sys.stdin.isatty():
            try:
                return input().strip()
            except EOFError:
                pass
        self.write("\n")
        return None


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def fill_env(text: str, values: Mapping[str, str]) -> str:
    # Each value goes on the line that already names it, so the comments stay beside what they explain.
    left = dict(values)
    lines = []
    for line in text.splitlines():
        name = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and name in left:
            lines.append(f"{name}={left.pop(name)}")
        else:
            lines.append(line)
    return "\n".join([*lines, *(f"{name}={value}" for name, value in left.items())]) + "\n"


def switch_env(example: str, ports: Mapping[str, int], token: Callable[[], str] = lambda: secrets.token_hex(32)) -> str:
    values = {name: token() for name in SWITCH_SECRETS}
    values["SECRET_KEYS"] = f"local:{values['SECRET_KEYS']}"
    # Left on, Switch sends people's names to outside avatar services.
    return fill_env(example, {**values, "FEATURE_FLAGS_ENABLED": "agent_management", "THIRD_PARTY_AVATARS_ENABLED": "false", **{setting: str(ports[name]) for name, setting in PORT_SETTINGS.items()}})


def project_name(repo: Path) -> str:
    # Its own, and different for each folder, so two clones never share containers and nothing else's is ever in reach.
    return "foundry-" + hashlib.sha256(str(repo).encode()).hexdigest()[:8]


def plan_ports(wanted: Mapping[str, int], ours: set[int], is_free: Callable[[int], bool]) -> list[Clash]:
    clashes = []
    used = set(wanted.values())
    for service, port in wanted.items():
        if port in ours or is_free(port):
            continue
        alternative = port + 1
        while alternative in used or not is_free(alternative):
            alternative += 1
        used.add(alternative)
        clashes.append(Clash(service, port, alternative))
    return clashes


def _node_major(shown: str) -> int:
    found = re.search(r"v?(\d+)\.", shown)
    return int(found.group(1)) if found else 0


def _quiet_run(machine: Machine, name: str, *arguments: str) -> Result:
    return machine.run([machine.which(name) or name, *arguments], timeout=60)


def missing_prerequisites(repo: Path, machine: Machine) -> list[str]:
    """Everything that stops the real path, each in a sentence or two with where to get it, so a person fixes them all in one go."""
    missing = []
    if not machine.which("git"):
        missing.append(f"Git is not installed. Get it from {LINKS['git']}.")
    if not machine.which("docker"):
        missing.append(f"Docker is not installed, and nothing can install it for you. Get it from {LINKS['docker']}.")
    elif _quiet_run(machine, "docker", "compose", "version").code != 0:
        missing.append(f"Docker is here but its compose command is not. Get a current Docker from {LINKS['docker']}.")
    elif _quiet_run(machine, "docker", "info").code != 0:
        missing.append("Docker is installed but not running. Start Docker Desktop, or the Docker service, and wait until it says it is running. On Linux, your user may also need to be in the docker group.")
    if not machine.which("node"):
        missing.append(f"Node {NODE_MAJOR} or newer is not installed. Get it from {LINKS['node']}.")
    else:
        version = _quiet_run(machine, "node", "--version").output.strip()
        if _node_major(version) < NODE_MAJOR:
            missing.append(f"Node {version or 'here'} is too old, because Switch's console needs Node {NODE_MAJOR} or newer. Get it from {LINKS['node']}.")
        elif not machine.which("corepack") and not machine.which("pnpm"):
            missing.append("Node is here without corepack, which gets the right pnpm. Run npm install -g corepack.")
    missing += _missing_ai_tool(machine)
    if not (repo / ".foundry" / "switch").exists() and machine.free_gb(repo) < DISK_GB:
        missing.append(f"This disk has {machine.free_gb(repo):.0f} GB free, and a first run needs about {DISK_GB} GB. Make some room.")
    if (repo / ".env").exists() and not _env_is_ours(repo):
        missing.append(FAIL_ENV_NOT_OURS)
    return missing


def _missing_ai_tool(machine: Machine) -> list[str]:
    # Claude Code is the one tool that's enough. Codex is never needed, and on its own it can't run Foundry's makers: their tools reach them through a .mcp.json that only Claude Code reads, and the desk asks Claude what each message is.
    if machine.which("claude"):
        if _quiet_run(machine, "claude", "auth", "status").code != 0:
            return ["Claude Code is installed but not signed in. Run claude auth login."]
        return []
    if machine.which("codex") and _quiet_run(machine, "codex", "login", "status").code == 0:
        return [f"Codex is signed in, but it can't run Foundry alone: the makers' deck and picture tools reach them through a file only Claude Code reads. Get Claude Code from {LINKS['claude']}, or see Foundry with no agents at all by running this with --try."]
    return [f"Foundry's agents need Claude Code, signed in. Get it from {LINKS['claude']} and run claude auth login, or see Foundry with no agents at all by running this with --try."]


def _env_is_ours(repo: Path) -> bool:
    state = repo / ".foundry" / "state.json"
    try:
        return bool(json.loads(state.read_text(encoding="utf-8")).get("created", {}).get("env"))
    except (OSError, ValueError):
        return False


def _took(seconds: float) -> str:
    return f"{int(seconds)}s" if seconds < 60 else f"{int(seconds // 60)}m {int(seconds % 60)}s"


def _write_traceback(log: Path) -> None:
    # Inside an except, for whoever needs the details later. Not on the screen.
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as file:
            file.write(traceback.format_exc())
    except OSError:
        pass


def run_steps(steps: list[Step], ui: Ui, log: Path | None = None) -> int:
    for number, step in enumerate(steps, start=1):
        place = f"{number:>2}/{len(steps)}"
        try:
            if step.done():
                ui.say(f"{place}  {step.name}: already done")
                continue
            ui.write(f"{place}  {step.name}{f' ({step.time})' if step.time else ''} ")
            started = time.monotonic()
            with _Dots(ui):
                step.run()
            ui.say(f"done in {_took(time.monotonic() - started)}")
        except Failure as failure:
            ui.say()
            ui.say()
            ui.say(str(failure))
            ui.say(RUN_AGAIN)
            return 1
        except Exception:
            ui.say()
            ui.say()
            written = log or Path("setup.log")
            _write_traceback(written)
            ui.say(UNEXPECTED.format(log=written))
            ui.say(RUN_AGAIN)
            return 1
    return 0


class _Dots:
    """A dot every half minute, so a long step doesn't look stuck."""

    def __init__(self, ui: Ui) -> None:
        self.ui, self.stop = ui, threading.Event()
        self.thread = threading.Thread(target=self._tick, daemon=True)

    def _tick(self) -> None:
        while not self.stop.wait(30):
            self.ui.write(".")

    def __enter__(self) -> "_Dots":
        self.thread.start()
        return self

    def __exit__(self, *_exception) -> None:
        self.stop.set()


class Setup:
    def __init__(self, repo: Path, machine: Machine, ui: Ui, demo: str | None = None, yes: bool = False) -> None:
        self.repo, self.machine, self.ui, self.demo, self.yes = repo, machine, ui, demo, yes
        self.home = repo / ".foundry"
        self.switch = self.home / "switch"
        self.console = self.switch / "console"
        self.controller_data = self.home / "controller-data"
        self.logs = self.home / "logs"
        self.state_file = self.home / "state.json"
        self.images_file = self.home / "images.yml"
        self.switch_env_file = self.switch / ".env"
        self.env_file = repo / ".env"
        self.try_record = self.home / TRY_RECORD
        self.state_broken = False
        self._warned_open = False
        self.state = self._read_state()

    # What it remembers

    def _read_state(self) -> dict:
        try:
            found = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(found, dict) and state_is_sound(found):
                return found
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            pass
        self.state_broken = True
        return {}

    def _save_state(self) -> None:
        if "before" not in self.state:
            # Whatever is in its folder before its first word there isn't its own to remove.
            self.state["before"] = sorted(entry.name for entry in self.home.iterdir()) if self.home.is_dir() else []
        self.home.mkdir(parents=True, exist_ok=True)
        self._write(self.state_file, json.dumps(self.state, indent=2) + "\n")

    def _write(self, path: Path, text: str) -> None:
        # Whole or not at all, so a stop halfway never leaves half a settings file. Private before a word of it is written.
        temporary = path.with_name(path.name + ".tmp")
        temporary.unlink(missing_ok=True)
        os.close(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        try:
            if not self.machine.keep_private(temporary) and not self._warned_open:
                # Said once, and written anyway: refusing would stop setup on a disk with no access lists, which a settings file there can't have.
                self._warned_open = True
                self.ui.say()
                self.ui.say(WARN_NOT_PRIVATE.format(name=self._shown(path)))
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                file.write(text)
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _hide_secrets(self, say: bool = False) -> None:
        for path in (self.switch_env_file, self.env_file):
            try:
                values = self._env_values(path)
            except Failure as unreadable:
                if say:
                    self.ui.say(str(unreadable))
                continue
            for name, value in values.items():
                if value and (name in SWITCH_SECRETS or name in FOUNDRY_SECRETS):
                    self.ui.secret(value)

    def _env_values(self, path: Path) -> dict[str, str]:
        try:
            return parse_env(path.read_text(encoding="utf-8"))
        except OSError:
            return {}
        except UnicodeError:
            raise Failure(FAIL_ENV_TEXT.format(name=self._shown(path))) from None

    def _log(self, name: str) -> Path:
        return self.logs / f"{name}.log"

    def _shown(self, path: Path) -> str:
        return path.relative_to(self.repo).as_posix()

    def _failed(self, message: str, log: str) -> Failure:
        return Failure(f"{message} The details are in {self._shown(self._log(log))}.")

    def project(self) -> str:
        return project_name(self.repo)

    @property
    def ports(self) -> dict[str, int]:
        return self.state["ports"]

    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['api']}"

    def mattermost_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['mattermost']}"

    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['dashboard']}"

    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['gateway']}"

    # Choices, asked before anything slow starts

    def choose_demo(self) -> str:
        if self.demo:
            if self.demo not in DEMOS:
                raise Failure(FAIL_UNKNOWN_DEMO.format(demo=self.demo, demos=", ".join(DEMOS)))
            self.state["demo"] = self.demo
            self._save_state()
            return self.demo
        if self.state.get("demo") in DEMOS:
            return self.state["demo"]
        names = list(DEMOS)
        first = names[0]
        menu = "\n".join(f"  {number}. {DEMOS[name].label}" for number, name in enumerate(names, start=1))
        answer = None if self.yes else self.ui.ask(f"Which demo should its rooms be made for?\n{menu}\nPick a number [1]:")
        if answer is None:
            self.ui.say(f"Making the {DEMOS[first].label.split(':')[0]} demo. Another can be added later with --demo.")
        chosen = first
        if answer and answer.isdigit() and 1 <= int(answer) <= len(names):
            chosen = names[int(answer) - 1]
        self.state["demo"] = chosen
        self._save_state()
        return chosen

    def choose_ports(self) -> dict[str, int]:
        if "ports" in self.state:
            ours = self._ports_held()
            for name, port in self.ports.items():
                if port not in ours and not self.machine.port_free(port):
                    raise Failure(FAIL_PORT_CHOSEN.format(port=port, service=PORT_NAMES[name]))
            return self.ports
        names = {label: name for name, label in PORT_NAMES.items()}
        chosen = dict(DEFAULT_PORTS)
        clashes = plan_ports({PORT_NAMES[name]: port for name, port in DEFAULT_PORTS.items()}, set(), self.machine.port_free)
        for clash in clashes:
            if self.yes:
                self.ui.say(f"Port {clash.port} for the {clash.service} is in use, so it gets {clash.alternative}.")
            else:
                answer = self.ui.ask(f"Port {clash.port} for the {clash.service} is in use by something else. Use {clash.alternative} instead? [Y/n]")
                if answer is None:
                    raise Failure(FAIL_PORT_NOBODY.format(port=clash.port, service=clash.service, alternative=clash.alternative))
                if answer.strip().lower() not in ("", "y", "yes"):
                    raise Failure(FAIL_PORT_REFUSED.format(port=clash.port, service=clash.service))
            chosen[names[clash.service]] = clash.alternative
        self.state["ports"] = chosen
        self._save_state()
        return chosen

    def _ports_held(self) -> set[int]:
        # Whatever a container of this project publishes, whatever the others are doing, so a stop halfway blocks nothing.
        held: set[int] = set()
        if "ports" not in self.state:
            return held
        for row in self._service_rows():
            if row.get("State") not in ("exited", "dead", "created"):
                held |= {entry["PublishedPort"] for entry in row.get("Publishers") or [] if isinstance(entry, dict) and entry.get("PublishedPort")}
        # One that can't be checked is not assumed gone, so its port is not called taken by something else.
        if self._identity("dashboard") in (OURS, UNKNOWN):
            held.add(self.ports["dashboard"])
        return held

    # Docker

    def compose(self, *arguments: str) -> list[str]:
        # Every Docker command that can change anything is built here, so each one names this project and no other.
        return [
            self.machine.which("docker") or "docker", "compose", "-p", self.project(), "--project-directory", str(self.switch),
            "-f", str(self.switch / COMPOSE_FILE), "-f", str(self.images_file), "--profile", "collab", "--profile", "gateway", *arguments,
        ]

    def _service_rows(self) -> list[dict]:
        return self._asked_rows() or []

    def _asked_rows(self) -> list[dict] | None:
        # None when Docker couldn't say, which isn't the same as there being nothing.
        if not self.images_file.exists():
            return []
        shown = self.machine.run(self.compose("ps", "-a", "--format", "json"), timeout=60)
        if shown.code != 0:
            return None
        text = shown.output.strip()
        if text.startswith("["):
            return _json(text.encode()) or []
        rows = [_json(line.encode()) for line in text.splitlines() if line.startswith("{")]
        return [row for row in rows if isinstance(row, dict)]

    def _services_up(self) -> bool:
        running = {row.get("Service") for row in self._service_rows() if row.get("State") == "running"}
        return set(LONG_RUNNING) <= running

    def _pulls(self) -> list[str]:
        # Which images this run will be the one to download, so --reset takes away those and none that were already here.
        shown = self.machine.run(self.compose("config", "--images"), timeout=120)
        images = [line.strip() for line in shown.output.splitlines() if line.strip()] if shown.code == 0 else []
        docker = self.machine.which("docker") or "docker"
        return [image for image in images if self.machine.run([docker, "image", "inspect", image], timeout=60).code != 0]

    # The steps

    def steps(self) -> list[Step]:
        return [
            Step("Checking this machine", "", lambda: False, self.check_machine),
            Step("Choosing ports", "", lambda: False, self.choose_ports),
            Step(f"Getting Switch at {SHORT_COMMIT}", "about 1 minute", self.switch_is_here, self.get_switch),
            Step("Writing Switch's settings with generated secrets", "", self.switch_env_file.exists, self.write_switch_env),
            Step("Starting Switch's containers", "about 10 minutes the first time, for 2.5 GB of downloads", self._services_up, self.start_stack),
            Step("Waiting for Switch to be healthy", "about 2 minutes", self.switch_is_healthy, self.wait_for_switch),
            Step("Building the agent controller", "about 3 minutes", self.controller_is_built, self.build_controller),
            Step("Enrolling the agent controller", "", self.controller_is_enrolled, self.enroll_controller),
            Step("Starting the agent controller", "", self.controller_is_running, self.start_controller),
            Step("Writing Foundry's settings", "", self.foundry_env_is_written, self.write_foundry_env),
            Step("Installing Foundry's Python packages", "about 2 minutes", self.packages_are_in, self.install_packages),
            Step("Registering the desk", "", self.desk_is_registered, self.register_desk),
            Step("Making the demo's rooms and agents", "about 2 minutes", self.rooms_are_made, self.make_rooms),
            Step("Starting the desk", "", self.desk_is_running, self.start_desk),
            Step("Starting the dashboard", "", self.dashboard_is_running, self.start_dashboard),
        ]

    def check_machine(self) -> None:
        missing = missing_prerequisites(self.repo, self.machine)
        if missing:
            raise Failure("Before Foundry can be set up:\n" + "\n".join(f"  - {sentence}" for sentence in missing))
        self.ui.write("ok, ")
        self.choose_demo()

    def switch_is_here(self) -> bool:
        # A folder that was already there before setup's first word is somebody's own, with work in it that a forced checkout would replace, so setup leaves it as it is. One setup started itself is not listed, because its record was saved before the clone was begun.
        before = self.state.get("before", [])
        if "switch" in before:
            if self.switch.exists():
                raise Failure(FAIL_SWITCH_NOT_OURS)
            self.state["before"] = [name for name in before if name != "switch"]
            self._save_state()
        if not (self.switch / "console").is_dir():
            return False
        # Without a git folder of its own, the folder was never finished, and git would answer for the clone around it.
        if not (self.switch / ".git").exists():
            return False
        asked = self.machine.run([self.machine.which("git") or "git", "-C", self.switch, "rev-parse", "-q", "--verify", "HEAD"], timeout=30)
        if asked.code == 0:
            return asked.output.strip() == PINNED_COMMIT
        # A checkout stopped halfway has files but no HEAD yet, which git answers with exit 1 and no words. That is finished in place, which get_switch always does.
        if asked.code == 1 and not asked.output.strip():
            return False
        # Anything else is git failing, which says nothing about the commit, and nothing here is deleted on the strength of it.
        raise Failure(FAIL_SWITCH_UNREADABLE)

    def get_switch(self) -> None:
        # Only this one commit, which is far smaller than the whole history. With its line endings kept, because the containers read these files. Always in place, because the folder holds the .env with this stack's passwords, which git leaves alone and nothing can recover.
        self.switch.mkdir(parents=True, exist_ok=True)
        git = [self.machine.which("git") or "git", "-C", self.switch]
        for arguments in (("init", "-q"), ("config", "core.autocrlf", "false"), ("config", "core.longpaths", "true"), ("fetch", "--depth", "1", SWITCH_GIT, PINNED_COMMIT), ("checkout", "-q", "-f", "FETCH_HEAD")):
            checking_out = arguments[0] == "checkout"
            if checking_out:
                self._clear_stale_lock()
            if self.machine.run([*git, *arguments], log=self._log("switch-clone"), timeout=600).code != 0:
                # A lock left behind makes every checkout fail, which is not the internet's doing.
                if checking_out and self._index_lock().exists():
                    raise Failure(FAIL_LOCK)
                raise self._failed(FAIL_CLONE, "switch-clone")
        # A build from an earlier commit isn't this commit's.
        (self.console / CONTROLLER_CLI).unlink(missing_ok=True)

    def _index_lock(self) -> Path:
        return self.switch / ".git" / "index.lock"

    def _clear_stale_lock(self) -> None:
        """A checkout killed outright leaves the lock git takes, and every later checkout then fails on it. It goes only when it is this one file in the folder setup made, and no git has that folder open."""
        lock = self._index_lock()
        if not lock.exists() and not lock.is_symlink():
            return
        if lock.is_symlink() or not lock.is_file() or not is_inside(lock, self.switch) or self.machine.git_in_use(self.switch) is not False:
            raise Failure(FAIL_LOCK)
        lock.unlink()
        self.ui.write("cleared a lock an interrupted checkout left, ")

    def write_switch_env(self) -> None:
        # Only ever when there is no such file, so a stack's secrets never change under it. A database left with no file has passwords nobody can now give it.
        volume = f"{self.project()}_pgdata"
        if self.machine.run([self.machine.which("docker") or "docker", "volume", "inspect", volume], timeout=60).code == 0:
            raise Failure((FAIL_OLD_VOLUME_RECORDED if self.state.get("stack_started") else FAIL_OLD_VOLUME).format(volume=volume, project=self.project()))
        self._write(self.switch_env_file, switch_env((self.switch / ".env.example").read_text(encoding="utf-8"), self.ports))
        self._hide_secrets()

    def start_stack(self) -> None:
        lines = ["services:"]
        for service, image in IMAGES.items():
            lines += [f"  {service}:", f"    image: {image}"]
        self._write(self.images_file, "\n".join(lines) + "\n")
        if "pulled_images" not in self.state:
            self.state["pulled_images"] = self._pulls()
        self.state["stack_started"] = True
        self._save_state()
        if self.machine.run(self.compose("up", "-d"), log=self._log("switch"), timeout=1800).code != 0:
            raise self._failed(FAIL_COMPOSE, "switch")

    def _sign_in(self) -> Mapping[str, str] | None:
        values = self._env_values(self.switch_env_file)
        answer = self.machine.http("POST", f"{self.api_url()}/gateway/auth/login", {"email": values.get("GATEWAY_ADMIN_EMAIL"), "password": values.get("GATEWAY_ADMIN_PASSWORD")})
        return answer.cookies if answer.status == 200 else None

    def _has_chat_bridge(self, cookies: Mapping[str, str]) -> bool:
        answer = self.machine.http("GET", f"{self.api_url()}/gateway/collaborations", cookies=cookies)
        return isinstance(answer.data, list) and any(isinstance(bridge, dict) and bridge.get("bridge_type") == "mattermost" for bridge in answer.data)

    def switch_is_healthy(self) -> bool:
        if "ports" not in self.state or self.machine.http("GET", f"{self.api_url()}/health").status != 200:
            return False
        cookies = self._sign_in()
        return cookies is not None and self._has_chat_bridge(cookies)

    def wait_for_switch(self) -> None:
        cookies = self._waited(self._sign_in, 60, 5)
        if cookies is None:
            raise self._failed(FAIL_HEALTHY, "switch")
        if not self._waited(lambda: self._has_chat_bridge(cookies), 60, 5):
            raise self._failed(FAIL_BRIDGE, "switch")

    def _waited(self, check: Callable[[], object], tries: int, seconds: float) -> object:
        for _ in range(tries):
            found = check()
            if found:
                return found
            self.machine.sleep(seconds)
        return None

    def _pnpm(self) -> list[str]:
        corepack = self.machine.which("corepack")
        return [corepack, "pnpm"] if corepack else [self.machine.which("pnpm") or "pnpm"]

    def _pnpm_env(self) -> dict[str, str]:
        # Its own copies under .foundry, so --reset can take them away and the machine's own pnpm is left as it was.
        return {**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0", "COREPACK_HOME": str(self.home / "corepack"), "CI": "1"}

    def controller_is_built(self) -> bool:
        return (self.console / CONTROLLER_CLI).is_file()

    def build_controller(self) -> None:
        # Only the controller and what it needs. The whole console also downloads Electron, which nothing here uses.
        wanted = f"{CONTROLLER_PACKAGE}..."
        env = self._pnpm_env()
        steps = (
            [*self._pnpm(), "install", "--frozen-lockfile", "--filter", wanted, "--store-dir", self.home / "pnpm-store"],
            [*self._pnpm(), "--filter", wanted, "run", "build"],
        )
        for command in steps:
            if self.machine.run(command, cwd=self.console, env=env, log=self._log("controller-build"), timeout=1800).code != 0:
                raise self._failed(FAIL_BUILD, "controller-build")

    def _cli(self, *arguments: object) -> list:
        return [self.machine.which("node") or "node", CONTROLLER_CLI, *arguments]

    def controller_is_enrolled(self) -> bool:
        if not (self.controller_data / "controller.db").is_file():
            return False
        return self.machine.run(self._cli("status", "--data-dir", self.controller_data), cwd=self.console, timeout=60).code == 0

    def enroll_controller(self) -> None:
        cookies = self._sign_in()
        answer = self.machine.http("POST", f"{self.api_url()}/gateway/management/enrollment-codes", cookies=cookies) if cookies is not None else None
        code = answer.data.get("code") if answer and isinstance(answer.data, dict) else None
        if not code:
            raise self._failed(FAIL_ENROLL, "controller")
        # What is here from an enrolment that never finished would be refused as another controller's.
        if self.controller_data.exists():
            self.machine.remove_tree(self.controller_data)
        self.ui.secret(code)
        enrolled = self.machine.run(self._cli("enroll", "--server", self.api_url(), "--code", code, "--data-dir", self.controller_data, "--name", self.project(), "--secret-store", "file"), cwd=self.console, log=self._log("controller"), timeout=120)
        if enrolled.code != 0:
            raise self._failed(FAIL_ENROLL, "controller")

    def agents_folder(self) -> Path:
        # Where the controller keeps its agents' working folders, named by Switch after the server's address.
        return self.machine.home() / ".switch" / "agents" / f"127.0.0.1-{self.ports['api']}"

    def _mark(self) -> Path:
        return self.agents_folder() / (OWNER_PREFIX + self.project())

    def _mark_agents_folder(self) -> None:
        # Each clone that uses the folder leaves a mark of its own in it, made or not by this one, so a reset knows whether anyone else is using what it made. Not worth failing a run for.
        folder = self.agents_folder()
        try:
            if self.state.get("created", {}).get("agents_folder"):
                folder.mkdir(parents=True, exist_ok=True)
            if folder.is_dir():
                self._mark().write_text(f"{self.repo}\n", encoding="utf-8")
        except OSError:
            pass

    def _controller_row(self) -> dict | None:
        cookies = self._sign_in()
        if cookies is None:
            return None
        answer = self.machine.http("GET", f"{self.api_url()}/gateway/management/controllers", cookies=cookies)
        rows = answer.data if isinstance(answer.data, list) else []
        return next((row for row in rows if isinstance(row, dict) and row.get("state") == "online"), None)

    def _claude_ready(self, row: Mapping) -> bool:
        # "unknown" passes, as it does for Switch's own check: a machine's own login isn't always one the controller can read.
        providers = (row.get("status") or {}).get("providers") or []
        return any(entry.get("provider") == "claude" and entry.get("installed") and entry.get("auth") not in ("missing", "expired") for entry in providers if isinstance(entry, dict))

    def controller_is_running(self) -> bool:
        if not self._alive("controller"):
            return False
        row = self._controller_row()
        return row is not None and self._claude_ready(row)

    def start_controller(self) -> None:
        if not self._alive("controller"):
            self.state.setdefault("created", {}).setdefault("agents_folder", not self.agents_folder().exists())
            self._mark_agents_folder()
            self._start("controller", self._cli("run", "--data-dir", self.controller_data, "--no-self-update"), self.console, dict(os.environ))
        row = self._waited(self._ready_controller, 30, 3)
        if not row:
            raise self._failed(FAIL_CONTROLLER, "controller")
        if not self._claude_ready(row):
            raise Failure(FAIL_CLAUDE_NOT_READY)

    def _ready_controller(self) -> dict | None:
        # It says it is online before it has looked for its providers, so a moment is given for that too.
        row = self._controller_row()
        if row is None:
            return None
        if self._claude_ready(row):
            return row
        self._seen_unready = getattr(self, "_seen_unready", 0) + 1
        return row if self._seen_unready > 10 else None

    def _foundry_values(self) -> dict[str, str]:
        switch = self._env_values(self.switch_env_file)
        return {
            "SWITCH_URL": self.api_url(),
            "SWITCH_EMAIL": switch.get("GATEWAY_ADMIN_EMAIL", ""),
            "SWITCH_PASSWORD": switch.get("GATEWAY_ADMIN_PASSWORD", ""),
            "MATTERMOST_URL": self.mattermost_url(),
            "MATTERMOST_ADMIN_USER": switch.get("MATTERMOST_ADMIN_USER", ""),
            "MATTERMOST_ADMIN_PASSWORD": switch.get("MATTERMOST_ADMIN_PASSWORD", ""),
            "MATTERMOST_TEAM_NAME": switch.get("MATTERMOST_TEAM_NAME", ""),
            # Claude, with no model, so one signed-in tool runs the whole team. Anything recorded this way is not a cross-vendor review.
            "FOUNDRY_REVIEWER_PROVIDER": "claude",
            "FOUNDRY_REVIEWER_MODEL": "",
            "FOUNDRY_DASHBOARD_PORT": str(self.ports["dashboard"]),
            # In its own folder, so a hand-run Foundry's files in this folder are neither written to nor taken by --reset.
            **{setting: f".foundry/data/{name}" for setting, name in FOUNDRY_DATA.items()},
            # The scripted scenes need it this short, and a person typing in a demo room doesn't want to wait a minute.
            "FOUNDRY_QUIET_SECONDS": "8",
        }

    def foundry_env_is_written(self) -> bool:
        values = self._env_values(self.env_file)
        return all(values.get(name) == value for name, value in self._foundry_values().items())

    def write_foundry_env(self) -> None:
        if self.env_file.exists() and not self.state.get("created", {}).get("env"):
            raise Failure(FAIL_ENV_NOT_OURS)
        self.state.setdefault("created", {})["env"] = True
        self._save_state()
        (self.home / "data").mkdir(parents=True, exist_ok=True)
        text = self.env_file.read_text(encoding="utf-8") if self.env_file.exists() else (self.repo / ".env.example").read_text(encoding="utf-8")
        self._write(self.env_file, fill_env(text, self._foundry_values()))
        self._hide_secrets()

    def _lock_mark(self) -> str:
        try:
            return hashlib.sha256((self.repo / "uv.lock").read_bytes()).hexdigest()
        except OSError:
            return ""

    def packages_are_in(self) -> bool:
        return (self.repo / ".venv").exists() and self.state.get("packages") == self._lock_mark()

    def install_packages(self) -> None:
        self.state.setdefault("created", {}).setdefault("venv", not (self.repo / ".venv").exists())
        self._save_state()
        if self.machine.run([self.machine.which("uv") or "uv", "sync", "--frozen"], cwd=self.repo, log=self._log("packages"), timeout=1800).code != 0:
            raise self._failed(FAIL_SYNC, "packages")
        self.state["packages"] = self._lock_mark()
        self._save_state()

    def _tool(self, log: str, *arguments: str) -> Result:
        return self.machine.run([self.machine.which("uv") or "uv", "run", "--frozen", "--env-file", ".env", "python", *arguments], cwd=self.repo, env={**os.environ, "PYTHONUTF8": "1"}, log=self._log(log), timeout=1200)

    def desk_is_registered(self) -> bool:
        values = self._env_values(self.env_file)
        return bool(values.get("FOUNDRY_DESK_ID") and values.get("FOUNDRY_DESK_KEY"))

    def register_desk(self) -> None:
        if self._tool("desk-register", "tools/register_desk.py").code != 0:
            raise self._failed(FAIL_DESK_REGISTER, "desk-register")
        self._hide_secrets()

    def rooms_are_made(self) -> bool:
        return self.state.get("demo") in self.state.get("rooms_made", []) and bool(self._env_values(self.env_file).get("FOUNDRY_ROOMS"))

    def make_rooms(self) -> None:
        demo = self.state["demo"]
        scene = DEMOS[demo].scene
        calls = [("scripts/demo_seed.py", demo)]
        if scene:
            calls += [("scripts/demo_people.py", "ensure", scene), ("scripts/seed_history.py", scene)]
        for call in calls:
            if self._tool("rooms", *call).code != 0:
                raise self._failed(FAIL_ROOMS, "rooms")
        self.state.setdefault("rooms_made", []).append(demo)
        self._save_state()
        self._hide_secrets()

    # Processes it starts

    def _record(self, name: str) -> Process | None:
        found = self.state.get("processes", {}).get(name)
        return Process(found["pid"], found["started"]) if found else None

    def _identity(self, name: str) -> str | None:
        """What the computer says of the process recorded under this name: None when nothing is recorded, otherwise OURS, GONE, OTHERS or UNKNOWN."""
        process = self._record(name)
        return self.machine.identity(process) if process is not None else None

    def _alive(self, name: str) -> bool:
        # A run that can't tell whether its process is there stops, since going on would start a second one beside it.
        found = self._identity(name)
        if found == UNKNOWN:
            raise Failure(FAIL_CANT_TELL.format(name=name))
        return found == OURS

    def _start(self, name: str, command: list, cwd: Path, env: Mapping[str, str]) -> None:
        process = self.machine.spawn(command, cwd, env, self._log(name))
        self.state.setdefault("processes", {})[name] = dataclasses.asdict(process)
        self._save_state()

    def _stop_one(self, name: str) -> tuple[str, str]:
        """Stops a process this setup started, if it can still show it is that process, and says what happened in a few words, with whether that is settled: "done", "stuck" or "unsure". The record goes only when it is done."""
        process = self._record(name)
        said, result = self._end(process) if process else (NOT_RUNNING, "done")
        if result == "done":
            self.state.get("processes", {}).pop(name, None)
            self._save_state()
        return said, result

    def _end(self, process: Process) -> tuple[str, str]:
        found = self.machine.identity(process)
        if found == UNKNOWN:
            return CANT_TELL.format(pid=process.pid), "unsure"
        if found == GONE:
            return NOT_RUNNING, "done"
        if found == OTHERS:
            return NOT_CONFIRMED.format(pid=process.pid), "done"
        self.machine.kill(process)
        if self._waited(lambda: self.machine.identity(process) in (GONE, OTHERS), 10, 0.5):
            return STOPPED, "done"
        if self.machine.identity(process) == UNKNOWN:
            return CANT_TELL.format(pid=process.pid), "unsure"
        return WOULD_NOT_STOP.format(pid=process.pid), "stuck"

    def _stop_try(self) -> tuple[str, str] | None:
        # None when there is no record of one. A record is what makes it setup's own to stop.
        try:
            found = json.loads(self.try_record.read_text(encoding="utf-8"))
            process = Process(int(found["pid"]), str(found["started"]))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            self.try_record.unlink(missing_ok=True)
            return None
        said, result = self._end(process)
        if result == "done":
            self.try_record.unlink(missing_ok=True)
        return said, result

    def _stop_processes(self) -> bool:
        had_controller = self._record("controller") is not None
        results = []
        ended_try = self._stop_try()
        if ended_try:
            self.ui.say(f"  try mode: {ended_try[0]}")
            results.append(ended_try[1])
        for name in ("dashboard", "desk", "controller"):
            said, result = self._stop_one(name)
            self.ui.say(f"  {name}: {said}")
            results.append(result)
        if "unsure" in results:
            self.ui.say(CANT_TELL_AGAIN)
        if had_controller:
            strays = self.machine.leftovers(self.repo)
            if strays:
                self.ui.say(MAKERS_LEFT.format(pids=", ".join(str(pid) for pid in strays)))
        return all(result == "done" for result in results)

    def _rooms_mark(self) -> str:
        values = self._env_values(self.env_file)
        return values.get("FOUNDRY_ROOMS", "") + "|" + values.get("FOUNDRY_PACKS", "")

    def _python(self) -> Path:
        return self.repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _follows_rooms(self, name: str) -> bool:
        # Both read the rooms when they start, so one running from before a new demo's rooms were made is out of date.
        return self._alive(name) and self.state.get("following", {}).get(name) == self._rooms_mark()

    def _start_following(self, name: str, module: str) -> None:
        # A second one is never started beside one that is still there or can't be checked.
        said, result = self._stop_one(name)
        if result != "done":
            raise Failure(f"The {name} from an earlier run {said}.")
        env = {**os.environ, **self._env_values(self.env_file), "PYTHONUTF8": "1"}
        self._start(name, [self._python(), "-m", module], self.repo, env)
        self.state.setdefault("following", {})[name] = self._rooms_mark()
        self._save_state()

    def desk_is_running(self) -> bool:
        return self._follows_rooms("desk")

    def start_desk(self) -> None:
        self._start_following("desk", "foundry")
        self.machine.sleep(5)
        if not self._alive("desk"):
            raise self._failed(FAIL_DESK, "desk")

    def dashboard_is_running(self) -> bool:
        return self._follows_rooms("dashboard")

    def start_dashboard(self) -> None:
        self._start_following("dashboard", "foundry.dashboard")
        if not self._waited(lambda: self.machine.http("GET", f"{self.dashboard_url()}/login").status == 200, 20, 1):
            raise self._failed(FAIL_DASHBOARD, "dashboard")

    # The commands

    def install(self) -> int:
        if self.state_broken:
            self.ui.say(FAIL_STATE)
            return 1
        self._hide_secrets()
        self.ui.say("Setting up Foundry. A first run takes about 20 minutes, most of it downloads. It is safe to stop and run again.")
        self.ui.say()
        code = run_steps(self.steps(), self.ui, self._log("setup"))
        if code == 0:
            self.finish()
        return code

    def finish(self) -> None:
        demo = DEMOS[self.state["demo"]]
        self.ui.say()
        self.ui.say("Foundry is running on real agents.")
        self.ui.say(f"  Dashboard   {self.dashboard_url()}")
        self.ui.say(f"  Mattermost  {self.mattermost_url()}")
        self.ui.say(f"  Switch      {self.gateway_url()}")
        self.ui.say()
        self.ui.say("The logins were generated here and are not shown. They are in the .env file in this folder:")
        self.ui.say("  Dashboard and Switch: SWITCH_EMAIL and SWITCH_PASSWORD")
        self.ui.say("  Mattermost: MATTERMOST_ADMIN_USER and MATTERMOST_ADMIN_PASSWORD")
        self.ui.say()
        self.ui.say(f"To play it: {demo.plays}.")
        self.ui.say("To see how it's doing, run this with --status. To stop it, --stop. To remove all of it, --reset.")

    def status(self) -> int:
        self._hide_secrets(say=True)
        if self.state_broken:
            self.ui.say(FAIL_STATE)
            return 1
        running = running_try(self.try_record, self.machine)
        if running:
            self.ui.say(f"Try mode may be running at http://127.0.0.1:{running['port']}, but the computer could not be asked just now." if running["unsure"] else f"Try mode is running at http://127.0.0.1:{running['port']}.")
        if not self.state.get("ports"):
            self.ui.say("Foundry has not been set up here yet. Run this with no options to set it up, or with --try to look around with made-up data.")
            return 0
        asked = self._asked_rows()
        rows = {row.get("Service"): row for row in asked or []}
        self.ui.say(f"Foundry in {self.repo}, Docker project {self.project()}")
        for service in LONG_RUNNING:
            shown = "Docker is not answering" if asked is None else rows.get(service, {}).get("State") or "not created"
            self.ui.say(f"  {service:<12}{shown}")
        for name in ("controller", "desk", "dashboard"):
            found = self._identity(name)
            shown = "running" if found == OURS else "can't tell just now" if found == UNKNOWN else "stopped"
            self.ui.say(f"  {name:<12}{shown}")
        self.ui.say(f"  Demo rooms  {', '.join(self.state.get('rooms_made', [])) or 'none yet'}")
        self.ui.say()
        self.ui.say(f"  Dashboard   {self.dashboard_url()}")
        self.ui.say(f"  Mattermost  {self.mattermost_url()}")
        self.ui.say(f"  Switch      {self.gateway_url()}")
        self.ui.say("  Logins are in the .env file in this folder, and in .foundry/switch/.env.")
        return 0

    def stop(self, closing: str = "Stopped what setup started. Run this again to start it all back up.") -> int:
        self._hide_secrets(say=True)
        if self.state_broken:
            self.ui.say(FAIL_STATE)
            return 1
        if not self.state.get("processes") and not self.state.get("stack_started") and not self.try_record.exists():
            self.ui.say("Nothing to stop. Setup has not started anything here.")
            return 0
        only_try = not self.state.get("processes") and not self.state.get("stack_started")
        fine = self._stop_processes()
        if only_try:
            return 0 if fine else 1
        if self.state.get("stack_started") and self.images_file.exists():
            if self.machine.run(self.compose("stop"), log=self._log("switch"), timeout=300).code == 0:
                self.ui.say("  Switch's containers: stopped")
            else:
                fine = False
                self.ui.say(f"  Switch's containers: Docker could not stop them, so they may still be running. Start Docker if it is off and run this again. The details are in {self._shown(self._log('switch'))}.")
        if fine and closing:
            self.ui.say(closing)
        return 0 if fine else 1

    def _removals(self) -> list[str]:
        created = self.state.get("created", {})
        lines = []
        if self.state.get("stack_started"):
            lines.append(f"the Docker containers, network and data of project {self.project()}")
        if self.state.get("processes") or self.try_record.exists():
            lines.append("first, it stops whatever setup started that is still running: the agent controller, the desk, the dashboard and try mode")
        if self.state.get("pulled_images"):
            lines.append(f"{len(self.state['pulled_images'])} Docker images only this setup downloaded: {', '.join(self.state['pulled_images'])}")
        lines.append(".foundry, with Switch's copy, the controller, Foundry's databases and uploads, and the logs")
        if created.get("env"):
            lines.append(".env, which setup wrote")
        if created.get("venv"):
            lines.append(".venv, which setup made")
        if self._agents_plan()[0] == "remove":
            lines.append(str(self.agents_folder()))
        return lines

    def _kept(self) -> list[str]:
        # What is here and was not recorded as made by setup. Its own data is all in .foundry/data, so these foundry files are somebody else's.
        created = self.state.get("created", {})
        kept = [path.name for path in sorted(self.repo.glob("foundry-*.db*"))]
        if (self.repo / "foundry-inputs").exists():
            kept.append("foundry-inputs")
        if self.env_file.exists() and not created.get("env"):
            kept.append(".env")
        if (self.repo / ".venv").exists() and not created.get("venv"):
            kept.append(".venv")
        if "ports" in self.state and not created.get("agents_folder") and self.agents_folder().exists():
            kept.append(str(self.agents_folder()))
        if self.home.is_dir():
            kept += [f".foundry/{entry.name}" for entry in sorted(self.home.iterdir()) if entry.name != "state.json" and (entry.name not in OWN_IN_HOME or entry.name in self.state.get("before", []))]
        return kept

    def _down(self) -> Result:
        log = self._log("switch")
        if self.images_file.exists() and (self.switch / COMPOSE_FILE).exists():
            return self.machine.run(self.compose("down", "-v", "--remove-orphans"), log=log, timeout=300)
        # Its files have gone, and the project name alone still reaches its containers and nothing else. From a folder with nothing in it, so a compose file in whatever folder this was run from is not read as well.
        with tempfile.TemporaryDirectory(prefix="foundry-down-") as empty:
            return self.machine.run([self.machine.which("docker") or "docker", "compose", "-p", self.project(), "down", "-v", "--remove-orphans"], cwd=Path(empty), log=log, timeout=300)

    def _agents_root(self) -> Path:
        return self.machine.home() / ".switch" / "agents"

    def _agents_proof(self) -> str:
        """Whether the folder is the one this clone's port names: "unsafe" when it is not even a folder of that name directly under the agents' root, or when the port in the state file differs from this clone's own Switch settings, which setup wrote. "unproven" when those settings are gone or don't say."""
        port = self.ports["api"]
        folder = self.agents_folder()
        if folder.name != f"127.0.0.1-{port}" or Path(os.path.realpath(folder)) != Path(os.path.realpath(self._agents_root())) / folder.name:
            return "unsafe"
        try:
            written = self._env_values(self.switch_env_file).get("API_HOST_PORT")
        except Failure:
            return "unproven"
        if written is None:
            return "unproven"
        return "ours" if written == str(port) else "unsafe"

    def _agents_plan(self) -> tuple[str, str]:
        """What reset does with the agents' folder, and why when it leaves it: "none" (nothing of setup's there), "remove", "leave" or "unsafe". It goes only when setup made it, this clone's own mark is in it, and no other clone's is."""
        if "ports" not in self.state or not self.state.get("created", {}).get("agents_folder") or not self.agents_folder().exists():
            return "none", ""
        proof = self._agents_proof()
        if proof == "unsafe":
            return "unsafe", ""
        folder = self.agents_folder()
        if proof == "unproven":
            return "leave", AGENTS_NO_ENV.format(path=folder)
        try:
            if not self._mark().is_file():
                return "leave", AGENTS_NO_MARK.format(path=folder)
            if [entry for entry in folder.iterdir() if entry.name.startswith(OWNER_PREFIX) and entry.name != self._mark().name]:
                return "leave", AGENTS_SHARED.format(path=folder)
        except OSError:
            return "leave", AGENTS_NO_MARK.format(path=folder)
        return "remove", ""

    def _drop_mark(self) -> None:
        # Only this clone's own mark, and only where it sits below the agents' root.
        if "ports" not in self.state:
            return
        try:
            mark = self._mark()
            if mark.is_file() and is_inside(mark, self._agents_root()):
                mark.unlink()
        except OSError:
            pass

    def _unsafe_removals(self) -> list[str]:
        """What reset would remove that is not where setup puts it, which only an edited state file or a link can cause. Looked at before anything is removed."""
        created = self.state.get("created", {})
        before = self.state.get("before", [])
        unsafe = [str(self.home / name) for name in OWN_IN_HOME if name not in before and (self.home / name).exists() and not is_inside(self.home / name, self.home)]
        if created.get("venv") and (self.repo / ".venv").exists() and not is_inside(self.repo / ".venv", self.repo):
            unsafe.append(str(self.repo / ".venv"))
        if self._agents_plan()[0] == "unsafe":
            unsafe.append(str(self.agents_folder()))
        return unsafe

    def _remove_below(self, path: Path, parent: Path) -> None:
        # The one way reset removes a folder, so none is removed that does not sit below the folder it belongs in.
        if not is_inside(path, parent):
            raise Failure(FAIL_UNSAFE.format(path=path))
        self.machine.remove_tree(path)

    def reset(self) -> int:
        self._hide_secrets(say=True)
        if self.state_broken:
            self.ui.say(FAIL_STATE)
            return 1
        if not self.state:
            self.ui.say("Nothing to remove. Setup has no record of making anything here.")
            return 0
        unsafe = self._unsafe_removals()
        if unsafe:
            for path in unsafe:
                self.ui.say(FAIL_UNSAFE.format(path=path))
            return 1
        if self.state.get("stack_started") and _quiet_run(self.machine, "docker", "info").code != 0:
            self.ui.say(FAIL_RESET_NO_DOCKER)
            return 1
        kept = self._kept()
        # Decided now, while Switch's settings that prove it are still there.
        agents, agents_why = self._agents_plan()
        self.ui.say("This removes what setup recorded making, and nothing else:")
        for line in self._removals():
            self.ui.say(f"  - {line}")
        if kept:
            self.ui.say(f"These were not made by setup, so they stay: {', '.join(kept)}.")
        if agents_why:
            self.ui.say(agents_why)
        answer = "yes" if self.yes else self.ui.ask("Type yes to remove all of it:")
        if answer is None:
            self.ui.say("Nobody is here to answer, so nothing was removed. To say yes in advance, add --yes.")
            return 1
        if answer.strip().lower() != "yes":
            self.ui.say("Nothing was removed.")
            return 0
        if not self._stop_processes():
            self.ui.say("Nothing else was removed.")
            return 1
        created = self.state.get("created", {})
        if self.state.get("stack_started") and self._down().code != 0:
            self.ui.say(FAIL_RESET_DOWN.format(project=self.project(), log=self._shown(self._log("switch"))))
            return 1
        docker = self.machine.which("docker") or "docker"
        # Never with force, so an image another container has come to use stays.
        images_left = [image for image in self.state.get("pulled_images", []) if self.machine.run([docker, "image", "rm", image], timeout=120).code != 0]
        if agents == "remove":
            self._remove_below(self.agents_folder(), self._agents_root())
        else:
            self._drop_mark()
        if created.get("env"):
            self.env_file.unlink(missing_ok=True)
            self.env_file.with_name(".env.tmp").unlink(missing_ok=True)
        if created.get("venv") and (self.repo / ".venv").exists():
            self._remove_below(self.repo / ".venv", self.repo)
        self._remove_own_folder()
        self.state = {}
        self.ui.say("Removed. Run this again to set it all up from the start.")
        if images_left:
            self.ui.say(f"Docker kept {len(images_left)} of the images setup downloaded, because something else uses them.")
        if kept:
            self.ui.say(f"Kept, because setup did not make them: {', '.join(kept)}.")
        if agents_why:
            self.ui.say(agents_why)
        return 0

    def _remove_own_folder(self) -> None:
        before = self.state.get("before", [])
        for name in OWN_IN_HOME:
            path = self.home / name
            if name not in before and path.is_dir():
                self._remove_below(path, self.home)
            elif name not in before:
                path.unlink(missing_ok=True)
        self.state_file.unlink(missing_ok=True)
        try:
            self.home.rmdir()
        except OSError:
            # Something of someone else's is in it.
            pass

    def try_mode(self) -> int:
        return try_mode(self.repo, self.machine, self.ui, self)


# Whatever a real setup or a person's own shell has named, none of it is passed on to try mode.
NOT_FOR_TRY_MODE = ("FOUNDRY_", "SWITCH_", "MATTERMOST_", "ANTHROPIC_", "SARVAM_", "SLACK_", "TELEGRAM_", "WHATSAPP_", "GOOGLE_", "OPENAI_", "UV_ENV_FILE", "CLAUDE_", "VIRTUAL_ENV")
NO_UV = "Try mode needs uv, and uv is not on your PATH. Get it from https://docs.astral.sh/uv/getting-started/installation/."


TRY_RECORD = "try.json"
# What tools/try_foundry.py returns when it has said why it stopped itself.
TRY_ALREADY_SAID = 3
TRY_RUNNING = "Try mode is already running at http://127.0.0.1:{port}. Its sign-in page shows the made-up login. To stop it, press Ctrl+C where it started or run this with --stop."
TRY_UNSURE = "Setup could not check whether the try mode it recorded, at http://127.0.0.1:{port}, is still running, so it started none beside it. This is usually a busy computer: run this again in a minute."
TRY_DID_NOT_RUN ="Try mode has stopped. If it never showed an address, uv probably could not fetch Python or Foundry's packages, which the first run needs the internet for."


def running_try(record: Path, machine: Machine) -> dict | None:
    """The try mode recorded here, if that same process is still running. A record of anything else is stale, and goes."""
    try:
        found = json.loads(record.read_text(encoding="utf-8"))
        process = Process(int(found["pid"]), str(found["started"]))
        port = int(found["port"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        record.unlink(missing_ok=True)
        return None
    found = machine.identity(process)
    if found in (OURS, UNKNOWN):
        # "unsure" when the computer could not be asked: the record stays, and nothing is started beside what may be running.
        return {"pid": process.pid, "started": process.started, "port": port, "unsure": found == UNKNOWN}
    record.unlink(missing_ok=True)
    return None


def clean_env(env: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in env.items() if not name.upper().startswith(NOT_FOR_TRY_MODE)}


def try_mode(repo: Path, machine: Machine, ui: Ui, build: "Setup") -> int:
    # It needs only uv. Its data and settings live in its own folder, it never reads a .env, and tools/try_foundry.py listens on this machine and connects to nothing.
    running = running_try(build.try_record, machine)
    if running:
        if running["unsure"]:
            ui.say(TRY_UNSURE.format(port=running["port"]))
            return 1
        ui.say(TRY_RUNNING.format(port=running["port"]))
        return 0
    uv = machine.which("uv")
    if not uv:
        ui.say(NO_UV)
        return 1
    if not build.state_broken:
        build.state.setdefault("created", {}).setdefault("venv", not (repo / ".venv").exists())
        build._save_state()
    ui.say("Try mode: the dashboard with made-up data. No agents, no Docker, and it never reads your .env.")
    if not (repo / ".venv").exists():
        ui.say("The first time, uv downloads Python and Foundry's packages, about 2 minutes. After that nothing leaves this machine.")
    command = [uv, "run", "--frozen", "--no-dev", "python", "tools/try_foundry.py"]
    try:
        code = subprocess.run(command, cwd=repo, env={**clean_env(os.environ), "PYTHONUTF8": "1"}, check=False).returncode
    except KeyboardInterrupt:
        ui.say("Try mode stopped.")
        return 0
    if code not in (0, TRY_ALREADY_SAID):
        ui.say(TRY_DID_NOT_RUN)
    return code


def parser() -> argparse.ArgumentParser:
    ask = argparse.ArgumentParser(prog="setup", description="Sets Foundry up from a fresh clone, and can be run again at any point.")
    command = ask.add_mutually_exclusive_group()
    command.add_argument("--try", dest="try_mode", action="store_true", help="the dashboard with made-up data and no agents. It needs only uv")
    command.add_argument("--stop", action="store_true", help="stop what setup started")
    command.add_argument("--status", action="store_true", help="show what is up")
    command.add_argument("--reset", action="store_true", help="remove only what setup recorded making, after asking")
    ask.add_argument("--demo", choices=list(DEMOS), help="which demo to make rooms for. It is asked if not given")
    ask.add_argument("--yes", action="store_true", help="say yes to whatever it would ask, including --reset's question, so with --reset it removes without asking")
    return ask


def main(arguments: list[str] | None = None) -> int:
    chosen = parser().parse_args(arguments)
    ui = Ui(stdin=True)
    try:
        build = Setup(REPO, Machine(), ui, demo=chosen.demo, yes=chosen.yes)
        if chosen.try_mode:
            return build.try_mode()
        if chosen.stop:
            return build.stop()
        if chosen.status:
            return build.status()
        if chosen.reset:
            return build.reset()
        return build.install()
    except KeyboardInterrupt:
        ui.say()
        ui.say("Stopped. Run this again to carry on from here.")
        return 130
    except Failure as failure:
        ui.say(str(failure))
        return 1
    except OSError as error:
        ui.say(FAIL_FILE_IN_USE.format(path=str(error.filename or "A file here").removeprefix("\\\\?\\")))
        return 1
    except Exception:
        log = REPO / ".foundry" / "logs" / "setup.log"
        _write_traceback(log)
        ui.say(UNEXPECTED.format(log=log))
        return 1


if __name__ == "__main__":
    sys.exit(main())
