"""What one business tells the clean-up step: what counts as an update, its words, its report shape and its documents."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Pack:
    update_rule: str = ""
    glossary: str = ""
    report_format: str = ""
    report_room: str = ""
    sources: dict[str, str] = field(default_factory=dict)


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
    )
