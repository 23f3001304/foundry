"""What one business tells the clean-up step: what counts as an update, its words, its report shape and its documents."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_SET_TIMES = ("10:00", "18:00")


def _clock_times(values: list | tuple) -> tuple[str, ...]:
    # YAML reads an unquoted 10:00 as the number 600.
    return tuple(value if isinstance(value, str) else f"{value // 60:02d}:{value % 60:02d}" for value in values)


def _set_times(named: list | tuple = ()) -> tuple[str, ...]:
    # FOUNDRY_SET_TIMES is for short live runs, so it beats whatever a pack names.
    override = tuple(time.strip() for time in os.environ.get("FOUNDRY_SET_TIMES", "").split(",") if time.strip())
    return override or _clock_times(named) or DEFAULT_SET_TIMES


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
        set_times=_set_times(data.get("set_times") or ()),
        jump_share=float(data.get("jump_share", Pack.jump_share)),
        working_hours=_clock_times(data.get("working_hours") or Pack.working_hours),
        ask_again_hours=int(data.get("ask_again_hours", Pack.ask_again_hours)),
        measures=tuple(data.get("measures") or ()),
        dashboard=tuple(data.get("dashboard") or ()),
    )
