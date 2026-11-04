"""Foundry's one door to Switch. Each method wraps a call confirmed in docs/spike-results.md."""

import asyncio
import json
import logging
import mimetypes
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CARD_LIFETIME = timedelta(hours=23)
MAX_TITLE_CHARS = 500
QUESTION_CARD_TITLE = "Your note"
QUESTION_TITLE = "One question"
MAX_DETAIL_CHARS = 4000
CARD_OPTIONS = [
    {"id": "approve", "label": "Approve", "decision": "accept"},
    {"id": "revise", "label": "Ask for changes", "decision": "decline"},
]

DESK_NAME = "foundry-desk"


@dataclass
class Outcome:
    session_id: str
    request_id: str
    state: str
    answer: str | None
    answered_by: str | None
    answers: list[dict] | None = None

    def chosen_from(self, choices: list[str]) -> str | None:
        picked = ((self.answers or [{}])[0].get("selected_option_ids") or [None])[0]
        return dict(zip(_choice_ids(choices), choices)).get(picked)


def _choice_ids(choices: list[str]) -> list[str]:
    return [f"choice-{position}" for position, _ in enumerate(choices, start=1)]


class SwitchClient:
    def __init__(self, base_url: str, agent_id: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url
        self.agent_id = agent_id
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.transport = transport
        self.connection_id = str(uuid.uuid4())
        # Stable across restarts, so a card opened before a restart can still be closed.
        self.session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"foundry/{agent_id}"))
        self.cursor = 0
        self.beat_seconds = 2
        self.reconnect_seconds = 2
        self.http = httpx.Client(base_url=base_url, headers=self.headers, timeout=60, transport=transport)

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def post_message(self, room_id: str, content: str, thread_id: str | None = None) -> None:
        if thread_id is None:
            self._call("POST", f"/agents/{self.agent_id}/message", json={"room_id": room_id, "content": content})
            return
        # The plain message route has no thread field; the session operations do.
        session = self._session_headers()
        self._call("POST", f"/agents/{self.agent_id}/ops/connect_to_room", headers=session,
                   json={"room_id": room_id, "include_general_instructions": False})
        self._call("POST", f"/agents/{self.agent_id}/ops/post_message", headers=session,
                   json={"body": content, "thread_id": thread_id})

    def read_context(self, room_id: str, limit: int = 30) -> str:
        timeline = self._call("POST", f"/agents/{self.agent_id}/ops/read_context", headers=self._session_headers(),
                              json={"room_id": room_id, "limit": limit}).json()["result"]
        entries = [entry for thread in timeline["threads"] for entry in [thread["root"], *thread["replies"]]]
        return "\n".join(f"{entry['sender_name']}: {entry['body']}" for entry in entries if entry["kind"] == "message" and entry["sender_name"] != DESK_NAME)

    def _session_headers(self) -> dict[str, str]:
        return {"X-Switch-Connection-Id": self.connection_id, "X-Switch-Session-Id": self.session_id}

    def post_file(self, room_id: str, path: Path | str, caption: str) -> None:
        path = Path(path)
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._call("POST", f"/agents/{self.agent_id}/rooms/{room_id}/media",
                   files={"file": (path.name, path.read_bytes(), kind)}, data={"caption": caption})

    def download(self, room_id: str, attachment: dict) -> bytes:
        return self._call("GET", f"/agents/{self.agent_id}/rooms/{room_id}/media", params={"mxc": attachment["mxc"]}).content

    def open_card(self, room_id: str, request_id: str, title: str, detail: str) -> None:
        self._call("POST", f"/agent-sessions/{self.session_id}/approvals", json={
            "request_id": request_id,
            "turn_id": request_id,
            "kind": "approval",
            "title": title[:MAX_TITLE_CHARS],
            "detail": detail[:MAX_DETAIL_CHARS],
            "options": CARD_OPTIONS,
            "questions": [],
            "room_id": room_id,
            "thread_id": None,
            "expires_at": (datetime.now(UTC) + CARD_LIFETIME).isoformat(),
        })

    def open_question_card(self, room_id: str, request_id: str, question: str, choices: list[str]) -> None:
        self._call("POST", f"/agent-sessions/{self.session_id}/approvals", json={
            "request_id": request_id,
            "turn_id": request_id,
            "kind": "questions",
            "title": QUESTION_CARD_TITLE,
            "detail": None,
            "options": [],
            "questions": [{
                "id": "answer",
                "title": QUESTION_TITLE,
                "prompt": question[:MAX_DETAIL_CHARS],
                "options": [{"id": choice_id, "label": choice, "description": None} for choice_id, choice in zip(_choice_ids(choices), choices)],
                "multi_select": False,
                "allow_custom_answer": False,
            }],
            "room_id": room_id,
            "thread_id": None,
            "expires_at": (datetime.now(UTC) + CARD_LIFETIME).isoformat(),
        })

    def close_card(self, request_id: str) -> None:
        self._call("POST", f"/agent-sessions/{self.session_id}/approvals/{request_id}/close")

    def outcomes(self) -> list[Outcome]:
        return [
            Outcome(row["sessionId"], row["requestId"], row["state"], row["answer"], row["answeredBy"], row.get("answers"))
            for row in self._call("GET", "/agent-sessions/approvals/outcomes").json()
        ]

    def ack_outcome(self, session_id: str, request_id: str) -> None:
        self._call("POST", f"/agent-sessions/{session_id}/approvals/{request_id}/delivered")

    async def events(self, rooms: list[str]) -> AsyncIterator[dict]:
        timeout = httpx.Timeout(30, read=None)
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=timeout, transport=self.transport) as http:
            beat = asyncio.create_task(self._beat(http))
            try:
                while True:
                    try:
                        async for event in self._stream(http, rooms):
                            yield event
                    except httpx.TransportError as error:
                        logger.warning("Switch stream dropped: %s", error)
                    except httpx.HTTPStatusError as error:
                        # A restarting Switch answers 5xx. Anything else, such as a wrong key, won't fix itself.
                        if error.response.status_code < 500:
                            rooms = await self._rooms_left_after(http, rooms, error)
                        else:
                            logger.warning("Switch stream refused: %s", error)
                    await asyncio.sleep(self.reconnect_seconds)
            finally:
                beat.cancel()

    async def _rooms_left_after(self, http: httpx.AsyncClient, rooms: list[str], refusal: httpx.HTTPStatusError) -> list[str]:
        # Switch refuses the whole stream over one room, so a deleted chat would otherwise stop every other room.
        if refusal.response.status_code != 403:
            raise refusal
        answers = [await http.get(f"/agents/{self.agent_id}/rooms/{room}/history", params={"limit": 1}) for room in rooms]
        closed = [room for room, answer in zip(rooms, answers) if answer.status_code in (403, 404)]
        if not closed or len(closed) == len(rooms):
            raise refusal
        logger.warning("Stopped following %s: Switch has no such room or the desk isn't in it. Take it out of FOUNDRY_ROOMS in .env.", ", ".join(closed))
        return [room for room in rooms if room not in closed]

    async def _stream(self, http: httpx.AsyncClient, rooms: list[str]) -> AsyncIterator[dict]:
        params = {"connection_id": self.connection_id, "scope": "all", "filter": "all", "rooms": ",".join(rooms)}
        headers = {"Accept": "text/event-stream"}
        if self.cursor:
            headers["Last-Event-ID"] = str(self.cursor)
        async with http.stream("GET", f"/agents/{self.agent_id}/events", params=params, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("id:") and line[3:].strip().isdigit():
                    self.cursor = int(line[3:])
                elif line.startswith("data:"):
                    try:
                        event = json.loads(line[5:])
                    except json.JSONDecodeError:
                        logger.warning("Skipped an event that was not JSON: %s", line[:200])
                        continue
                    yield event

    async def _beat(self, http: httpx.AsyncClient) -> None:
        while True:
            await asyncio.sleep(self.beat_seconds)
            try:
                response = await http.post(f"/agents/{self.agent_id}/connection/beat",
                                           json={"connection_id": self.connection_id, "cursor": self.cursor})
                response.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("Switch heartbeat failed: %s", error)
