"""Try mode: the real dashboard on made-up data, started by ./setup.sh --try. It needs no Docker, no agents and no sign-in to anything.

Its login, its Switch and every business in it are made up. It keeps everything in .foundry/try and wipes that folder when it starts. It answers on this machine only, connects to nothing, and never looks at a .env.
"""

import logging
import os
import secrets
import shutil
import socket
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import foundry.desk
from foundry.cards import CardQueue, Trigger
from foundry.commands import CommandStore
from foundry.dashboard.app import create_app
from foundry.desk import Settings, Workrooms
from foundry.items import ItemState, ItemStore
from foundry.jobs import JobStore, State
from foundry.log import Log
from foundry.pack import load_pack
from foundry.tools.deck_server import build_deck
from foundry.tools.graphic_server import render_graphic

HOST = "127.0.0.1"
FIRST_PORT = 8190
# Made up here and printed by this mode alone. They open nothing but this demo's own pages.
LOGIN = "try@foundry.local"
PASSWORD = "try-it-out"
# Never looked up. The dashboard's calls to Switch all go to answer() below.
NOWHERE = "http://switch.try-mode.invalid"
BRIDGE = "try"
OWN_FOLDER_MARK = ".try-mode-data"
# Anything like these in this process's environment came from somewhere real, and nothing here may read it.
REAL_SETTINGS = ("FOUNDRY_", "SWITCH_", "MATTERMOST_", "ANTHROPIC_", "SARVAM_", "SLACK_", "TELEGRAM_", "WHATSAPP_", "GOOGLE_", "OPENAI_", "CLAUDE_")
# Each business, with who signs in as whom.
BUSINESSES = {
    "demo-it-firm": "Delivery Manager",
    "demo-investment-firm": "Analyst Lead",
    "demo-agency-client-a": "Account Director",
    "demo-agency-client-b": "Account Director",
    "lalten-cafe": "Cafe Manager",
}
ROOM_NAMES = {
    "demo-it-firm": ("delivery", "team-a", "team-b", "team-c"),
    "demo-investment-firm": ("analysts", "office-a", "office-b", "office-c", "office-d", "office-e"),
    "demo-agency-client-a": ("phatakha",),
    "demo-agency-client-b": ("ambaryug",),
    "lalten-cafe": ("lalten",),
}
AGENCY = ("demo-agency-client-a", "demo-agency-client-b")
# What the overview's charts draw, in the same form as a scene's earlier history. All of it fictional.
SCENES = {
    "demo-agency-client-a": {
        "brand": "demo-agency-client-a",
        "history": [{"as": "Marketing Manager A", "room": "phatakha", "days_ago": 2, "say": "The summer mango range goes on sale next month."}],
        "earlier_work": {"as": "Marketing Manager A", "room": "phatakha", "say": "The launch posts went out well.", "jobs": ["Launch posts for Kokum Fizz", "Retailer deck for the summer range", "Festival poster set"], "stuck": [{"days_ago": 9, "title": "Stuck: Festival poster set", "detail": "The visual maker stopped on a size the kit has no layout for."}]},
    },
    "demo-agency-client-b": {
        "brand": "demo-agency-client-b",
        "history": [{"as": "Marketing Manager B", "room": "ambaryug", "days_ago": 3, "say": "The first flush lots have reached the warehouse."}],
        "earlier_work": {"as": "Marketing Manager B", "room": "ambaryug", "say": "The tasting notes read well.", "jobs": ["Tasting notes for the winter blend", "Gift box leaflet", "Estate story deck"], "stuck": []},
    },
    "lalten-cafe": {
        "brand": "lalten-cafe",
        "history": [{"as": "Cafe Manager", "room": "lalten", "days_ago": 1, "say": "Saturday was the busiest morning this month."}],
        "earlier_work": {"as": "Cafe Manager", "room": "lalten", "say": "The poster is up by the door.", "jobs": ["Weekend menu card", "Filter coffee poster", "Staff rota note"], "stuck": []},
    },
}
BANNER_WORDS = {
    "login": LOGIN,
    "password": PASSWORD,
}
SWITCH_ADMIN_ONLY = "This is try mode, so no connection can be added or removed."


class _NoChat:
    """Stands in for Switch when a made-up card opens. Nothing is posted anywhere."""

    def __getattr__(self, _name: str):
        return lambda *_arguments, **_options: None


def person(title: str) -> str:
    return f"@switch-mattermost-{BRIDGE}-{'-'.join(title.casefold().split())}:localhost"


def forget_real_settings() -> None:
    for name in list(os.environ):
        if name.upper().startswith(REAL_SETTINGS):
            del os.environ[name]
    # What the demo packs write as {switch_email} and {bridge}.
    os.environ["SWITCH_EMAIL"] = LOGIN
    os.environ["FOUNDRY_MATTERMOST_BRIDGE"] = BRIDGE


def fresh_folder(folder: Path) -> None:
    # Wiped on every start, so it is refused unless this mode made it.
    if folder.exists() and any(folder.iterdir()) and not (folder / OWN_FOLDER_MARK).exists():
        raise ValueError(f"{folder} isn't try mode's own folder, so nothing in it was touched.")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / OWN_FOLDER_MARK).write_text("Made-up data for try mode. It is wiped each time try mode starts.\n", encoding="utf-8")


def answer(request: httpx.Request) -> httpx.Response:
    # All the Switch this mode has. Only the made-up login gets in.
    path = request.url.path
    if path == "/gateway/auth/login":
        import json

        sent = json.loads(request.content)
        if sent.get("email", "").casefold() == LOGIN and sent.get("password") == PASSWORD:
            return httpx.Response(200, json={}, headers={"set-cookie": "try_mode=1; Path=/; HttpOnly"})
        return httpx.Response(401, json={"detail": "Wrong login"})
    if request.method != "GET":
        return httpx.Response(403, json={"detail": SWITCH_ADMIN_ONLY})
    if path == "/gateway/collaborations":
        return httpx.Response(200, json=[
            {"bridge_id": BRIDGE, "bridge_type": "mattermost", "display_name": "Team chat (made up)", "status": "active", "attention": None, "room_count": sum(len(names) for names in ROOM_NAMES.values())},
        ])
    if path == "/gateway/rooms":
        return httpx.Response(200, json=[{"id": f"try-{name}", "name": name, "bridge_id": BRIDGE} for names in ROOM_NAMES.values() for name in names])
    if path == "/gateway/collaborations/types":
        return httpx.Response(200, json=[{
            "key": "mattermost", "display_name": "Mattermost", "channel_creation_supported": True,
            "config_schema": {"properties": {"url": {"title": "Server address", "type": "string"}, "access_token": {"title": "Access", "type": "string", "format": "password"}}, "required": ["url", "access_token"]},
        }])
    return httpx.Response(404, json={"detail": "Not in try mode."})


def settings_in(folder: Path) -> Settings:
    rooms = {name: bucket for bucket, names in ROOM_NAMES.items() for name in names}
    workrooms, brands, packs = {}, {}, {}
    for name, bucket in rooms.items():
        outside = f"try-{name}"
        if bucket in AGENCY:
            workrooms[outside] = Workrooms(f"{outside}-studio", f"{outside}-review", f"-{name}")
        else:
            workrooms[outside] = Workrooms(f"{outside}-projects", f"{outside}-projects")
        brands |= {outside: bucket, workrooms[outside].studio: bucket, workrooms[outside].review: bucket}
        packs[outside] = replace(load_pack(folder / "brands" / bucket), dashboard=({"login": LOGIN, "acts_as": person(BUSINESSES[bucket])},))
    return Settings(
        buffer_path=folder / "buffer.db", log_path=folder / "log.db", work_path=folder / "work.db", jobs_path=folder / "jobs.db", inputs_dir=folder / "inputs",
        workrooms=workrooms, brands=brands, packs=packs, sticker_mode="off", utc_offset_minutes=330,
    )


class World:
    """Writes what the desk would have written, in the desk's own files, all of it marked as seeded."""

    def __init__(self, settings: Settings, folder: Path, now: datetime) -> None:
        self.settings, self.folder, self.now = settings, folder, now
        self.jobs = JobStore(settings.jobs_path)
        self.log = Log(settings.log_path)
        self.items = ItemStore(settings.work_path)
        self.cards = CardQueue(settings.work_path, _NoChat(), self.log, lambda: now)
        CommandStore(settings.commands_path)
        self.made = folder / "made"
        self.made.mkdir()

    def job(self, bucket: str, room: str, title: str, state: State, opened_hours_ago: float, asked_by: str, words: str):
        room_id = f"try-{room}"
        boss = person(BUSINESSES[bucket])
        job = self.jobs.create(room_id, person(asked_by), boss, bucket)
        job.brief, job.state = f"What is being made: {title}\nWho it is for: the team that asked.\nMade-up data for try mode.", state
        self.jobs.save(job)
        self.say(job, opened_hours_ago, asked_by, "message", words)
        self.say(job, opened_hours_ago - 0.01, "foundry-desk", "job_opened", title)
        return job

    def say(self, job, hours_ago: float, who: str, kind: str, text: str, ref: str | None = None) -> None:
        self.log.add_seeded(self.now - timedelta(hours=hours_ago), job.bucket, job.room_id, person(who) if not who.startswith("foundry-") else who, kind, text, sender_name=who, job_id=job.id, ref=ref)

    def owes(self, job, who: str, room: str, what: str, measure: str, due_hours: float, answered: str = "", reason: str = "") -> None:
        item = self.items.create(job.id, job.bucket, person(who), who, f"try-{room}", what, measure, self.now + timedelta(hours=due_hours))
        item.asked_at = self.now - timedelta(hours=abs(due_hours) + 3)
        self.say(job, abs(due_hours) + 3, "foundry-desk", "item_asked", f"{who}: {what}")
        if answered:
            item.state, item.answer = ItemState.ANSWERED, answered
            self.say(job, abs(due_hours) + 1, who, "item_answer", answered)
        elif reason:
            item.reason = reason
            self.say(job, abs(due_hours) + 1, who, "item_reason", reason)
        self.items.save(item)

    def deck(self, job, name: str, title: str, slides: list[dict], maker: str = "foundry-deck", hours_ago: float = 1) -> None:
        path = build_deck(str(self.folder / "brands" / job.bucket), title, slides, str(self.made / f"{job.id[:6]}-{name}.pptx"))
        self.say(job, hours_ago, maker, "file_made", Path(path).name, ref=path)

    def picture(self, job, name: str, words: str, line: str, maker: str = "foundry-visual", hours_ago: float = 1) -> None:
        path = render_graphic(str(self.folder / "brands" / job.bucket), words, line, "1080x1080", str(self.made / f"{job.id[:6]}-{name}.png"), composition="statement")
        self.say(job, hours_ago, maker, "file_made", Path(path).name, ref=path)

    def card(self, job, trigger: Trigger, title: str, detail: str, choices: tuple[str, ...] = ("Approve", "Revise")) -> None:
        request_id = uuid.uuid4().hex
        self.cards.submit(trigger, job.approver, job.bucket, job.room_id, title, detail, choices, job_id=job.id, request_id=request_id)
        job.approval = {"request_id": request_id, "title": title, "detail": detail, "awaiting_notes": False, "room_id": job.room_id}
        self.jobs.save(job)
        self.say(job, 0.5, "foundry-desk", "card_opened", title, ref=request_id)

    def history(self) -> None:
        # The same tool the real demos use, with the same mark on what it writes.
        import seed_history
        from demo_people import load_scene

        rooms = {name: f"try-{name}" for names in ROOM_NAMES.values() for name in names}
        for scene in (load_scene("it_firm"), load_scene("investment_firm"), *SCENES.values()):
            seed_history.seed(scene, self.log, rooms, BRIDGE, self.now, self.cards)


def it_firm(world: World) -> None:
    deck = world.job("demo-it-firm", "delivery", "Release status deck for Harsingar Stores", State.COLLECTING, 6, "Delivery Manager", "I need the release status deck for Harsingar Stores. Team Leads A, B and C each owe me stories closed and defects open.")
    world.owes(deck, "Team Lead A", "team-a", "Team A stories closed and defects open", "two whole numbers", -1, answered="Team A closed 41 stories this sprint and has 3 defects open.")
    world.owes(deck, "Team Lead B", "team-b", "Team B stories closed and defects open", "two whole numbers", -1, reason="blocked on QA")
    world.owes(deck, "Team Lead C", "team-c", "Team C stories closed and defects open", "two whole numbers", -1)
    qa = world.job("demo-it-firm", "delivery", "QA summary for the customer portal", State.SIGNOFF_PENDING, 20, "Delivery Manager", "Please make the QA summary for the customer portal.")
    world.deck(qa, "qa-summary", "QA summary", [
        {"layout": "chart", "title": "Defects open by team", "caption": "Defects open at the end of the sprint", "labels": ["Team A", "Team B", "Team C"], "values": [3, 7, 5], "unit": ""},
        {"layout": "content", "title": "What comes next", "bullets": ["Team A retests the login fixes", "Team B waits on QA", "Team C closes the reporting module"]},
    ])
    world.say(qa, 0.8, "foundry-reviewer", "review", "Checked against the brief and the kit. It passes.")
    world.card(qa, Trigger.FINAL_WORK, "Final work: QA summary for the customer portal", "The reviewer passed it. Approve to send it to the room.")
    stuck = world.job("demo-it-firm", "delivery", "Sprint review deck for Team B", State.BLOCKED, 30, "Team Lead B", "We need the sprint review deck for Team B.")
    stuck.attention = ["The deck maker stopped on the velocity table."]
    world.jobs.save(stuck)
    world.say(stuck, 2, "foundry-deck", "agent_marker", "WORK_BLOCKED The velocity table has no figures for sprint 14.")
    world.card(stuck, Trigger.STUCK, "Stuck: Sprint review deck for Team B", "The deck maker stopped on the velocity table.", ())
    world.job("demo-it-firm", "delivery", "UAT report for the reporting module", State.MAKING, 3, "Delivery Manager", "Make the UAT report for the reporting module.")
    world.job("demo-it-firm", "delivery", "Defect summary for Team C", State.REVIEWING, 5, "Team Lead C", "Please summarise the defects for Team C.")
    notes = world.job("demo-it-firm", "delivery", "Release notes for the payment fixes", State.DELIVERED, 50, "Delivery Manager", "Please make the release notes for the payment fixes.")
    world.deck(notes, "release-notes", "Release notes", [{"layout": "content", "title": "Payment fixes", "bullets": ["Refunds no longer time out", "Receipts carry the right tax line"]}], hours_ago=30)
    world.say(notes, 28, "foundry-desk", "delivered", "Release notes for the payment fixes")


def investment_firm(world: World) -> None:
    review = world.job("demo-investment-firm", "analysts", "Quarterly review deck for the partners' meeting", State.COLLECTING, 8, "Analyst Lead", "I need the quarterly review deck for the partners' meeting. Office Heads A to E each owe their office's assets under management.")
    figures = {"A": "6,420", "B": "5,180", "C": "", "D": "4,950", "E": "19,800"}
    for letter, figure in figures.items():
        world.owes(review, f"Office Head {letter}", f"office-{letter.lower()}", f"Office {letter} assets under management at quarter end", "crore rupees, a whole number", -2, answered=f"Office {letter} ended the quarter at {figure} crore." if figure else "")
    fees = world.job("demo-investment-firm", "analysts", "Fee summary for Office E", State.SIGNOFF_PENDING, 26, "Analyst Lead", "Please make the fee summary for Office E.")
    world.deck(fees, "fee-summary", "Fee summary", [{"layout": "big_number", "title": "Fees this quarter", "number": "142", "caption": "Crore rupees, made up"}])
    world.card(fees, Trigger.FINAL_WORK, "Final work: Fee summary for Office E", "The reviewer passed it. Approve to send it to the room. Internal summary of made-up numbers, not advice.")


def agency(world: World) -> None:
    mango = world.job("demo-agency-client-a", "phatakha", "Mango Masala campaign set: deck, poster and social posts", State.REVIEWING, 7, "Marketing Manager A", "We need the full campaign set for Mango Masala.")
    # The dashboard learns a person's name from what they said, and the Account Director approves both clients' work.
    world.say(mango, 6.9, "Account Director", "message", "Thanks. Send it to me when the reviewer has passed it.")
    world.deck(mango, "mango-masala", "Mango Masala", [{"layout": "statement", "text": "Loud, sweet and a little hot."}, {"layout": "content", "title": "Where it runs", "bullets": ["Shop posters", "Social posts", "Retailer deck"]}], maker="foundry-deck-phatakha")
    world.picture(mango, "mango-poster", "Mango Masala", "This summer", maker="foundry-visual-phatakha")
    tea = world.job("demo-agency-client-b", "ambaryug", "First Flush Reserve campaign set: deck, poster and social posts", State.SIGNOFF_PENDING, 22, "Marketing Manager B", "We need the campaign set for the First Flush Reserve.")
    world.say(tea, 21.9, "Account Director", "message", "Thanks. Send it to me when the reviewer has passed it.")
    world.deck(tea, "first-flush", "First Flush Reserve", [{"layout": "statement", "text": "Picked in spring, in small lots."}], maker="foundry-deck-ambaryug")
    world.picture(tea, "first-flush-poster", "First Flush Reserve", "Small lots, this spring", maker="foundry-visual-ambaryug")
    world.card(tea, Trigger.FINAL_WORK, "Final work: First Flush Reserve campaign set", "The reviewer passed it. Approve to send it to the client's room.")


def coffee_shop(world: World) -> None:
    menu = world.job("lalten-cafe", "lalten", "Weekend menu deck and poster", State.DELIVERED, 40, "Cafe Manager", "We need a short deck for our weekend menu launch and one poster to go with it.")
    world.deck(menu, "weekend-menu", "Weekend menu", [{"layout": "content", "title": "This weekend", "bullets": ["Kerala filter coffee", "Masala omelette", "Banana bread"]}, {"layout": "statement", "text": "Open from 7am on Saturday."}], hours_ago=30)
    world.picture(menu, "weekend-poster", "Filter coffee", "Open from 7am on Saturday", hours_ago=30)
    world.say(menu, 28, "foundry-desk", "delivered", "Weekend menu deck and poster")
    rains = world.job("lalten-cafe", "lalten", "Monsoon menu poster", State.BRIEF_PENDING, 2, "Cafe Manager", "One poster for the monsoon menu, please.")
    world.card(rains, Trigger.BRIEF, "Brief: Monsoon menu poster", "What is being made: one poster for the monsoon menu. Approve to start it.")


def build_app(folder: Path) -> Starlette:
    forget_real_settings()
    fresh_folder(folder)
    # A save on the Data page lands in this copy, and the real brand folders are never in reach.
    for bucket in BUSINESSES:
        shutil.copytree(REPO / "brands" / bucket, folder / "brands" / bucket)
    foundry.desk.BRANDS = folder / "brands"
    settings = settings_in(folder)
    world = World(settings, folder, datetime.now(UTC))
    world.history()
    it_firm(world)
    investment_firm(world)
    agency(world)
    coffee_shop(world)
    app = create_app(settings, NOWHERE, httpx.MockTransport(answer), secrets.token_hex(32))
    # Only here, and base.html shows the banner only when it is set.
    app.state.templates.env.globals["try_mode"] = BANNER_WORDS
    return app


def free_port(port: int) -> int:
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((HOST, port))
            return port
        except OSError:
            port += 1
        finally:
            probe.close()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    print("Making up the data...", flush=True)
    app = build_app(REPO / ".foundry" / "try")
    port = free_port(FIRST_PORT)
    print(flush=True)
    print("  TRY MODE. Everything in it is made up, no agents are running and nothing is sent anywhere.", flush=True)
    print(f"  Open      http://{HOST}:{port}", flush=True)
    print(f"  Login     {LOGIN}", flush=True)
    print(f"  Password  {PASSWORD}", flush=True)
    print("  Both work only in try mode. The real setup generates its own and never prints them.", flush=True)
    print("  Press Ctrl+C to stop.", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
