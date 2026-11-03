"""Loads a brand kit: front matter with the tokens, then plain guidance for the agents."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---[ \t]*(?:\r?\n(.*))?\Z", re.DOTALL)
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
REQUIRED = ("name", "colors", "fonts", "voice")
COLOURS = ("primary", "accent", "ink", "paper")
# A kit with only a primary colour still builds. White paper and near-black ink are always readable.
DEFAULT_PAPER, DEFAULT_INK = "#FFFFFF", "#222222"


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
    style: str = "band"

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
    colours = data["colors"]
    for name in COLOURS:
        if name in colours or name == "primary":
            if not HEX_COLOUR.fullmatch(str(colours.get(name, ""))):
                raise BrandError(f"The brand kit needs a {name} colour like #7A3E1D, not {colours.get(name)!r}")
    colours.setdefault("accent", colours["primary"])
    colours.setdefault("paper", DEFAULT_PAPER)
    colours.setdefault("ink", DEFAULT_INK)
    fonts = data["fonts"]
    if not fonts.get("heading") or not fonts.get("body"):
        raise BrandError("The brand kit's fonts need a heading and a body.")
    logo_path = Path(assets_dir) / "logo.png"
    if not logo_path.exists():
        raise BrandError(f"The brand kit has no logo at {logo_path}")
    return Brand(data["name"], data["colors"], data["fonts"], data["voice"], logo_path, guidance.strip(), data.get("style", "band"))


def load_brand_dir(brand_dir: Path | str) -> Brand:
    folder = Path(brand_dir)
    kit = folder / "kit.md"
    if not kit.exists():
        raise BrandError(f"There is no kit.md in {folder}")
    return load_brand(kit.read_text(encoding="utf-8"), folder)
