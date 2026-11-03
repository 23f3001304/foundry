"""Measures text with the brand's own font, so nothing spills off a slide or a graphic."""

from pathlib import Path

from PIL import ImageFont

LINE_SPACING = 1.2


def load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)


def wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
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
    raise ValueError(f"This text is too long to fit: {text[:60]}...")


def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[start:start + 2], 16) for start in (1, 3, 5))
