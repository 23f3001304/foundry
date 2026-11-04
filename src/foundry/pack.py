"""What one business tells the clean-up step: what counts as an update, its words, its report shape and its documents."""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

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

    def __post_init__(self) -> None:
        # Refused here, when the desk starts. Left alone, a typo would raise on every tick.
        for time in self.set_times:
            try:
                datetime.strptime(time, "%H:%M")
            except ValueError:
                raise PackError(f"I can't read the set time {time!r}. Write it as HH:MM on a 24-hour clock, like 18:00, in FOUNDRY_SET_TIMES or the pack's set_times.") from None


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
        approver=str(data.get("approver") or "").strip(),
        set_times=_set_times(data.get("set_times")),
        jump_share=float(data.get("jump_share", Pack.jump_share)),
        working_hours=_clock_times(data.get("working_hours") or Pack.working_hours),
        ask_again_hours=int(data.get("ask_again_hours", Pack.ask_again_hours)),
        measures=tuple(data.get("measures") or ()),
        dashboard=tuple(data.get("dashboard") or ()),
    )
