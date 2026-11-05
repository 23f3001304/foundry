"""One command from a fresh clone to a running Foundry: ./setup.sh on macOS and Linux, .\\setup.ps1 on Windows. Those two only find uv and run this.

Each step checks whether it is already done, so a run that stopped halfway is finished by running it again. Everything it makes lives in .foundry and the two git-ignored .env files, under a Docker project name of its own, and --stop and --reset only touch that.

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
import socket
import stat
import subprocess
import sys
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
PORT_NAMES = {"api": "Switch API", "mattermost": "Mattermost", "gateway": "Switch gateway", "postgres": "Postgres", "dashboard": "Foundry dashboard"}
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
FAIL_COMPOSE = "Docker could not start Switch's containers. Check that Docker Desktop is running and has disk space."
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
FAIL_PORT_CHOSEN = "Port {port}, which this Foundry's {service} uses, is taken by something else now. Close whatever is using it. To start over on other ports, run this with --reset."
FAIL_PORT_REFUSED = "Port {port} for the {service} is in use, and setup can't go on without a port for it. Close whatever is using it."
FAIL_PORT_NOBODY = "Port {port} for the {service} is in use. Nobody is here to ask, so nothing was changed. To use {alternative} instead, run this with --yes."
FAIL_UNKNOWN_DEMO = "There is no demo called {demo}. The demos are {demos}."
RUN_AGAIN = "When that is fixed, run this again. It carries on from here."
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

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def home(self) -> Path:
        return Path.home()

    def free_gb(self, path: Path) -> float:
        return shutil.disk_usage(path).free / 1024**3

    def port_free(self, port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Without this, Windows lets a second program bind a port another already holds.
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

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
        return Process(process.pid, self._started(process.pid))

    def alive(self, process: Process) -> bool:
        return bool(process.started) and self._started(process.pid) == process.started

    def kill(self, process: Process) -> None:
        if os.name == "nt":
            self.run(["taskkill", "/PID", process.pid, "/T", "/F"])
            return
        try:
            os.killpg(process.pid, 15)
        except OSError:
            pass

    def leftovers(self, repo: Path) -> list[int]:
        # Anything still running from this folder's own controller or tool servers, found by the folder's path on its command line, because a session can outlive the process that started it.
        marks = (str(repo / ".foundry"), f"--directory {repo} run python -m foundry.tools")
        return [pid for pid, line in _processes(self) if pid != os.getpid() and any(mark in line for mark in marks)]

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

    def _started(self, pid: int) -> str:
        if os.name == "nt":
            shown = self.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CreationDate.ToString("o")'], timeout=30)
        else:
            shown = self.run(["ps", "-o", "lstart=", "-p", pid], timeout=10)
        return shown.output.strip() if shown.code == 0 else ""


def _powershell() -> str:
    return shutil.which("powershell") or shutil.which("pwsh") or "powershell"


def _processes(machine: Machine) -> list[tuple[int, str]]:
    if os.name == "nt":
        shown = machine.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"], timeout=60)
    else:
        shown = machine.run(["ps", "-eo", "pid=,args="], timeout=30)
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
    return fill_env(example, {**values, "FEATURE_FLAGS_ENABLED": "agent_management", **{setting: str(ports[name]) for name, setting in PORT_SETTINGS.items()}})


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
        missing.append("Docker is installed but not running. Start Docker Desktop, or the Docker service, and wait until it says it is running.")
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
            try:
                written.parent.mkdir(parents=True, exist_ok=True)
                with written.open("a", encoding="utf-8") as file:
                    file.write(traceback.format_exc())
            except OSError:
                pass
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
        self.state = self._read_state()
        self._hide_secrets()

    # What it remembers

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self._write(self.state_file, json.dumps(self.state, indent=2) + "\n")

    def _write(self, path: Path, text: str) -> None:
        # Whole or not at all, so a stop halfway never leaves half a settings file. On macOS and Linux, only this user can read it.
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)

    def _hide_secrets(self) -> None:
        for name, value in {**self._env_values(self.switch_env_file), **self._env_values(self.env_file)}.items():
            if value and (name in SWITCH_SECRETS or name in FOUNDRY_SECRETS):
                self.ui.secret(value)

    @staticmethod
    def _env_values(path: Path) -> dict[str, str]:
        try:
            return parse_env(path.read_text(encoding="utf-8"))
        except OSError:
            return {}

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
        held: set[int] = set()
        if "ports" not in self.state:
            return held
        if self._services_up():
            held |= {self.ports[name] for name in PORT_SETTINGS}
        if self._alive("dashboard"):
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
        if not self.images_file.exists():
            return []
        shown = self.machine.run(self.compose("ps", "-a", "--format", "json"), timeout=60)
        if shown.code != 0:
            return []
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
        if not (self.switch / "console").is_dir():
            return False
        return self.machine.run([self.machine.which("git") or "git", "-C", self.switch, "rev-parse", "HEAD"], timeout=30).output.strip() == PINNED_COMMIT

    def get_switch(self) -> None:
        # Only this one commit, which is far smaller than the whole history. With its line endings kept, because the containers read these files.
        if self.switch.exists():
            self.machine.remove_tree(self.switch)
        self.switch.mkdir(parents=True)
        git = [self.machine.which("git") or "git", "-C", self.switch]
        for arguments in (("init", "-q"), ("config", "core.autocrlf", "false"), ("config", "core.longpaths", "true"), ("remote", "add", "origin", SWITCH_GIT), ("fetch", "--depth", "1", "origin", PINNED_COMMIT), ("checkout", "-q", "FETCH_HEAD")):
            if self.machine.run([*git, *arguments], log=self._log("switch-clone"), timeout=600).code != 0:
                raise self._failed(FAIL_CLONE, "switch-clone")

    def write_switch_env(self) -> None:
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

    def _alive(self, name: str) -> bool:
        process = self._record(name)
        return process is not None and self.machine.alive(process)

    def _start(self, name: str, command: list, cwd: Path, env: Mapping[str, str]) -> None:
        process = self.machine.spawn(command, cwd, env, self._log(name))
        self.state.setdefault("processes", {})[name] = dataclasses.asdict(process)
        self._save_state()

    def _stop_one(self, name: str) -> bool:
        process = self._record(name)
        stopped = process is not None and self.machine.alive(process)
        if stopped:
            self.machine.kill(process)
        self.state.get("processes", {}).pop(name, None)
        self._save_state()
        return stopped

    def _rooms_mark(self) -> str:
        values = self._env_values(self.env_file)
        return values.get("FOUNDRY_ROOMS", "") + "|" + values.get("FOUNDRY_PACKS", "")

    def _python(self) -> Path:
        return self.repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _follows_rooms(self, name: str) -> bool:
        # Both read the rooms when they start, so one running from before a new demo's rooms were made is out of date.
        return self._alive(name) and self.state.get("following", {}).get(name) == self._rooms_mark()

    def _start_following(self, name: str, module: str) -> None:
        self._stop_one(name)
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
        if not self.state.get("ports"):
            self.ui.say("Foundry has not been set up here yet. Run this with no options to set it up, or with --try to look around with made-up data.")
            return 0
        rows = {row.get("Service"): row for row in self._service_rows()}
        self.ui.say(f"Foundry in {self.repo}, Docker project {self.project()}")
        for service in LONG_RUNNING:
            shown = rows.get(service, {}).get("State") or "not created"
            self.ui.say(f"  {service:<12}{shown}")
        for name in ("controller", "desk", "dashboard"):
            self.ui.say(f"  {name:<12}{'running' if self._alive(name) else 'stopped'}")
        self.ui.say(f"  Demo rooms  {', '.join(self.state.get('rooms_made', [])) or 'none yet'}")
        self.ui.say()
        self.ui.say(f"  Dashboard   {self.dashboard_url()}")
        self.ui.say(f"  Mattermost  {self.mattermost_url()}")
        self.ui.say(f"  Switch      {self.gateway_url()}")
        self.ui.say("  Logins are in the .env file in this folder, and in .foundry/switch/.env.")
        return 0

    def stop(self, closing: str = "Stopped what setup started. Run this again to start it all back up.") -> int:
        if not self.state:
            self.ui.say("Nothing to stop. Setup has not started anything here.")
            return 0
        for name in ("dashboard", "desk", "controller"):
            self.ui.say(f"  {name}: {'stopped' if self._stop_one(name) else 'was not running'}")
        for pid in self.machine.leftovers(self.repo):
            self.machine.kill(Process(pid, ""))
        if self.state.get("stack_started") and self.images_file.exists():
            self.machine.run(self.compose("stop"), log=self._log("switch"), timeout=300)
            self.ui.say("  Switch's containers: stopped")
        if closing:
            self.ui.say(closing)
        return 0

    def _removals(self) -> list[str]:
        created = self.state.get("created", {})
        lines = [f"the Docker containers and data of project {self.project()}"]
        if self.state.get("pulled_images"):
            lines.append(f"{len(self.state['pulled_images'])} Docker images only this setup downloaded")
        lines.append(".foundry, with Switch's copy, the controller and the logs")
        if created.get("env"):
            lines.append(".env and Foundry's foundry-*.db files and foundry-inputs")
        if created.get("venv"):
            lines.append(".venv")
        if created.get("agents_folder") and "ports" in self.state:
            lines.append(str(self.agents_folder()))
        return lines

    def reset(self) -> int:
        if not self.state and not self.home.exists():
            self.ui.say("Nothing to remove. Setup has not made anything here.")
            return 0
        self.ui.say("This removes everything setup made, and nothing else:")
        for line in self._removals():
            self.ui.say(f"  - {line}")
        answer = "yes" if self.yes else self.ui.ask("Type yes to remove all of it:")
        if answer is None:
            self.ui.say("Nobody is here to answer, so nothing was removed. To say yes in advance, add --yes.")
            return 1
        if answer.strip().lower() != "yes":
            self.ui.say("Nothing was removed.")
            return 0
        self.stop(closing="")
        created = self.state.get("created", {})
        if self.state.get("stack_started") and self.images_file.exists():
            self.machine.run(self.compose("down", "-v", "--remove-orphans"), log=None, timeout=300)
        docker = self.machine.which("docker") or "docker"
        for image in self.state.get("pulled_images", []):
            # Never with force, so an image another container has come to use stays.
            self.machine.run([docker, "image", "rm", image], timeout=120)
        if created.get("agents_folder") and "ports" in self.state:
            self.machine.remove_tree(self.agents_folder())
        if created.get("env"):
            self.env_file.unlink(missing_ok=True)
            for made in self.repo.glob("foundry-*.db*"):
                made.unlink(missing_ok=True)
            self.machine.remove_tree(self.repo / "foundry-inputs")
        if created.get("venv"):
            self.machine.remove_tree(self.repo / ".venv")
        self.machine.remove_tree(self.home)
        self.state = {}
        self.ui.say("Removed. Run this again to set it all up from the start.")
        return 0

    def try_mode(self) -> int:
        return try_mode(self.repo, self.machine, self.ui, self)


# Whatever a real setup or a person's own shell has named, none of it is passed on to try mode.
NOT_FOR_TRY_MODE = ("FOUNDRY_", "SWITCH_", "MATTERMOST_", "ANTHROPIC_", "SARVAM_", "SLACK_", "TELEGRAM_", "WHATSAPP_", "GOOGLE_", "OPENAI_", "UV_ENV_FILE", "CLAUDE_")
NO_UV = "Try mode needs uv, and uv is not on your PATH. Get it from https://docs.astral.sh/uv/getting-started/installation/."


def clean_env(env: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in env.items() if not name.upper().startswith(NOT_FOR_TRY_MODE)}


def try_mode(repo: Path, machine: Machine, ui: Ui, build: "Setup") -> int:
    # It needs only uv. Its data and settings live in its own folder, it never reads a .env, and tools/try_foundry.py listens on this machine and connects to nothing.
    uv = machine.which("uv")
    if not uv:
        ui.say(NO_UV)
        return 1
    build.state.setdefault("created", {}).setdefault("venv", not (repo / ".venv").exists())
    build._save_state()
    ui.say("Try mode: the dashboard with made-up data. No agents, no Docker, and it never reads your .env.")
    if not (repo / ".venv").exists():
        ui.say("The first time, uv downloads Python and Foundry's packages, about 2 minutes. After that nothing leaves this machine.")
    command = [uv, "run", "--frozen", "--no-dev", "python", "tools/try_foundry.py"]
    try:
        return subprocess.run(command, cwd=repo, env={**clean_env(os.environ), "PYTHONUTF8": "1"}, check=False).returncode
    except KeyboardInterrupt:
        ui.say("Try mode stopped.")
        return 0


def parser() -> argparse.ArgumentParser:
    ask = argparse.ArgumentParser(prog="setup", description="Sets Foundry up from a fresh clone, and can be run again at any point.")
    ask.add_argument("--try", dest="try_mode", action="store_true", help="the dashboard with made-up data and no agents. It needs only uv")
    ask.add_argument("--stop", action="store_true", help="stop what setup started")
    ask.add_argument("--status", action="store_true", help="show what is up")
    ask.add_argument("--reset", action="store_true", help="remove only what setup made, after asking")
    ask.add_argument("--demo", choices=list(DEMOS), help="which demo to make rooms for. It is asked if not given")
    ask.add_argument("--yes", action="store_true", help="take the default for anything it would ask")
    return ask


def main(arguments: list[str] | None = None) -> int:
    chosen = parser().parse_args(arguments)
    ui = Ui(stdin=True)
    build = Setup(REPO, Machine(), ui, demo=chosen.demo, yes=chosen.yes)
    try:
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
    except OSError as error:
        ui.say(FAIL_FILE_IN_USE.format(path=error.filename or "A file here"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
