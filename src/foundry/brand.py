"""Loads a brand kit: front matter with the tokens, then plain guidance for the agents."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---[ \t]*(?:\r?\n(.*))?\Z", re.DOTALL)
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
REQUIRED = ("name", "colors", "fonts", "voice")


class BrandError(Exception):
    pass


@dataclass
class Brand:
    name: str
    colors: dict[str, str]
    fonts: dict[str, str]
    voice: str
    logo_path: Path
    guidance: str = ""

    def font_file(self, role: str) -> Path | None:
        path = self.logo_path.parent / "fonts" / f"{role}.ttf"
        return path if path.exists() else None


def load_brand(text: str, assets_dir: Path) -> Brand:
    match = FRONT_MATTER.match(text)
    tokens, guidance = (match.group(1), match.group(2) or "") if match else (text, "")
    try:
        data = yaml.safe_load(tokens)
    except yaml.YAMLError as error:
        raise BrandError(f"The brand kit's front matter is not valid: {error}") from error
    if not isinstance(data, dict):
        raise BrandError("The brand kit's front matter must list its fields.")
    missing = [field for field in REQUIRED if not data.get(field)]
    if missing:
        raise BrandError(f"The brand kit is missing: {', '.join(missing)}")
    primary = data["colors"].get("primary", "")
    if not HEX_COLOUR.fullmatch(str(primary)):
        raise BrandError(f"The brand kit needs a primary colour like #7A3E1D, not {primary!r}")
    logo_path = Path(assets_dir) / "logo.png"
    if not logo_path.exists():
        raise BrandError(f"The brand kit has no logo at {logo_path}")
    return Brand(data["name"], data["colors"], data["fonts"], data["voice"], logo_path, guidance.strip())
