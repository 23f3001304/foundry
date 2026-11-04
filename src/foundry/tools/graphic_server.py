"""MCP tool for maker agents: renders a graphic whose colours, fonts, logo and picture come from the brand kit."""

import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from PIL import Image, ImageDraw, ImageFont, ImageOps

from foundry.brand import Brand, load_brand_dir
from foundry.tools.layout import LINE_SPACING, fit_size, load_font, rgb, wrap

mcp = MCPServer("foundry-visual")

SIZE = re.compile(r"(\d{3,4})x(\d{3,4})")
SMALLEST_SIDE, LARGEST_SIDE = 200, 7100
MOST_OF_THE_HEIGHT_FOR_THE_PICTURE = 0.6
UNDRAWABLE = "\U0010FFFF"


def _parse_size(size: str) -> tuple[int, int]:
    match = SIZE.fullmatch(size)
    sides = tuple(int(side) for side in match.groups()) if match else ()
    if len(sides) != 2 or not all(SMALLEST_SIDE <= side <= LARGEST_SIDE for side in sides):
        raise ValueError(f"The size must be WIDTHxHEIGHT between {SMALLEST_SIDE} and {LARGEST_SIDE}, like 1080x1080, not {size!r}.")
    return sides


def _check_font_can_draw(text: str, font: ImageFont.FreeTypeFont, role: str) -> None:
    # A font draws the same empty box for every letter it lacks. Refuse rather than ship boxes.
    box = bytes(font.getmask(UNDRAWABLE))
    missing = sorted({letter for letter in text if not letter.isspace() and bytes(font.getmask(letter)) == box})
    if missing:
        raise ValueError(f"The brand's {role} font cannot draw: {' '.join(missing[:10])}. Write this text in a script the font has.")


def _draw_text(draw: ImageDraw.ImageDraw, text: str, font_path: Path | None, role: str, colour: tuple, box: tuple[int, int, int, int], largest: int, smallest: int, highlight: str = "", marker: tuple = (), marked_colour: tuple = ()) -> int:
    left, top, right, bottom = box
    size = fit_size(text, font_path, right - left, bottom - top, largest, smallest)
    font = load_font(font_path, size)
    _check_font_can_draw(text, font, role)
    lines = wrap(text, font, right - left)
    start = " ".join(lines).find(highlight) if highlight else -1
    end, offset = start + len(highlight), 0
    for number, line in enumerate(lines):
        y = top + number * size * LINE_SPACING
        first, last = max(start - offset, 0), min(end - offset, len(line))
        if start >= 0 and first < last:
            _draw_marked(draw, font, line, (left, y), size, first, last, colour, marker, marked_colour)
        else:
            draw.text((left, y), line, font=font, fill=colour)
        offset += len(line) + 1
    return top + int(len(lines) * size * LINE_SPACING)


def _draw_marked(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, line: str, at: tuple[int, float], size: int, first: int, last: int, colour: tuple, marker: tuple, marked_colour: tuple) -> None:
    left, y = at
    start_x, end_x = left + font.getlength(line[:first]), left + font.getlength(line[:last])
    pad = size * 0.08
    draw.rectangle((start_x - pad, y, end_x + pad, y + size * (LINE_SPACING - 0.02)), fill=marker)
    draw.text((left, y), line[:first], font=font, fill=colour)
    draw.text((start_x, y), line[first:last], font=font, fill=marked_colour)
    draw.text((end_x, y), line[last:], font=font, fill=colour)


@mcp.tool()
def render_graphic(brand_dir: str, headline: str, subline: str, size: str, out_path: str, highlight: str = "") -> str:
    """Render an on-brand .png and return its absolute path.

    size is WIDTHxHEIGHT, like 1080x1080 for a post, 1080x1920 for a story, 1200x630 for a link preview or 3508x4961 for an A3 print.
    highlight is words from the headline to put on the brand's accent colour. The graphic then uses the accent nowhere else.
    Text that cannot fit, or that the brand's fonts cannot draw, raises an error. Shorten or rewrite it.
    """
    if highlight and highlight not in headline:
        raise ValueError(f"The highlight must be words from the headline. {highlight!r} is not in {headline!r}.")
    width, height = _parse_size(size)
    brand = load_brand_dir(brand_dir)
    canvas = _compose(brand, headline, subline, width, height, highlight)
    path = Path(out_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return str(path)


def picture_height(width: int, height: int, picture_size: tuple[int, int]) -> int:
    # A tall graphic has room to show the whole picture. A square one needs the space for its words.
    if height <= width * 1.2:
        return height // 2
    return min(round(width * picture_size[1] / picture_size[0]), int(height * MOST_OF_THE_HEIGHT_FOR_THE_PICTURE))


def _compose(brand: Brand, headline: str, subline: str, width: int, height: int, highlight: str = "") -> Image.Image:
    solid = brand.style == "solid"
    background = rgb(brand.colors["primary" if solid else "paper"])
    heading_colour = rgb(brand.colors["paper" if solid else "primary"])
    body_colour = rgb(brand.colors["paper" if solid else "ink"])
    paper = rgb(brand.colors["paper"])
    accent = rgb(brand.colors["accent"])
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    unit = min(width, height)
    margin, rule, logo_side = int(unit * 0.06), max(4, int(unit * 0.012)), int(unit * 0.16)
    wide = width > height * 1.2
    hero_path = brand.logo_path.parent / "hero.png"
    hero = Image.open(hero_path).convert("RGB") if hero_path.exists() else None
    band = picture_height(width, height, hero.size) if hero else height // 2
    picture_box = (width // 2, 0, width, height) if wide else (0, 0, width, band)
    text_left, text_top = (0, 0) if wide else (0, band)
    text_right = width // 2 if wide else width
    if hero:
        canvas.paste(ImageOps.fit(hero, (picture_box[2] - picture_box[0], picture_box[3] - picture_box[1])), picture_box[:2])
    if not highlight:
        strip = (picture_box[0] - rule, 0, picture_box[0], height) if wide else (0, picture_box[3], width, picture_box[3] + rule)
        draw.rectangle(strip, fill=accent)
    left, right, top = text_left + margin, text_right - margin, text_top + margin + rule
    logo_top = height - margin - logo_side
    space = logo_top - top - margin // 2
    headline_end = _draw_text(draw, headline, brand.font_file("heading"), "heading", heading_colour, (left, top, right, top + int(space * 0.72)), int(unit * 0.11), max(14, int(unit * 0.024)), highlight, accent, rgb(brand.colors["ink"]))
    if subline:
        _draw_text(draw, subline, brand.font_file("body"), "body", body_colour, (left, headline_end + margin // 3, right, logo_top - margin // 3), int(unit * 0.045), max(12, int(unit * 0.018)))
    logo_left = text_right - margin - logo_side
    if solid:
        pad = logo_side // 10
        draw.rounded_rectangle((logo_left - pad, logo_top - pad, logo_left + logo_side + pad, logo_top + logo_side + pad), radius=pad, fill=paper)
    logo = Image.open(brand.logo_path).convert("RGBA").resize((logo_side, logo_side), Image.LANCZOS)
    canvas.paste(logo, (logo_left, logo_top), logo)
    return canvas


if __name__ == "__main__":
    mcp.run()
