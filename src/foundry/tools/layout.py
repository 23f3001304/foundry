"""Measures text with the brand's own font, so nothing spills off a slide or a graphic."""

import re
from decimal import Decimal
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError
from PIL import ImageFont

LINE_SPACING = 1.2
UNDRAWABLE = "\U0010FFFF"
# What a chart or a table says for a figure nobody sent. It holds no number, so the number check has nothing to read in it.
NOT_RECEIVED = "not received"
# Spaces a line can break at, which a non-breaking space is not.
BREAKS = re.compile(r"[^\S ]+")


class MakerError(ToolError, ValueError):
    """Something a maker asked a tool for that the tool cannot do. Under mcp 2.x a plain ValueError reaches the maker only as "Error executing tool", so it retries blind. A ToolError shows why."""


def load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)


def check_font_can_draw(text: str, font: ImageFont.FreeTypeFont, role: str) -> None:
    # A font draws the same empty box for every letter it lacks. Refuse rather than ship boxes.
    box = bytes(font.getmask(UNDRAWABLE))
    missing = sorted({letter for letter in text if not letter.isspace() and bytes(font.getmask(letter)) == box})
    if missing:
        raise MakerError(f"The brand's {role} font cannot draw: {' '.join(missing[:10])}. Write this text in a script the font has.")


def words_of(text: str) -> list[str]:
    return list(filter(None, BREAKS.split(text)))


def wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in words_of(paragraph):
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while font.getlength(word) > width:
                cut = next((end for end in range(len(word) - 1, 0, -1) if font.getlength(word[:end]) <= width), 1)
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def fit_size(text: str, font_path: Path | None, width: float, height: float, largest: int, smallest: int) -> int:
    for size in range(largest, smallest - 1, -1):
        if len(wrap(text, load_font(font_path, size), width)) * size * LINE_SPACING <= height:
            return size
    raise MakerError(f"This text is too long to fit: {text[:60]}...")


def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[start:start + 2], 16) for start in (1, 3, 5))


def mix(colour: str, other: str, share: float) -> str:
    # One colour moved this share of the way toward another.
    mixed = [round(part * (1 - share) + toward * share) for part, toward in zip(rgb(colour), rgb(other))]
    return "#" + "".join(f"{part:02X}" for part in mixed)


def _lightness(colour: str) -> float:
    channels = [part / 255 for part in rgb(colour)]
    return sum(weight * (part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4) for weight, part in zip((0.2126, 0.7152, 0.0722), channels))


def contrast(one: str, other: str) -> float:
    # The web's measure of how well two colours read against each other, from 1 to 21.
    light, dark = sorted((_lightness(one), _lightness(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def figure_text(value: float) -> str:
    # Written so that numbers_in reads it back as the number it was given: digits, with commas between the thousands.
    text = f"{Decimal(format(value, '.15g')):,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
