"""Loads a brand kit: front matter with the tokens, then plain guidance for the agents."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from mcp.server.mcpserver.exceptions import ToolError

from foundry.text import on_the_network

# The opening is dashes and the end of the line, and nothing that can be matched more than one way. A pattern that could take the line breaks after the dashes in more than one way took longer for every one of them.
FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n(.*))?\Z", re.DOTALL)
# What a deck, a prompt or a file name can't take inside a word: the controls, which XML refuses. A voice may run over several lines, so it may have those.
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
LINE_BREAKS = "\n\r\t"
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
REQUIRED = ("name", "colors", "fonts", "voice")
COLOURS = ("primary", "accent", "ink", "paper")
# A kit with only a primary colour still builds. White paper and near-black ink are always readable.
DEFAULT_PAPER, DEFAULT_INK = "#FFFFFF", "#222222"


# Most of a value that is shown back in an error. The kit is somebody's file, so what is in it is never quoted at length.
MOST_QUOTED = 30
MOST_SHOWN = 200
ALIASES = "The brand kit can't use YAML aliases (&name and *name). Write each value out."
TOO_DEEP = "The brand kit's front matter is nested too deeply."
NOT_CLOSED = "The brand kit's front matter has no closing --- line."
LOGO = "logo.png"
STICKER_MODES = ("off", "subtle", "playful")
# The same logo for a dark ground, in a kit that has one.
LOGO_ON_DARK = "logo-on-dark.png"


class BrandError(ToolError):
    # A ToolError, so a maker whose tool cannot read the brand folder is shown why. A plain exception reaches it only as "Error executing tool".
    pass


class _NoAliases(yaml.SafeLoader):
    # A few hundred bytes of aliases can stand for gigabytes once they are read out, and a kit has no use for them.
    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise BrandError(ALIASES)
        return super().compose_node(parent, index)


def _words(value: object, what: str, lines: bool = False) -> str:
    # Every maker, check and sticker uses these as text, so a number or a list is stopped here and not found later by whatever reads it.
    if not isinstance(value, str):
        raise BrandError(f"The brand kit's {what} must be words, not a number or a list.")
    if CONTROL.search(value.translate(str.maketrans("", "", LINE_BREAKS)) if lines else value):
        raise BrandError(f"The brand kit's {what} can't hold control characters.")
    return value


@dataclass
class Brand:
    name: str
    colors: dict[str, str]
    fonts: dict[str, str]
    voice: str
    logo_path: Path
    guidance: str = ""
    style: str = "band"
    business_type: str = ""
    # One line saying which style from the design guide fits this business. The kit's word outranks the guide's.
    design_style: str = ""
    stickers: str = ""

    @property
    def logo_on_dark(self) -> Path | None:
        path = self.logo_path.parent / LOGO_ON_DARK
        return path if path.exists() else None

    def font_file(self, role: str) -> Path | None:
        path = self.logo_path.parent / "fonts" / f"{role}.ttf"
        return path if path.exists() else None


def load_brand(text: str, assets_dir: Path) -> Brand:
    match = FRONT_MATTER.match(text)
    if match is None and text.startswith("---"):
        # Opened and never closed. Reading it as YAML would take the dashes for a document and the rest for its first part.
        raise BrandError(NOT_CLOSED)
    tokens, guidance = (match.group(1), match.group(2) or "") if match else (text, "")
    try:
        data = yaml.load(tokens, Loader=_NoAliases)
    except yaml.YAMLError as error:
        raise BrandError(f"The brand kit's front matter is not valid: {str(error)[:MOST_SHOWN]}") from error
    except RecursionError:
        raise BrandError(TOO_DEEP) from None
    if not isinstance(data, dict):
        raise BrandError("The brand kit's front matter must list its fields.")
    # Only spaces is as good as nothing.
    missing = [field for field in REQUIRED if not data.get(field) or (isinstance(data[field], str) and not data[field].strip())]
    if missing:
        raise BrandError(f"The brand kit is missing: {', '.join(missing)}")
    name, voice = _words(data["name"], "name"), _words(data["voice"], "voice", lines=True)
    colours = data["colors"]
    if not isinstance(colours, dict):
        raise BrandError('The brand kit\'s colors must list names and colours, like primary: "#7A3E1D".')
    for colour in COLOURS:
        if colour in colours or colour == "primary":
            value = colours.get(colour)
            if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
                shown = f", not {value[:MOST_QUOTED]!r}" if isinstance(value, str) else ""
                raise BrandError(f"The brand kit needs a {colour} colour like #7A3E1D{shown}")
    colours.setdefault("accent", colours["primary"])
    colours.setdefault("paper", DEFAULT_PAPER)
    colours.setdefault("ink", DEFAULT_INK)
    fonts = data["fonts"]
    if not isinstance(fonts, dict) or not all(isinstance(fonts.get(role), str) and fonts[role].strip() for role in ("heading", "body")):
        raise BrandError("The brand kit's fonts need a heading and a body.")
    for role in ("heading", "body"):
        _words(fonts[role], f"{role} font")
    # Left out, or left blank, these are nothing and the ordinary look. Anything else has to be words.
    style = "band" if data.get("style") is None else _words(data["style"], "style")
    business_type = "" if data.get("business_type") is None else _words(data["business_type"], "business_type")
    design_style = "" if data.get("design_style") is None else _words(data["design_style"], "design_style")
    # YAML reads a bare off as false.
    stickers = "off" if data.get("stickers") is False else "" if data.get("stickers") is None else _words(data["stickers"], "stickers")
    if stickers and stickers not in STICKER_MODES:
        raise BrandError(f"The brand kit's stickers must be one of {', '.join(STICKER_MODES)}.")
    logo_path = Path(assets_dir) / LOGO
    if not logo_path.exists():
        raise BrandError(f"The brand kit has no {LOGO} in its folder.")
    return Brand(name, colours, fonts, voice, logo_path, guidance.strip(), style, business_type, design_style, stickers)


BRAND_PIN = "FOUNDRY_BRAND_DIR"
PINNED = "This tool works only for the brand folder {pinned}, and {asked} is not it."
# The same name in another place: the pin names where the folder was when the makers were set up.
MOVED = "This tool was set up for {pinned}, and {asked} is not that folder. The brands folder has moved since the makers were set up, so run tools/setup_makers.py again for this client."
ANOTHER_MACHINE = "a path on another machine"


def pinned_folder() -> Path | None:
    # A client's own makers are started with their client's brand folder named here. Blank is none, as for any business whose makers are shared.
    text = os.environ.get(BRAND_PIN, "").strip()
    return Path(text) if text else None


def _the_pin_allows(asked: Path | str, pinned: Path) -> None:
    # Whether it is the pinned folder is a matter of where it really is, so a spelling in other letters or through a link is the same folder and a copy of the same name elsewhere is not.
    # A path on another machine is refused as it is written, because finding out where it is would contact that machine.
    if on_the_network(str(asked)):
        raise BrandError(PINNED.format(pinned=pinned.name, asked=ANOTHER_MACHINE))
    if on_the_network(str(pinned)):
        raise BrandError(PINNED.format(pinned=ANOTHER_MACHINE, asked=Path(asked).name))
    if os.path.normcase(os.path.realpath(asked)) == os.path.normcase(os.path.realpath(pinned)):
        return
    if Path(asked).name.casefold() == pinned.name.casefold():
        raise BrandError(MOVED.format(pinned=pinned, asked=asked))
    raise BrandError(PINNED.format(pinned=pinned.name, asked=Path(asked).name))


def load_brand_dir(brand_dir: Path | str) -> Brand:
    folder = Path(brand_dir)
    # So their tools open no other client's kit, logo or picture.
    if (pinned := pinned_folder()) is not None:
        _the_pin_allows(brand_dir, pinned)
    kit = folder / "kit.md"
    if not kit.exists():
        # The brand's name and not where it is kept, since this reaches pages and the makers.
        raise BrandError(f"There is no kit.md in the {folder.name} brand folder.")
    return load_brand(kit.read_text(encoding="utf-8"), folder)
