"""Plays a demo's team on Mattermost: real users in real channels, sending scripted words. Everything Foundry answers is real.

uv run --env-file .env python scripts/demo_people.py ensure it_firm
uv run --env-file .env python scripts/demo_people.py play it_firm [first step]
"""

import os
import re
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml
from foundry.voice import speak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from register_desk import save

SCENES = Path(__file__).resolve().parent / "scenes"
THIS_MACHINE = ("localhost", "127.0.0.1", "::1")
ON_THE_BUSINESS_CLOCK = re.compile(r"\{in:(\d+)\}")
LOG_TOKEN = re.compile(r"(Log token for this job: )[^\s.]+")
NUMBERED = re.compile(r"\s*\d+[.)]\s*")
ACTIONS = ("say", "voice", "file", "press")
POLL_SECONDS = 3
WAIT_SECONDS = 600
PRESS_SECONDS = 60
MOST_POSTS = 100
MOST_CHARS_SHOWN = 1500
# What speech is spoken in for a voice step. Sarvam's Bulbul reads Hinglish on its Hindi voice.
VOICE_LANGUAGE = "hi-IN"
NO_VOICE = "Skipped a voice note because SARVAM_API_KEY is not set, so it has not run. Nothing stands in for it."
TYPED_INSTEAD = "There is no SARVAM_API_KEY, so the voice note has not run. The same words are typed instead."


def load_scene(name: str) -> dict:
    path = Path(name) if name.endswith((".yaml", ".yml")) else SCENES / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def username(title: str) -> str:
    return "-".join(title.casefold().split())


def sender_id(title: str, bridge: str) -> str:
    return f"@switch-mattermost-{bridge}-{username(title)}:localhost"


def _clock(when: datetime) -> str:
    local = when.astimezone(timezone(timedelta(minutes=int(os.environ.get("FOUNDRY_UTC_OFFSET_MINUTES", "330")))))
    return f"{local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'}"


def fill_times(text: str, start: datetime) -> str:
    # A scene says "by {in:10}" and a person reads a time on the clock, because there is no fake clock.
    return ON_THE_BUSINESS_CLOCK.sub(lambda match: _clock(start + timedelta(minutes=int(match.group(1)))), text)


def masked(text: str) -> str:
    return LOG_TOKEN.sub(r"\1<hidden>", text)


def _local(name: str, default: str) -> str:
    # These scripts sign in as the admin and reset the password of anyone with a scripted person's name, so they only ever talk to a stack on this machine.
    url = os.environ.get(name, default)
    host = urlsplit(url).hostname or ""
    if host not in THIS_MACHINE and not host.endswith(".localhost"):
        raise SystemExit(f"{name} points at {host or url}, which is not this machine. The demo scripts only run against a local stack, so nothing was done.")
    return url


def switch_url() -> str:
    return _local("SWITCH_URL", "http://127.0.0.1:8000")


def _chat_url() -> str:
    return f"{_local('MATTERMOST_URL', 'http://127.0.0.1:8065')}/api/v4"


def local_only() -> None:
    switch_url()
    _chat_url()


def _signed_in(login: str, password: str) -> httpx.Client:
    answer = httpx.post(f"{_chat_url()}/users/login", json={"login_id": login, "password": password}, timeout=30)
    answer.raise_for_status()
    return httpx.Client(base_url=_chat_url(), headers={"Authorization": f"Bearer {answer.headers['Token']}"}, timeout=60)


def _admin() -> httpx.Client:
    return _signed_in(os.environ["MATTERMOST_ADMIN_USER"], os.environ["MATTERMOST_ADMIN_PASSWORD"])


def _team(admin: httpx.Client) -> dict:
    return admin.get(f"/teams/name/{os.environ['MATTERMOST_TEAM_NAME']}").raise_for_status().json()


def _channel_id(admin: httpx.Client, team: dict, room: str) -> str:
    answer = admin.get(f"/teams/{team['id']}/channels/name/{room}")
    if answer.status_code == 404:
        raise SystemExit(f"There is no Mattermost channel called {room}. Run scripts/demo_seed.py first.")
    return answer.raise_for_status().json()["id"]


def find_bridge() -> str | None:
    # Whatever the stack's Mattermost bridge is called, every sender id on it holds this.
    with httpx.Client(base_url=f"{switch_url()}/gateway", timeout=60) as gateway:
        gateway.post("/auth/login", json={"email": os.environ["SWITCH_EMAIL"], "password": os.environ["SWITCH_PASSWORD"]}).raise_for_status()
        bridges = gateway.get("/collaborations").raise_for_status().json()
    return next((bridge["bridge_id"] for bridge in bridges if bridge["bridge_type"] == "mattermost"), None)


def bridge_id() -> str:
    found = find_bridge()
    if found is None:
        raise SystemExit("This Switch stack has no Mattermost bridge, so nobody can be scripted on it.")
    return found


def _password() -> str:
    # Made up here for this stack's scripted people, and kept only in .env.
    if not os.environ.get("FOUNDRY_DEMO_PASSWORD"):
        save({"FOUNDRY_DEMO_PASSWORD": secrets.token_urlsafe(24)})
    return os.environ["FOUNDRY_DEMO_PASSWORD"]


def _ensure_user(admin: httpx.Client, title: str, password: str) -> str:
    name = username(title)
    found = admin.get(f"/users/username/{name}")
    if found.status_code == 200:
        user_id = found.json()["id"]
        # They may have been made with an earlier .env, and only the password in this one can sign them in.
        admin.put(f"/users/{user_id}/password", json={"new_password": password}).raise_for_status()
        return user_id
    made = admin.post("/users", json={"username": name, "email": f"{name}@foundry-demo.test", "password": password, "nickname": title})
    return made.raise_for_status().json()["id"]


def ensure(scene: dict) -> None:
    save({"FOUNDRY_MATTERMOST_BRIDGE": bridge_id()})
    password = _password()
    admin = _admin()
    team = _team(admin)
    channels = {room: _channel_id(admin, team, room) for rooms in scene["people"].values() for room in rooms}
    for title, rooms in scene["people"].items():
        user_id = _ensure_user(admin, title, password)
        admin.post(f"/teams/{team['id']}/members", json={"team_id": team["id"], "user_id": user_id}).raise_for_status()
        for room in rooms:
            admin.post(f"/channels/{channels[room]}/members", json={"user_id": user_id}).raise_for_status()
        print(f"{title} is {username(title)}, in {', '.join(rooms)}")


def _buttons(post: dict) -> list[dict]:
    return [action for attachment in (post.get("props") or {}).get("attachments") or [] for action in attachment.get("actions") or []]


def _label(action: dict) -> str:
    # Switch may number a card's buttons, as the text form of the card does.
    return NUMBERED.sub("", action.get("name", ""), count=1).strip()


def _printable(line: str) -> str:
    # A redirected stdout on Windows is cp1252, and one tick in a post must not stop a scene.
    encoding = sys.stdout.encoding or "utf-8"
    return line.encode(encoding, "backslashreplace").decode(encoding)


class Stage:
    """The channels of one scene, and everyone signed in. It prints every post once, so a run leaves a timeline behind it."""

    def __init__(self, scene: dict, start: datetime) -> None:
        self.scene, self.start = scene, start
        self.admin = _admin()
        self.team = _team(self.admin)
        self.since = int(start.timestamp() * 1000)
        self.people: dict[str, httpx.Client] = {}
        self.channels: dict[str, str] = {}
        self.shown: dict[str, str] = {}
        self.taken: set[str] = set()
        # The rooms a scene follows, and any a step names that it did not list.
        for room in [*scene.get("watch", []), *(room for rooms in scene["people"].values() for room in rooms)]:
            self._channel(room)

    def _channel(self, room: str) -> str:
        if room not in self.channels:
            self.channels[room] = _channel_id(self.admin, self.team, room)
        return self.channels[room]

    def person(self, title: str) -> httpx.Client:
        if title not in self.people:
            if not os.environ.get("FOUNDRY_DEMO_PASSWORD"):
                raise SystemExit("FOUNDRY_DEMO_PASSWORD is not set. Run this script's ensure first.")
            self.people[title] = _signed_in(username(title), os.environ["FOUNDRY_DEMO_PASSWORD"])
        return self.people[title]

    def say(self, line: str) -> None:
        elapsed = int((datetime.now(UTC) - self.start).total_seconds())
        print(_printable(f"{datetime.now():%H:%M:%S} +{elapsed // 60:02d}:{elapsed % 60:02d} {line}"), flush=True)

    def posts(self, room: str) -> list[dict]:
        found = self.admin.get(f"/channels/{self._channel(room)}/posts", params={"per_page": MOST_POSTS}).raise_for_status().json()
        return [found["posts"][post_id] for post_id in reversed(found["order"]) if not found["posts"][post_id].get("delete_at")]

    def show_new_posts(self) -> None:
        for room in self.channels:
            for post in self.posts(room):
                if post["create_at"] < self.since:
                    continue
                buttons = [action.get("name", "") for action in _buttons(post)]
                files = [info.get("name", "") for info in (post.get("metadata") or {}).get("files") or []]
                seen = f"{post['message']}|{buttons}|{files}"
                if self.shown.get(post["id"]) != seen:
                    edited = " (edited)" if post["id"] in self.shown else ""
                    self.shown[post["id"]] = seen
                    self.say(f"{room}{edited}: {masked(post['message'])[:MOST_CHARS_SHOWN]!r}{f' buttons={buttons}' if buttons else ''}{f' files={files}' if files else ''}")

    def wait_for(self, number: int, step: dict) -> None:
        wanted = step["wait_for"]
        room, text, button = wanted.get("room", step["room"]), wanted.get("text"), wanted.get("button")
        deadline = time.monotonic() + wanted.get("timeout", WAIT_SECONDS)
        while True:
            self.show_new_posts()
            for post in self.posts(room):
                if post["id"] not in self.taken and post["create_at"] >= self.since and self._matches(post, text, button):
                    self.taken.add(post["id"])
                    self.say(f"Step {number} saw what it waited for in {room}.")
                    return
            if time.monotonic() >= deadline:
                raise SystemExit(f"Step {number} stopped the scene: nothing in {room} showed {button or text!r} in time.")
            time.sleep(POLL_SECONDS)

    def _matches(self, post: dict, text: str | None, button: str | None) -> bool:
        if button and all(_label(action) != button for action in _buttons(post)):
            return False
        return not text or text.casefold() in post["message"].casefold()

    def press(self, number: int, step: dict) -> None:
        deadline = time.monotonic() + step.get("timeout", PRESS_SECONDS)
        while True:
            for post in reversed(self.posts(step["room"])):
                action = next((action for action in _buttons(post) if _label(action) == step["press"]), None)
                if action is not None:
                    self.person(step["as"]).post(f"/posts/{post['id']}/actions/{action['id']}", json={}).raise_for_status()
                    self.say(f"Step {number}: {step['as']} pressed {step['press']} in {step['room']}.")
                    return
            if time.monotonic() >= deadline:
                raise SystemExit(f"Step {number} stopped the scene: no card in {step['room']} has a button called {step['press']!r}.")
            time.sleep(POLL_SECONDS)

    def post(self, step: dict, message: str, file_ids: list[str] | None = None) -> None:
        body = {"channel_id": self._channel(step["room"]), "message": message}
        self.person(step["as"]).post("/posts", json={**body, "file_ids": file_ids} if file_ids else body).raise_for_status()

    def upload(self, step: dict, name: str, data: bytes) -> list[str]:
        answer = self.person(step["as"]).post("/files", params={"channel_id": self._channel(step["room"])}, files={"files": (name, data)})
        return [info["id"] for info in answer.raise_for_status().json()["file_infos"]]


def _act(stage: Stage, number: int, step: dict) -> bool:
    # False when the step could not be done honestly, so nothing is waited for.
    who = f"Step {number}: {step['as']} in {step['room']}"
    if "voice" in step and not os.environ.get("SARVAM_API_KEY"):
        if "say" not in step:
            stage.say(f"{who}. {NO_VOICE}")
            return False
        stage.say(f"{who}. {TYPED_INSTEAD}")
    if "voice" in step and os.environ.get("SARVAM_API_KEY"):
        words = fill_times(step["voice"], stage.start)
        stage.post(step, "", stage.upload(step, "voice.wav", speak(words, VOICE_LANGUAGE)))
        stage.say(f"{who} sent a voice note saying: {words}")
    elif "file" in step:
        path = Path(step["file"])
        words = fill_times(step.get("say", ""), stage.start)
        stage.post(step, words, stage.upload(step, path.name, path.read_bytes()))
        stage.say(f"{who} sent {path.name}")
    elif "say" in step:
        words = fill_times(step["say"], stage.start)
        stage.post(step, words)
        stage.say(f"{who} says: {words}")
    elif "press" in step:
        stage.press(number, step)
    return True


def play(scene: dict, start: datetime | None = None, first_step: int = 1) -> None:
    stage = Stage(scene, start or datetime.now(UTC))
    for number, step in enumerate(scene["steps"], start=1):
        if number < first_step:
            continue
        if not any(action in step for action in ACTIONS) and "wait_for" not in step:
            raise SystemExit(f"Step {number} has nothing to do and nothing to wait for.")
        if _act(stage, number, step) and "wait_for" in step:
            stage.wait_for(number, step)
    stage.show_new_posts()
    stage.say("The scene is over.")


def main(arguments: list[str]) -> None:
    local_only()
    what, name, *rest = arguments
    scene = load_scene(name)
    if what == "ensure":
        ensure(scene)
    elif what == "play":
        play(scene, first_step=int(rest[0]) if rest else 1)
    else:
        raise SystemExit("Say ensure or play, then the scene's name.")


if __name__ == "__main__":
    main(sys.argv[1:])
