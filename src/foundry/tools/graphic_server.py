"""MCP tool for maker agents: renders a graphic whose colours, fonts, logo and picture come from the brand kit."""

import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from PIL import Image, ImageDraw, ImageFont, ImageOps

from foundry.brand import Brand, load_brand_dir
from foundry.tools import compositions, confine, design_check
from foundry.tools.compositions import heading_colour, margin_of, new_page, statement_colours  # noqa: F401
from foundry.tools.layout import LINE_SPACING, MakerError, check_font_can_draw, contrast, fit_size, load_font, rgb, wrap

mcp = MCPServer("foundry-visual")

SIZE = re.compile(r"(\d{3,4})x(\d{3,4})")
SMALLEST_SIDE, LARGEST_SIDE = 200, 7100
MOST_OF_THE_HEIGHT_FOR_THE_PICTURE = 0.6
# A tall page has room for larger words than a square one, and without them its lower half stands empty.
HEADLINE_SHARES, SUBLINE_SHARES = {False: 0.11, True: 0.15}, {False: 0.045, True: 0.055}
SPLIT, TYPE_LED, FULL_BLEED, STATEMENT = "split", "type_led", "full_bleed", "statement"
COMPOSITIONS = (SPLIT, TYPE_LED, FULL_BLEED, STATEMENT)
UNKNOWN_COMPOSITION = "There is no composition called {name!r}. Use one of: {names}."
NO_BRAND_PICTURE = "This brand has no picture of its own. Give a picture you drew as picture, or choose type_led or statement, which need none."
NO_PICTURE_THERE = "There is no picture at {name}. Give the absolute path of a .png or .jpg file."
NOT_A_PICTURE = "{name} is not a picture I can read."
HOLDS_NO_PICTURE = "The {name} composition holds no picture. Choose full_bleed or split to use one."


def _parse_size(size: str) -> tuple[int, int]:
    match = SIZE.fullmatch(size)
    sides = tuple(int(side) for side in match.groups()) if match else ()
    if len(sides) != 2 or not all(SMALLEST_SIDE <= side <= LARGEST_SIDE for side in sides):
        raise MakerError(f"The size must be WIDTHxHEIGHT between {SMALLEST_SIDE} and {LARGEST_SIDE}, like 1080x1080, not {size!r}.")
    return sides


def _hex(colour: tuple) -> str:
    return "#" + "".join(f"{part:02X}" for part in colour)


def _note(drawn: list[dict] | None, role: str, text: str, font: ImageFont.FreeTypeFont, size: int, x: float, y: float, colour: tuple) -> None:
    if drawn is not None and text.strip():
        ink = font.getbbox(text)
        drawn.append({"role": role, "words": text, "size": size, "box": [round(x + ink[0]), round(y + ink[1]), round(x + ink[2]), round(y + ink[3])], "colour": _hex(colour)})


def _draw_text(draw: ImageDraw.ImageDraw, text: str, font_path: Path | None, role: str, colour: tuple, box: tuple[int, int, int, int], largest: int, smallest: int, highlight: str = "", marker: tuple = (), marked_colour: tuple = (), drawn: list[dict] | None = None) -> int:
    left, top, right, bottom = box
    size = fit_size(text, font_path, right - left, bottom - top, largest, smallest)
    font = load_font(font_path, size)
    check_font_can_draw(text, font, role)
    lines = wrap(text, font, right - left)
    said = "headline" if role == "heading" else "subline"
    # Lines run to a like length, with no word alone on the last, and lit words stay together when they fit on a line.
    if len(text.splitlines()) == 1:
        lines = [line.replace(compositions.NO_BREAK, " ") for line in compositions.balanced_lines(text, font, right - left, len(lines), highlight) or lines]
    start = " ".join(lines).find(highlight) if highlight else -1
    end, offset = start + len(highlight), 0
    for number, line in enumerate(lines):
        y = top + number * size * LINE_SPACING
        first, last = max(start - offset, 0), min(end - offset, len(line))
        if start >= 0 and first < last:
            _draw_marked(draw, font, line, (left, y), size, first, last, colour, marker, marked_colour)
            _note(drawn, said, line[:first], font, size, left, y, colour)
            _note(drawn, "lit", line[first:last], font, size, left + font.getlength(line[:first]), y, marked_colour)
            _note(drawn, said, line[last:], font, size, left + font.getlength(line[:last]), y, colour)
        else:
            draw.text((left, y), line, font=font, fill=colour)
            _note(drawn, said, line, font, size, left, y, colour)
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


def _picture_given(text: str) -> Image.Image:
    path = confine.picture(text)
    if not path.is_file():
        raise MakerError(NO_PICTURE_THERE.format(name=Path(text).name))
    try:
        with Image.open(path) as picture:
            return picture.convert("RGB")
    except OSError as error:
        raise MakerError(NOT_A_PICTURE.format(name=path.name)) from error


def _brand_picture(brand: Brand) -> Image.Image | None:
    hero = brand.logo_path.parent / "hero.png"
    return Image.open(hero).convert("RGB") if hero.exists() else None


@mcp.tool()
def render_graphic(brand_dir: str, headline: str, subline: str, size: str, out_path: str, highlight: str = "", composition: str = SPLIT, picture: str = "") -> str:
    """Render an on-brand .png and return its absolute path.

    size is WIDTHxHEIGHT, like 1080x1080 for a post, 1080x1920 for a story, 1200x630 for a link preview or 3508x4961 for an A3 print.
    highlight is words from the headline to put on the brand's accent colour. The graphic then uses the accent nowhere else.
    composition is how the page is built, chosen for what the graphic has to do:
    type_led is a huge headline filling the page, with no picture, for one short idea that must stop a scroll. Keep the headline to a few words.
    full_bleed is a picture across the whole page, with the words and logo on a clean panel of the paper colour, when one strong picture carries it.
    statement is one big sentence on the brand's colour, for a plain announcement.
    split is a picture and the words side by side, and it is what you get when you choose nothing.
    picture is the absolute path of a picture you drew, for full_bleed or split, which otherwise use the brand's own. No word is ever drawn on a picture.
    A line break in the headline is kept. Text that cannot fit, or that the brand's fonts cannot draw, raises an error. Shorten or rewrite it.
    """
    if highlight and highlight not in headline:
        raise MakerError(f"The highlight must be words from the headline. {highlight!r} is not in {headline!r}.")
    if composition not in COMPOSITIONS:
        raise MakerError(UNKNOWN_COMPOSITION.format(name=composition, names=", ".join(COMPOSITIONS)))
    if picture and composition in (TYPE_LED, STATEMENT):
        raise MakerError(HOLDS_NO_PICTURE.format(name=composition))
    width, height = _parse_size(size)
    brand = load_brand_dir(brand_dir)
    # A client's own makers write only in their own folder, so this is settled before anything is drawn.
    path = confine.output(out_path)
    given = _picture_given(picture) if picture else None
    record = _made(brand, composition, headline, subline, width, height, highlight, given)
    canvas = record.pop("canvas")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    # The desk cannot read an image, so the words it drew go beside it for the number check.
    Path(f"{path}.txt").write_text("\n".join(text for text in (headline, subline) if text), encoding="utf-8")
    # What check_design measures, which can't be read back out of a picture.
    Path(design_check.RECORD.format(path=path)).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _made(brand: Brand, composition: str, headline: str, subline: str, width: int, height: int, highlight: str, picture: Image.Image | None) -> dict:
    said = {"composition": composition, "headline": headline, "subline": subline}
    if composition == SPLIT:
        drawn: list[dict] = []
        return {**said, "canvas": _compose(brand, headline, subline, width, height, highlight, picture, drawn), "drawn": drawn}
    ground = statement_colours(brand)[0] if composition == STATEMENT else brand.colors["paper"]
    page = new_page(brand, width, height, ground)
    if composition == FULL_BLEED:
        art = picture or _brand_picture(brand)
        if art is None:
            raise MakerError(NO_BRAND_PICTURE)
        compositions.full_bleed(page, headline, subline, highlight, art)
    else:
        {TYPE_LED: compositions.type_led, STATEMENT: compositions.statement}[composition](page, headline, subline, highlight)
    return {**said, "canvas": page.canvas, "drawn": page.drawn, "logo": page.logo, "panel": page.panel}


def picture_height(width: int, height: int, picture_size: tuple[int, int]) -> int:
    # A tall graphic has room to show the whole picture. A square one needs the space for its words.
    if height <= width * 1.2:
        return height // 2
    return min(round(width * picture_size[1] / picture_size[0]), int(height * MOST_OF_THE_HEIGHT_FOR_THE_PICTURE))


def _compose(brand: Brand, headline: str, subline: str, width: int, height: int, highlight: str = "", picture: Image.Image | None = None, drawn: list[dict] | None = None) -> Image.Image:
    solid = brand.style == "solid"
    background = rgb(brand.colors["primary" if solid else "paper"])
    # On the stone the ash is for what recedes, so a headline is in the colour of its words.
    heading = rgb(brand.colors["paper"] if solid else heading_colour(brand))
    body_colour = rgb(brand.colors["paper" if solid else "ink"])
    paper = rgb(brand.colors["paper"])
    accent = rgb(brand.colors["accent"])
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    unit = min(width, height)
    margin, rule, logo_side = int(unit * 0.06), max(4, int(unit * 0.012)), int(unit * 0.16)
    wide, tall = width > height * 1.2, height > width * 1.2
    hero = picture or _brand_picture(brand)
    band = picture_height(width, height, hero.size) if hero else height // 2
    picture_box = (width // 2, 0, width, height) if wide else (0, 0, width, band)
    text_left, text_top = (0, 0) if wide else (0, band)
    text_right = width // 2 if wide else width
    if hero:
        canvas.paste(ImageOps.fit(hero, (picture_box[2] - picture_box[0], picture_box[3] - picture_box[1])), picture_box[:2])
    # On the stone a picture of the kit's gold is on the page already, and the kit asks for gold once.
    if not highlight and not (hero and brand.style == "touchstone"):
        strip = (picture_box[0] - rule, 0, picture_box[0], height) if wide else (0, picture_box[3], width, picture_box[3] + rule)
        draw.rectangle(strip, fill=accent)
    left, right, top = text_left + margin, text_right - margin, text_top + margin + rule
    logo_top = height - margin - logo_side
    space = logo_top - top - margin // 2
    headline_end = _draw_text(draw, headline, brand.font_file("heading"), "heading", heading, (left, top, right, top + int(space * 0.72)), int(unit * HEADLINE_SHARES[tall]), max(14, int(unit * 0.024)), highlight, accent, rgb(max((brand.colors["ink"], brand.colors["paper"]), key=lambda words: contrast(words, brand.colors["accent"]))), drawn)
    if subline:
        _draw_text(draw, subline, brand.font_file("body"), "body", body_colour, (left, headline_end + margin // 3, right, logo_top - margin // 3), int(unit * SUBLINE_SHARES[tall]), max(12, int(unit * 0.018)), drawn=drawn)
    logo_left = text_right - margin - logo_side
    if solid:
        pad = logo_side // 10
        draw.rounded_rectangle((logo_left - pad, logo_top - pad, logo_left + logo_side + pad, logo_top + logo_side + pad), radius=pad, fill=paper)
    logo = Image.open(brand.logo_path).convert("RGBA").resize((logo_side, logo_side), Image.LANCZOS)
    canvas.paste(logo, (logo_left, logo_top), logo)
    return canvas


if __name__ == "__main__":
    mcp.run()
