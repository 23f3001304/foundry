"""Who a tag in chat means, on any chat app Switch connects, and the private room Foundry uses to ask that person something.

A chat app writes a tag its own way: Slack as a user id, Mattermost as a username. Switch's directory of each connection knows both, with the person's name,
so a tag reads as the person it is, and the person's Switch id can be made the way Switch makes it for everyone who writes on that app.
"""

import logging
import os
from difflib import SequenceMatcher
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TAG = re.compile(r"@([A-Za-z0-9._\-]+)")
# The directory only answers a search, so it is read with a few searches that between them find nearly every name.
SEARCHES = ("a", "e", "i", "o", "u", "y")
KEEP_FOR = 600


@dataclass(frozen=True)
class Person:
    name: str
    username: str
    external_id: str
    sender: str


WORD = re.compile(r"[^\W\d_]{3,}")
# How alike a word has to be to a name to count as it, so "girsih" is Girish and "gary" is not.
CLOSE_ENOUGH = 0.8
# Words in a name that say nothing about who it is.
COMMON = {"the", "and", "mr", "mrs", "ms", "dr", "team", "from", "for", "with", "our"}


def mentioned(text: str, everyone: list[Person]) -> list[Person]:
    """The people a message names, by any part of their name, spelt right or nearly so."""
    words = {word.casefold() for word in WORD.findall(text)}
    found = []
    for person in everyone:
        parts = {part.casefold() for part in WORD.findall(person.name)} - COMMON
        if any(word == part or (len(part) >= 4 and SequenceMatcher(None, word, part).ratio() >= CLOSE_ENOUGH) for word in words for part in parts):
            found.append(person)
    return found


class People:
    def __init__(self, url: str | None = None, email: str | None = None, password: str | None = None) -> None:
        self.url = url or os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
        self.email, self.password = email or os.environ.get("SWITCH_EMAIL", ""), password or os.environ.get("SWITCH_PASSWORD", "")
        self._rooms: dict[str, dict] = {}
        self._people: dict[str, tuple[float, list[Person]]] = {}

    @contextmanager
    def _gateway(self) -> Iterator[httpx.Client]:
        with httpx.Client(base_url=f"{self.url}/gateway", timeout=30, trust_env=False) as gateway:
            gateway.post("/auth/login", json={"email": self.email, "password": self.password}).raise_for_status()
            yield gateway

    def room(self, room_id: str) -> dict:
        if room_id not in self._rooms:
            with self._gateway() as gateway:
                listed = gateway.get("/rooms", params={"include_archived": "true"}).raise_for_status().json()
            self._rooms = {room["id"]: room for room in (listed.get("items", []) if isinstance(listed, dict) else listed)}
        return self._rooms.get(room_id, {})

    def on(self, room_id: str) -> list[Person]:
        room = self.room(room_id)
        bridge, kind = room.get("bridge_id"), room.get("bridge_type")
        if not bridge or not kind:
            return []
        kept = self._people.get(bridge)
        if kept and time.monotonic() - kept[0] < KEEP_FOR:
            return kept[1]
        found: dict[str, Person] = {}
        with self._gateway() as gateway:
            for search in SEARCHES:
                answer = gateway.get(f"/collaborations/{bridge}/directory", params={"query": search})
                for user in answer.json().get("users", []) if answer.is_success else []:
                    if user.get("username"):
                        found[user["external_user_id"]] = Person(user.get("display_name") or user["username"], user["username"], user["external_user_id"],
                                                                 f"@switch-{kind}-{bridge}-{user['username']}:localhost")
        self._people[bridge] = (time.monotonic(), list(found.values()))
        return self._people[bridge][1]

    def tagged(self, room_id: str, text: str) -> list[Person]:
        if "@" not in text:
            return []
        everyone = self.on(room_id)
        by_tag = {key.casefold(): person for person in everyone for key in (person.external_id, person.username)}
        return list({person.sender: person for tag in TAG.findall(text) if (person := by_tag.get(tag.casefold()))}.values())

    def named(self, room_id: str, text: str) -> str:
        """The text with each tag of a person written as their name, so a model reading it knows who was tagged."""
        for person in self.tagged(room_id, text):
            text = re.sub(rf"@({re.escape(person.external_id)}|{re.escape(person.username)})\b", f"@{person.name}", text)
        return text

    def bridge_of(self, room_id: str) -> str:
        return self.room(room_id).get("bridge_id") or ""

    def username_of(self, room_id: str, sender: str) -> str:
        # The username is the end of a Switch id made for someone on a chat app: @switch-<app>-<connection>-<username>:<server>.
        bridge = self.bridge_of(room_id)
        marker = f"-{bridge}-"
        return sender.split(marker, 1)[1].rsplit(":", 1)[0] if bridge and marker in sender else ""
