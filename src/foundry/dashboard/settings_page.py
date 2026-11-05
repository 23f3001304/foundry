"""The Settings page: what's set up, the models and keys in .env, and how to connect a chat app."""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROVIDERS = ("claude", "codex", "opencode")
PLAIN = re.compile(r"[^\s\"'#=]*")
NOT_PLAIN = "{label} can't hold spaces, quotes, # or =, so nothing was saved."
NOT_A_CHOICE = "{label} isn't one of the choices, so nothing was saved."
GUIDES_DIR = Path(__file__).parent / "static" / "guides"
REPO = Path(__file__).resolve().parents[3]
BRAND_FOLDERS = REPO / "brands"
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
BAD_PROJECT_NAME = "A project's name is small letters, numbers and dashes, up to 40, so nothing was made."
BAD_BRAND_FOLDER = "That brand folder isn't one of the choices, so nothing was made."
BAD_KIND = "That kind of project isn't one of the choices, so nothing was made."
ALREADY_MAKING = "Another project is being made. Wait for it to finish, then try again."
TOOK_TOO_LONG = "Making the project took more than five minutes, so Foundry stopped waiting. Some rooms may exist. Run the same thing again to finish it."
DID_NOT_WORK = "The project wasn't made. Run tools/create_rooms.py from a terminal to see why."
MAKING_TIMEOUT = 300
PROJECT_KINDS = (("agency", "A client, with agents of its own"), ("internal", "Your own company or department"))
_making = threading.Lock()


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    hint: str = ""
    secret: bool = False
    choices: tuple[str, ...] = ()


KEYS = (
    Field("ANTHROPIC_API_KEY", "Claude API key", "For sorting messages and cleaning notes. Empty: the signed-in claude CLI does it.", secret=True),
    Field("GOOGLE_CLOUD_PROJECT", "Google Cloud project", "For drawing pictures on Vertex AI, using your gcloud sign-in."),
    Field("SARVAM_API_KEY", "Sarvam API key", "For voice notes.", secret=True),
)
MODELS = (
    Field("FOUNDRY_CLASSIFIER_MODEL", "Sorting model", "Reads each message."),
    Field("FOUNDRY_CLEANUP_MODEL", "Note clean-up model"),
    Field("FOUNDRY_IMAGES", "Draw pictures", "Needs the Google Cloud project.", choices=("off", "on")),
    Field("FOUNDRY_IMAGE_MODEL", "Picture model", "Empty: the default on Vertex AI."),
)
# Switch fixes an agent's provider when it is made, so these only reach a project made after they change.
AGENTS = (
    Field("FOUNDRY_BRIEF_PROVIDER", "Brief agent", choices=("", *PROVIDERS)),
    Field("FOUNDRY_DECK_PROVIDER", "Deck agent", choices=("", *PROVIDERS)),
    Field("FOUNDRY_VISUAL_PROVIDER", "Visual agent", choices=("", *PROVIDERS)),
    Field("FOUNDRY_REVIEWER_PROVIDER", "Reviewer agent", choices=("", *PROVIDERS)),
    Field("FOUNDRY_REVIEWER_MODEL", "Reviewer model", "A model that can see images."),
)
ALL_FIELDS = (*KEYS, *MODELS, *AGENTS)

GUIDES = (
    {"key": "telegram", "name": "Telegram", "steps": (
        "In Telegram, open @BotFather and send /newbot.",
        "Choose a name and a username ending in bot, then copy the token it gives you.",
        "Here, open Connections, choose Add a connection, pick Telegram and paste the token.",
        "Add the bot to your group, then send it a message so the group shows up in Switch.",
    )},
    {"key": "slack", "name": "Slack", "steps": (
        "Go to api.slack.com/apps and create an app in your workspace.",
        "Turn on Socket Mode, and copy the app-level token it makes.",
        "Add the bot scopes Switch asks for, install the app, and copy the bot token.",
        "Here, open Connections, choose Add a connection, pick Slack and paste both tokens.",
        "Invite the bot to your channel. The first time you press a card, Slack may ask you to link your account.",
    )},
    {"key": "mattermost", "name": "Mattermost", "steps": (
        "Setup already runs a Mattermost and connects it, so with that one there is nothing to do.",
        "For your own server: a System Admin turns on bot accounts, creates a bot and copies its token.",
        "Here, open Connections, choose Add a connection, pick Mattermost, and enter the server's address and the token.",
    )},
)


def guides() -> list[dict]:
    return [{**guide, "video": (GUIDES_DIR / f"{guide['key']}.mp4").exists()} for guide in GUIDES]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sign, value = line.partition("=")
            if sign and not name.lstrip().startswith("#"):
                values[name.strip()] = value.strip().strip("\"'")
    return values


def problem_with(form: dict) -> str:
    for field in ALL_FIELDS:
        value = str(form.get(field.name) or "").strip()
        if field.choices and value not in field.choices:
            return NOT_A_CHOICE.format(label=field.label)
        if not PLAIN.fullmatch(value):
            return NOT_PLAIN.format(label=field.label)
    return ""


def changes_from(form: dict, values: dict[str, str]) -> dict[str, str]:
    # An empty secret box means no change, because a saved key is never put back in the page. Its own tick removes it.
    changes = {}
    for field in ALL_FIELDS:
        value = str(form.get(field.name) or "").strip()
        if field.secret:
            if form.get(f"clear.{field.name}"):
                value = ""
            elif not value:
                continue
        if value != values.get(field.name, ""):
            changes[field.name] = value
    return changes


def save_env(path: Path, changes: dict[str, str]) -> None:
    # Every other line stays as it was. The new file takes the old one's place in one step, so a crash leaves one or the other.
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(changes)
    for index, line in enumerate(lines):
        name = line.partition("=")[0].strip()
        if "=" in line and not name.startswith("#") and name in left:
            lines[index] = f"{name}={left.pop(name)}"
    lines.extend(f"{name}={value}" for name, value in left.items())
    made, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env-")
    try:
        with os.fdopen(made, "w", encoding="utf-8", newline="\n") as file:
            file.write("\n".join(lines) + "\n")
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    # The names only. A value is never logged.
    logger.info("Settings changed: %s.", ", ".join(sorted(changes)))


def brand_folders() -> list[str]:
    return sorted(folder.parent.name for folder in BRAND_FOLDERS.glob("*/kit.md"))


def make_project(env_path: Path, mode: str, name: str, brand: str) -> str:
    """Makes a project's rooms and agents with the same tool the command line uses. Says what went wrong, or nothing if it worked."""
    if not PROJECT_NAME.fullmatch(name):
        return BAD_PROJECT_NAME
    if brand not in brand_folders():
        return BAD_BRAND_FOLDER
    if mode not in dict(PROJECT_KINDS):
        return BAD_KIND
    if not _making.acquire(blocking=False):
        return ALREADY_MAKING
    try:
        # What's in .env now, since a key saved on this page isn't in this process until a restart.
        answer = subprocess.run(
            [sys.executable, str(REPO / "tools" / "create_rooms.py"), mode, name, brand],
            cwd=env_path.parent, env={**os.environ, **read_env(env_path)}, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=MAKING_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return TOOK_TOO_LONG
    finally:
        _making.release()
    if answer.returncode == 0:
        logger.info("Project made: %s.", name)
        return ""
    # The tool's own sentence says what to do. A crash's trace could hold anything, so that stays off the page.
    lines = answer.stderr.strip().splitlines()
    return DID_NOT_WORK if not lines or "Traceback" in answer.stderr else lines[-1][:500]


def view(env_path: Path | None, settings) -> dict:
    values = read_env(env_path) if env_path else {}
    projects: dict[str, list[str]] = {}
    for room in settings.packs:
        projects.setdefault(settings.bucket_for(room), []).append(room)
    return {
        "keys": KEYS, "models": MODELS, "agents": AGENTS, "values": values, "guides": guides(),
        "editable": env_path is not None, "projects": projects, "brand_folders": brand_folders(), "project_kinds": PROJECT_KINDS,
        "clis": [(name, shutil.which(name) is not None) for name in PROVIDERS],
    }
