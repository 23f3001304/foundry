"""What one business tells the clean-up step: what counts as an update, its words, its report shape and its documents."""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from foundry.text import same_login

DEFAULT_SET_TIMES = ("10:00", "18:00")


class PackError(ValueError):
    pass


def _clock_times(values: list | tuple) -> tuple[str, ...]:
    # YAML reads an unquoted 10:00 as the number 600.
    return tuple(f"{value // 60:02d}:{value % 60:02d}" if isinstance(value, int) else str(value) for value in values)


def _set_times(named: object = None) -> tuple[str, ...]:
    # YAML reads a lone 18:00 as the number 1080, and a quoted one would be read a character at a time.
    if named is not None and not isinstance(named, list):
        raise PackError(f"I can't read set_times {named!r} in the pack. Write it as a list, like [10:00, 18:00].")
    # FOUNDRY_SET_TIMES is for short live runs, so it beats whatever a pack names.
    override = tuple(time.strip() for time in os.environ.get("FOUNDRY_SET_TIMES", "").split(",") if time.strip())
    return override or _clock_times(named or ()) or DEFAULT_SET_TIMES


DASHBOARD_LINE = "{login: manager-a, acts_as: '@manager-a:localhost'}"


def _dashboard(named: object = None) -> tuple[dict, ...]:
    # Who may manage the business on the dashboard, and who each acts as in chat. Read here, so a typo stops the desk when it starts and names the line.
    if named is None:
        return ()
    if not isinstance(named, list):
        raise PackError(f"I can't read dashboard {named!r} in the pack. Write it as a list with a login and an acts_as on each line, like [{DASHBOARD_LINE}].")
    for number, listed in enumerate(named, start=1):
        if not isinstance(listed, dict) or not all(isinstance(listed.get(key), str) and listed[key].strip() for key in ("login", "acts_as")):
            raise PackError(f"I can't read entry {number} of dashboard in the pack: {listed!r}. Each needs a login and an acts_as, like {DASHBOARD_LINE}.")
    return tuple({**listed, "login": _login(listed["login"]), "acts_as": _approver(listed["acts_as"])} for listed in named)


@dataclass(frozen=True)
class Pack:
    update_rule: str = ""
    glossary: str = ""
    report_format: str = ""
    report_room: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    approver: str = ""
    set_times: tuple[str, ...] = field(default_factory=_set_times)
    jump_share: float = 0.2
    working_hours: tuple[str, str] = ("09:00", "19:00")
    ask_again_hours: int = 24
    measures: tuple[str, ...] = ()
    dashboard: tuple[dict, ...] = ()

    def lists(self, login: str, acts_as: str) -> bool:
        # Whether the dashboard list names this login, acting as this identity. Both sides are matched as the dashboard matches them.
        wanted, identity = same_login(login), str(acts_as or "").strip()
        return bool(wanted and identity) and any(
            isinstance(listed, dict) and same_login(listed.get("login")) == wanted and str(listed.get("acts_as") or "").strip() == identity for listed in self.dashboard
        )

    def __post_init__(self) -> None:
        # Refused here, when the desk starts. Left alone, a typo would raise on every tick.
        for time in self.set_times:
            try:
                datetime.strptime(time, "%H:%M")
            except ValueError:
                raise PackError(f"I can't read the set time {time!r}. Write it as HH:MM on a 24-hour clock, like 18:00, in FOUNDRY_SET_TIMES or the pack's set_times.") from None


def _approver(named: object) -> str:
    # A Switch sender id holds the bridge's id, which differs on every install, so a pack writes {bridge} and the environment fills it in.
    approver = str(named or "").strip()
    bridge = os.environ.get("FOUNDRY_MATTERMOST_BRIDGE", "").strip()
    return approver.replace("{bridge}", bridge) if bridge else approver


def _login(named: str) -> str:
    # A dashboard login is a Switch login, so a demo's pack writes {switch_email} and whoever runs it signs in as the admin of their own stack.
    email = os.environ.get("SWITCH_EMAIL", "").strip()
    return named.replace("{switch_email}", email) if email else named


def load_pack(brand_dir: Path | str) -> Pack:
    folder = Path(brand_dir)
    if not (folder / "pack.md").is_file():
        return Pack()
    data = yaml.safe_load((folder / "pack.md").read_text(encoding="utf-8").split("---", 2)[1])
    sources = {file.stem: file.read_text(encoding="utf-8") for file in sorted((folder / "sources").glob("*.md"))}
    return Pack(
        update_rule=data.get("update_rule", "").strip(),
        glossary=data.get("glossary", "").strip(),
        report_format=data.get("report_format", "").strip(),
        report_room=data.get("report_room", "").strip(),
        sources=sources,
        approver=_approver(data.get("approver")),
        set_times=_set_times(data.get("set_times")),
        jump_share=float(data.get("jump_share", Pack.jump_share)),
        working_hours=_clock_times(data.get("working_hours") or Pack.working_hours),
        ask_again_hours=int(data.get("ask_again_hours", Pack.ask_again_hours)),
        measures=tuple(data.get("measures") or ()),
        dashboard=_dashboard(data.get("dashboard")),
    )
