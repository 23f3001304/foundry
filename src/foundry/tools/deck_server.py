"""MCP tool for maker agents: builds a slide deck whose colours, fonts, logo and layout come from the brand kit."""

import io
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree
from mcp.server.mcpserver import MCPServer
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Pt

from foundry.brand import Brand, load_brand_dir
from foundry.chain import Link, source_line, write_links
from foundry.checks import FEWEST_PEERS, PERIOD, WRITTEN_DATE, carries, figure, numbers_in, outliers
from foundry.tools import compositions, confine, touchstone
from foundry.tools.layout import LINE_SPACING, NOT_RECEIVED, MakerError, contrast, figure_text, fit_size, load_font, mix, with_commas, words_of, wrap

mcp = MCPServer("foundry-deck")

WIDTH, HEIGHT = 960, 540
TITLE_ONLY = 5
BULLET_GAP = 16
MOST_TABLE_COLUMNS = 8
MOST_PROPERTY_CHARS = 255
# A table's words are sized to the largest of these that lets the whole table fit, and a cell keeps this much room around its words.
TABLE_SIZES = (20, 9)
CELL_PAD = 6
# Figures are the point of a table, so they are this much larger than its words, and the lit one larger again. With more than two columns of them there is no room, and they stay the size of the words.
FIGURE_SCALE, LIT_SCALE, MOST_FIGURE, MOST_LIT, MOST_LARGE_COLUMNS = 2.8, 1.3, 44, 56, 2
HEADING_SMALLER = 4
# Space between a figure and the words in the next column, because a figure lines up on its right.
FIGURE_GAP = 14
# Rows take up the room there is, to this height. A word this large or larger gets its whole line beside the title, or the table goes under the title where it is wider.
TALLEST_FIGURE_ROW, TALLEST_WORD_ROW, ONE_LINE_FROM = 88, 44, 13
SIDE_TITLE_WIDTH, SIDE_GAP, ABOVE_CORNER_LOGO = 322, 28, 444
NO_STYLE_NO_GRID = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
# A little more than the padding, because PowerPoint sets a word slightly wider than the measure here does.
WORD_SLACK = 4
RULE_WIDTH = 9525
PICTURE_KINDS = (".png", ".jpg", ".jpeg")
ROWS_SHAPE = 'A table\'s "rows" is a list of rows, and each row is a list of cells. The first row holds the headings.'
# A column under a heading like these holds years, which stay as written. A heading that only mentions a year, such as Revenue this year, holds figures.
YEARS_HEADING = re.compile(r"(?:(?:calendar|financial|fiscal)\s+)?(?:year|yr|fy|period)(?:\s+(?:ended|ending|end|founded))?|founded", re.IGNORECASE)
# What may follow a figure in a cell: words with no digit in them, such as USD m.
FIGURE_AND_UNIT = re.compile(r"(\S+)(?:\s+[^\d\s][^\d]*)?")
TABLE_TOO_TALL = "This table is too big to fit on one slide, because it is too tall. Show fewer rows, shorten the cells, or split it over two slides."
TABLE_TOO_WIDE = "This table is too big to fit on one slide, because it is too wide: its longest words do not fit side by side at the smallest size. Use fewer columns or shorter words."
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SLIDE_MARKUP = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
RELATIONSHIPS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
# The small line under a slide's content that says where its numbers came from. It stops short of the corner logo.
SOURCE_RIGHT, SOURCE_TOP, SOURCE_HEIGHT = 836, 500, 28
SOURCE_SIZES = (11, 7)
SOURCE_SHAPE = 'Each source is {"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 IST"}.'
SOLID, BAND, TOUCHSTONE = "solid", "band", "touchstone"
# Said on the slide beside a figure far from the others, so the reader does not take it for a mistake and does not have to find it themselves. The figure stays as it was given.
FAR_OFF = "{names}: far from the others. Shown as given."
# The accent is deepened only as far as it takes to read at this contrast, the web's measure for large type.
LIT_CONTRAST = 3
READ_CONTRAST = 4.5
# How far the words fade toward the ground for what is second on a slide, and how far the primary colour fades for a stroke that recedes.
SOFT_SHARE = 0.25
BACK_ON_DARK, BACK_ON_PAPER = 0.35, 0.65
BAND_WIDTH, COVER_BAND_WIDTH = 24, 48
SIDE_MARGINS = {SOLID: 56, BAND: 72, TOUCHSTONE: 48}
# On the stone: lit letters this large are filled with rubbed metal, because a picture does not read in small ones. Row lines are this share of the way from the ground to the words.
METAL_FROM, HAIR_SHARE = 40, 0.18
# The logo in the foot of a slide: its longer side and where it ends. It ends on the right margin, in the room between the end of the source line and the end of what a slide holds. On the stone it is small.
FOOT_LOGO_SIDE, FOOT_LOGO_BOTTOM = 60, 516
STONE_FOOT_LOGO_SIDE, STONE_FOOT_LOGO_BOTTOM = 36, 526
PLATE_PIXELS_PER_POINT = 4
COVER_LOGO_SIZE = 46
COVER_TITLE_LARGEST, COVER_LINE_SPACING, COVER_LINE_PITCH = 92, 0.9, 1.13
# A rub on the first slide follows the last line of the title when it has this much room, and has its own row when it does not. It runs off the edge of the slide.
RUB_NEEDS_ROOM, RUB_RUNS_ON = 240, 120
TITLE_TOP, TITLE_HEIGHT = 44, 90
# What a slide holds under its title ends here, above the source line and left of the corner logo.
BODY_TOP, BODY_BOTTOM, BODY_RIGHT = 150, 490, 850
NO_BREAK = "\u00a0"
# Slides with one figure lit. A plot ends at the foot of the body, so the source line under it is in the same place on every slide. Beyond ten strokes a row is too thin to read.
MOST_STROKES = 10
CHART_NEEDS = "A {layout} slide needs its labels and values, the same number of each, and it has {labels} labels and {values} values."
NOT_A_FIGURE = "{label}'s value must be a number, or null when nobody sent that figure. {value!r} is not."
NOT_A_NUMBER = "A big_number slide's number must be a figure, or null when nobody sent it. {value!r} is not."
NOTHING_TO_SHOW = "A big_number slide needs its number, or its labels and values."
NEGATIVE_STROKE = "A stroke cannot show {label}'s negative figure. Use draw_chart's bar kind and build_deck's picture layout for figures below zero."
TOO_MANY_STROKES = "A {layout} slide can show at most {most} figures, and this has {count}. Use a table for more."
NO_LABEL = "Every label on a chart needs its words."
FIGURE_TOO_WIDE = "This figure is too wide to fit on the slide: {figure}... Shorten it or its unit, say the rest in the caption, or use a table."
LABEL_TOO_LONG = "This label is too long to fit: {label}..."
WORDS_TOO_LONG = "These words are too long to fit: {words}... Shorten them."
HIGHLIGHT_A_LABEL = "On a {layout} slide the highlight must be one of the labels, which is the one that gets lit: {labels}. {highlight!r} is not."
NO_SOURCE_FOR_NOTHING = "A figure nobody sent has no source. Leave it out of sources."
NO_FIGURE_IN_SOURCE = "A source is for a figure, and {value!r} has none in it. Give the figure as it is on the slide, such as 1,980, and leave words out of sources."
# Where the foot of a figure sits in its text box, and how much of its size the digits stand above that, as a share of the size. The same for the kits' fonts within a point or two.
BASELINE_SHARE, DIGIT_SHARE = 0.9, 0.72
# A unit after a figure is this share of the figure's size.
UNIT_SHARE = 0.42
SIDE_RIGHT = 912
SMALL_WORDS = 14
LEAST_FIGURE = 11
# On a big-number slide the figure stands over the strokes, with the title and what it is to its right.
HERO_LARGEST, HERO_LEAST, ALONE_LARGEST = 172, 48, 200
BIG_COLUMN = 508
ROWS_HEIGHT, THICKEST_ROW, ROW_GAP_SHARE, ROW_FIGURE_LARGEST, LABEL_LARGEST, LABEL_LEAST, WIDEST_LABEL = 232, 44, 0.2, 29, 14, 9, 180
# On a chart slide the title is on the left and the strokes stand on the right, each this share of the room it has, with the figure over the lit one.
TALL_LEFT_WIDTH, TALL_GAP, TALL_FOOT, TALL_SHARE, THICKEST_TALL = 290, 40, 22, 0.54, 64
TALL_HERO_LARGEST, TALL_HERO_LEAST, TALL_FIGURE_LARGEST = 118, 40, 38
TOP_OF_FIGURES = 40


@dataclass(frozen=True)
class Look:
    """The colours of one slide, worked out from the kit and what the slide is on, so a layout never has to ask which style it is in."""

    ground: str
    title: str
    words: str
    # What is second on the slide: a heading over a column, a figure that is not the lit one.
    soft: str
    source: str
    # The accent, as it reads on this ground.
    lit: str
    # A stroke that recedes.
    back: str
    # The thin line under a table's row.
    line: str
    left: int
    # Where a plot ends on the right: clear of the corner logo.
    right: int
    # The width of the band of the primary colour down the left of a slide, if it has one.
    band: int


def _apply_theme(deck: Presentation, brand: Brand) -> None:
    # So that a person who edits the deck later still picks from the brand's colours and fonts. On a dark ground, text a person types has to be the light colour, which the theme's first pair decides.
    theme = deck.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme.blob)
    palette = root.find(f".//{DRAWING}clrScheme")
    first_pair = (("dk1", "ink"), ("lt1", "paper")) if brand.style == TOUCHSTONE else ()
    for slot, name in (("accent1", "primary"), ("accent2", "accent"), ("dk2", "ink"), ("lt2", "paper"), *first_pair):
        entry = palette.find(f"{DRAWING}{slot}")
        entry.clear()
        etree.SubElement(entry, f"{DRAWING}srgbClr", val=brand.colors[name].removeprefix("#"))
    root.find(f".//{DRAWING}majorFont/{DRAWING}latin").set("typeface", brand.fonts["heading"])
    root.find(f".//{DRAWING}minorFont/{DRAWING}latin").set("typeface", brand.fonts["body"])
    theme._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _rgb(colour: str) -> RGBColor:
    return RGBColor.from_string(colour.removeprefix("#"))


def _faded(words: str, ground: str) -> str:
    # The words moved toward the ground, no further than they can still be read.
    shares = (SOFT_SHARE * step / 5 for step in range(5, 0, -1))
    return next((mix(words, ground, share) for share in shares if contrast(mix(words, ground, share), ground) >= READ_CONTRAST), words)


def _readable(colour: str, ground: str, toward: str) -> str:
    # A colour that already reads on this ground is left as the kit has it. Otherwise it moves toward the words only as far as it needs to.
    return next((mix(colour, toward, step / 20) for step in range(21) if contrast(mix(colour, toward, step / 20), ground) >= LIT_CONTRAST), toward)


def _look(brand: Brand, loud: bool) -> Look:
    # Loud is a slide with one thing to say: the cover, a statement, a big number and a chart. A solid kit has those on its primary colour.
    colours = brand.colors
    dark = brand.style == SOLID and loud
    stone = brand.style == TOUCHSTONE
    ground, words = (colours["primary"], colours["paper"]) if dark else (colours["paper"], colours["ink"])
    return Look(
        ground=ground,
        title=words if dark or stone else colours["primary"],
        words=words,
        soft=_faded(words, ground),
        source=colours["primary"] if stone else words,
        lit=_readable(colours["accent"], ground, words),
        back=colours["primary"] if stone else mix(colours["primary"], colours["paper"], BACK_ON_DARK if dark else BACK_ON_PAPER),
        line=mix(colours["paper"], colours["ink"], HAIR_SHARE) if stone else colours["ink"],
        left=SIDE_MARGINS.get(brand.style, SIDE_MARGINS[BAND]),
        right=SIDE_RIGHT if stone else BODY_RIGHT,
        band=0 if brand.style in (SOLID, TOUCHSTONE) else BAND_WIDTH,
    )


def _new_slide(deck: Presentation, brand: Brand, look: Look, cover: bool = False) -> object:
    slide = deck.slides.add_slide(deck.slide_layouts[TITLE_ONLY])
    if brand.style == TOUCHSTONE:
        _stone_ground(slide, brand)
    else:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = _rgb(look.ground)
    if look.band:
        _block(slide, look.title, 0, 0, COVER_BAND_WIDTH if cover else look.band, HEIGHT)
    return slide


def _picture_fill(part, picture: bytes) -> etree._Element:
    # A fill made of a picture. Adding the same picture again reuses it, so a deck holds one stone however many slides it has.
    _, relation = part.get_or_add_image_part(io.BytesIO(picture))
    fill = etree.Element(f"{DRAWING}blipFill", dpi="0", rotWithShape="1")
    etree.SubElement(fill, f"{DRAWING}blip", {f"{RELATIONSHIPS}embed": relation})
    etree.SubElement(fill, f"{DRAWING}srcRect")
    etree.SubElement(etree.SubElement(fill, f"{DRAWING}stretch"), f"{DRAWING}fillRect")
    return fill


def _stone_ground(slide, brand: Brand) -> None:
    ground = etree.Element(f"{SLIDE_MARKUP}bg")
    properties = etree.SubElement(ground, f"{SLIDE_MARKUP}bgPr")
    properties.append(_picture_fill(slide.part, touchstone.stone(brand.colors["paper"])))
    etree.SubElement(properties, f"{DRAWING}effectLst")
    slide._element.find(f"{SLIDE_MARKUP}cSld").insert(0, ground)


def _paint(run, part, brand: Brand, look: Look, colour: str) -> None:
    # A run in its colour, once it has its size. Large lit letters on the stone are filled with rubbed metal. They stay real text, which a person can edit and the number check can read.
    run.font.color.rgb = _rgb(colour)
    if brand.style == TOUCHSTONE and colour == look.lit and run.font.size >= Pt(METAL_FROM):
        properties = run._r.get_or_add_rPr()
        properties.replace(properties.find(f"{DRAWING}solidFill"), _picture_fill(part, touchstone.metal_sheet(brand.colors["accent"])))


def _block(slide, colour: str, left: int, top: int, width: int, height: int) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(left), Pt(top), Pt(width), Pt(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(colour)
    shape.line.fill.background()
    # Behind the text, which was placed first.
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2, shape._element)


def _periods_together(text: str) -> str:
    # A quarter such as Q2 FY27 is one thing, so a line never breaks inside it.
    return PERIOD.sub(lambda found: found.group().replace(" ", NO_BREAK), text)


def _write(shape, brand: Brand, look: Look, role: str, colour: str, box: tuple[float, float, float, float], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, middle: bool = False, highlight: str = "", align: PP_ALIGN = PP_ALIGN.LEFT) -> None:
    left, top, width, height = box
    shape.left, shape.top, shape.width, shape.height = Pt(left), Pt(top), Pt(width), Pt(height)
    frame = shape.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE if middle else MSO_ANCHOR.TOP
    size = fit_size("\n".join(paragraphs), brand.font_file(role), width, height - gap * len(paragraphs), largest, smallest)
    lit = _periods_together(highlight)
    for index, text in enumerate(paragraphs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.space_after = Pt(gap)
        for piece in re.split(f"({re.escape(lit)})", text, maxsplit=1) if lit else [text]:
            if not piece:
                continue
            run = paragraph.add_run()
            run.text = piece
            run.font.size = Pt(size)
            run.font.name = brand.fonts[role]
            _paint(run, shape.part, brand, look, look.lit if piece == lit else colour)


def _text_box(slide, brand: Brand, look: Look, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, highlight: str = "") -> None:
    shape = slide.shapes.add_textbox(*(Pt(value) for value in box))
    _write(shape, brand, look, role, colour, box, paragraphs, largest, smallest, gap, highlight=highlight)


def _title(slide, brand: Brand, look: Look, box: tuple[int, int, int, int], text: str, largest: int, smallest: int, middle: bool = False, highlight: str = "") -> None:
    _write(slide.shapes.title, brand, look, "heading", look.title, box, [_periods_together(text)], largest, smallest, middle=middle, highlight=highlight)


def _logo_picture(slide, brand: Brand, ground: str, side: int, right: int, bottom: int) -> None:
    # What the logo draws ends on this right and bottom. It goes straight on the ground in whichever version reads there, and only with neither on a plate following its outline, so a client's logo is never recoloured.
    if not brand.has_logo:
        return
    path, plated = compositions.logo_for(brand, ground)
    if plated:
        art = compositions.plated_logo(brand, side * PLATE_PIXELS_PER_POINT)
        art = art.crop(compositions.ink_box(art))
        picture_file = io.BytesIO()
        art.save(picture_file, "PNG")
        picture = slide.shapes.add_picture(picture_file, 0, 0)
        wide, high = art.size
    else:
        picture = slide.shapes.add_picture(str(path), 0, 0)
        with Image.open(path) as logo:
            art = logo.convert("RGBA")
        left, top, ends, foot = compositions.ink_box(art)
        picture.crop_left, picture.crop_top = left / art.width, top / art.height
        picture.crop_right, picture.crop_bottom = 1 - ends / art.width, 1 - foot / art.height
        wide, high = ends - left, foot - top
    scale = side / max(wide, high)
    picture.width, picture.height = Pt(wide * scale), Pt(high * scale)
    picture.left, picture.top = Pt(right) - picture.width, Pt(bottom) - picture.height
    picture.name = "Logo"


def _corner_logo(slide, brand: Brand, look: Look) -> None:
    side, bottom = (STONE_FOOT_LOGO_SIDE, STONE_FOOT_LOGO_BOTTOM) if brand.style == TOUCHSTONE else (FOOT_LOGO_SIDE, FOOT_LOGO_BOTTOM)
    _logo_picture(slide, brand, look.ground, side, SIDE_RIGHT, bottom)


def _accent_rule(slide, brand: Brand, left: int, top: int) -> None:
    # The short mark over a slide that has nothing lit, so the accent is still on it once.
    if brand.style == TOUCHSTONE:
        picture, pad = touchstone.rub(96, 7, brand.colors["accent"], True, False, "rule")
        slide.shapes.add_picture(io.BytesIO(picture), Pt(left - pad), Pt(top - pad), width=Pt(96 + 2 * pad), height=Pt(7 + 2 * pad))
    else:
        _block(slide, brand.colors["accent"], left, top, 96, 6)


def _stone_cover(deck: Presentation, brand: Brand, look: Look, title: str, subtitle: str, highlight: str) -> None:
    # The firm's mark and name at the top, the title large, and one rub of metal after its last line.
    slide = _new_slide(deck, brand, look)
    if brand.has_logo:
        slide.shapes.add_picture(str(brand.logo_path), Pt(look.left), Pt(34), width=Pt(COVER_LOGO_SIZE)).name = "Logo"
    _line(slide, brand, look, "body", look.soft, (look.left + COVER_LOGO_SIZE + 10, 34, 500, COVER_LOGO_SIZE), brand.name, 15, name="Firm")
    together = _periods_together(title)
    box = (look.left, 150, SIDE_RIGHT - look.left, 280)
    size = fit_size(together, brand.font_file("heading"), box[2], box[3], COVER_TITLE_LARGEST, 22)
    _title(slide, brand, look, box, title, size, size, highlight=highlight)
    for paragraph in slide.shapes.title.text_frame.paragraphs:
        paragraph.line_spacing = COVER_LINE_SPACING
    lines = wrap(together, _measured(brand.font_file("heading"), size), box[2])
    pitch = size * COVER_LINE_PITCH
    after = box[0] + _measured(brand.font_file("heading"), size).getlength(lines[-1]) + size * 0.28
    beside = WIDTH - after >= RUB_NEEDS_ROOM
    thick = size * 0.72 if beside else size * 0.4
    left, top = (after, box[1] + (len(lines) - 1) * pitch + size * 0.22) if beside else (box[0], box[1] + len(lines) * pitch + 6)
    length = WIDTH - left + RUB_RUNS_ON
    picture, pad = touchstone.cover_rub(round(length), round(thick), brand.colors["accent"])
    slide.shapes.add_picture(io.BytesIO(picture), Pt(left - pad), Pt(top - pad), width=Pt(round(length) + 2 * pad), height=Pt(round(thick) + 2 * pad)).name = "Rub of metal"
    if subtitle:
        _text_box(slide, brand, look, "body", look.soft, (look.left, 448, SOURCE_RIGHT - look.left, 40), [_periods_together(subtitle)], 21, 14)


def _title_slide(deck: Presentation, brand: Brand, title: str, subtitle: str, highlight: str = "") -> None:
    _check_highlight(highlight, title)
    look = _look(brand, loud=True)
    if brand.style == TOUCHSTONE:
        _stone_cover(deck, brand, look, title, subtitle, highlight)
        return
    if brand.style == SOLID:
        slide = _new_slide(deck, brand, look)
        if not highlight:
            _accent_rule(slide, brand, 56, 130)
        title_box, subtitle_box = (56, 150, 680, 230), (56, 400, 680, 60)
    else:
        slide = _new_slide(deck, brand, look, cover=True)
        if not highlight:
            _accent_rule(slide, brand, 96, 130)
        title_box, subtitle_box = (96, 150, 640, 230), (96, 400, 640, 60)
    _logo_picture(slide, brand, look.ground, 150, SIDE_RIGHT, 186)
    _title(slide, brand, look, title_box, title, 72, 22, highlight=highlight)
    if subtitle:
        _text_box(slide, brand, look, "body", look.words, subtitle_box, [_periods_together(subtitle)], 24, 14)


def _required(spec: dict, field: str, layout: str) -> str | list:
    if not spec.get(field):
        raise MakerError(f"A {layout} slide needs its {field}.")
    return spec[field]


def _check_highlight(highlight: str, *texts: str) -> None:
    lit = _periods_together(highlight)
    if lit and not any(lit in _periods_together(text) for text in texts):
        raise MakerError(f"The highlight must be words on the slide. {highlight!r} is not on it.")


def _words_of_field(spec: dict, field: str) -> str:
    # A field a slide may leave out, as words. A null is the same as leaving it out.
    given = spec.get(field)
    if given is None:
        return ""
    if not isinstance(given, str):
        raise MakerError(f"A slide's {field} must be words. {given!r} is not.")
    return given


def _make_title(deck: Presentation, brand: Brand, spec: dict) -> None:
    _title_slide(deck, brand, _required(spec, "title", "title"), spec.get("subtitle", ""), _words_of_field(spec, "highlight"))


def _titled_slide(deck: Presentation, brand: Brand, title: str, highlight: str) -> tuple:
    # The start of every slide that holds something under its title, and the box left for it: clear of the corner logo and the source line.
    look = _look(brand, loud=False)
    slide = _new_slide(deck, brand, look)
    _title(slide, brand, look, (look.left, TITLE_TOP, look.right - look.left, TITLE_HEIGHT), title, 36, 16, highlight=highlight)
    return slide, look, (look.left, BODY_TOP, look.right - look.left, BODY_BOTTOM - BODY_TOP)


def _make_content(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "content")
    points = [_periods_together(f"• {point}") for point in _required(spec, "bullets", "content")]
    highlight = _words_of_field(spec, "highlight")
    _check_highlight(highlight, title, *points)
    slide, look, box = _titled_slide(deck, brand, title, highlight)
    _text_box(slide, brand, look, "body", look.words, box, points, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, look)


def _one_slide(deck: Presentation, brand: Brand, title: str, subtitle: str, bullets: list[str], highlight: str) -> None:
    # A deck of one is a page someone reads, not a cover, so it is on the kit's paper like any slide that holds something.
    body = [_periods_together(text) for text in (*([subtitle] if subtitle else []), *(f"• {point}" for point in bullets))]
    _check_highlight(highlight, title, *body)
    slide, look, box = _titled_slide(deck, brand, title, highlight)
    if body:
        _text_box(slide, brand, look, "body", look.words, box, body, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, look)


def _cell_text(cell: object, as_written: bool = False) -> str:
    # A null is a figure nobody sent. It is said in words, so there is never a number in its place and never an empty cell that could be read as nothing.
    # A figure is written with its commas, so the number check reads 1,980 where it would take 1980 for a year. A heading or a year stays as written.
    if cell is None:
        return NOT_RECEIVED
    if as_written and isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    if not as_written and _is_figure(cell):
        return figure_text(cell)
    text = str(cell).strip()
    if text.casefold() == NOT_RECEIVED:
        return NOT_RECEIVED
    bare = not as_written and figure(text) is not None and text[0].isdigit() and text[-1].isdigit()
    return with_commas(text) if bare else text


def _cell_figure(text: str):
    # The figure a cell starts with, when all that follows it is its unit. A date, a period's name or words with a number in them, such as Office 1, hold none.
    whole = FIGURE_AND_UNIT.fullmatch(text)
    return figure(whole[1]) if whole and not WRITTEN_DATE.search(text) else None


def _written_rows(rows: list[list]) -> list[list[str]]:
    # What a table's cells say on the slide. In a column of figures, one with its unit after it gets its commas too. The first column names the rows.
    headings = [_cell_text(cell, as_written=True) for cell in rows[0]]
    years = {at for at, heading in enumerate(headings) if YEARS_HEADING.fullmatch(heading)}
    body = [[_cell_text(cell, at in years) for at, cell in enumerate(row)] for row in rows[1:]]
    for at in set(range(1, len(headings))) - years:
        given = [row[at] for row in body if at < len(row) and row[at] and row[at] != NOT_RECEIVED]
        if 2 * sum(_cell_figure(text) is not None for text in given) >= len(given):
            for row in body:
                if at < len(row) and _cell_figure(row[at]) is not None:
                    row[at] = with_commas(row[at])
    return [headings, *body]


def _table_cells(spec: dict) -> list[list[str]]:
    rows = _required(spec, "rows", "table")
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        raise MakerError(ROWS_SHAPE)
    if len(rows) < 2:
        raise MakerError("A table needs its headings and at least one row under them.")
    cells = [[_periods_together(text) for text in row] for row in _written_rows(rows)]
    columns = len(cells[0])
    if not columns:
        raise MakerError("A table needs at least one column.")
    if columns > MOST_TABLE_COLUMNS:
        raise MakerError(f"A table can have at most {MOST_TABLE_COLUMNS} columns, and this has {columns}.")
    for number, row in enumerate(cells[1:], start=2):
        if len(row) != columns:
            raise MakerError(f"Row {number} has {len(row)} cell{'' if len(row) == 1 else 's'}, and the headings have {columns}.")
    return cells


def _column_of_figures(cells: list[list[str]], at: int) -> bool:
    # Words saying a figure did not come, and a blank, say nothing about what the column holds.
    given = [row[at] for row in cells[1:] if row[at] and row[at] != NOT_RECEIVED]
    return bool(given) and all(figure(text) is not None for text in given)


def _lit_row(cells: list[list[str]], measure: int | None, highlight: str) -> int | None:
    # The row a highlight names. With no highlight, the largest figure in the column that matters. A highlight that is only in the title has lit the title, and the accent is for one thing.
    if highlight:
        return next((number for number, row in enumerate(cells) if number and any(highlight in text for text in row)), None)
    if measure is None:
        return None
    given = [(figure(row[measure]), number) for number, row in enumerate(cells) if number and figure(row[measure]) is not None]
    return max(given, key=lambda pair: pair[0])[1] if given else None


@dataclass(frozen=True)
class TableFit:
    size: int
    widths: list[float]
    heights: list[float]
    # The font's role and size of each cell.
    fonts: list[list[tuple[str, int]]]
    one_line: bool


@lru_cache(maxsize=256)
def _measured(path: Path | None, size: int):
    return load_font(path, size)


def _cell_fonts(cells: list[list[str]], figures: list[bool], lit: int | None, measure: int | None, size: int) -> list[list[tuple[str, int]]]:
    large = sum(figures[1:]) <= MOST_LARGE_COLUMNS
    plain = min(MOST_FIGURE, round(size * FIGURE_SCALE)) if large else size
    brightest = min(MOST_LIT, round(plain * LIT_SCALE)) if large else plain

    def font(number: int, at: int) -> tuple[str, int]:
        if number == 0:
            return "heading", max(TABLE_SIZES[1], size - HEADING_SMALLER)
        if figures[at] and at > 0 and figure(cells[number][at]) is not None:
            return "heading", brightest if number == lit and at == measure else plain
        return "body", size

    return [[font(number, at) for at in range(len(row))] for number, row in enumerate(cells)]


def _width_of(brand: Brand, font: tuple[str, int], text: str) -> float:
    return _measured(brand.font_file(font[0]), font[1]).getlength(text)


def _column_widths(brand: Brand, cells: list[list[str]], fonts: list[list[tuple[str, int]]], figures: list[bool], width: float) -> tuple[list[float], bool] | None:
    # Every column is at least as wide as its longest word, so no word is ever cut in two. A cell below the headings gets its whole line if the slide has room,
    # and a heading may wrap. None when the words alone are wider than the slide at this size.
    columns = range(len(cells[0]))
    pads = [2 * CELL_PAD + WORD_SLACK + (FIGURE_GAP if figures[at] and at < len(figures) - 1 else 0) for at in columns]
    narrowest = [max((_width_of(brand, fonts[number][at], word) for number, row in enumerate(cells) for word in words_of(row[at])), default=0) + pads[at] for at in columns]
    if sum(narrowest) > width:
        return None
    widest = [max(narrowest[at], max((_width_of(brand, fonts[number][at], cells[number][at]) for number in range(1, len(cells))), default=0) + pads[at]) for at in columns]
    if sum(widest) <= width:
        return [wide + (width - sum(widest)) * wide / sum(widest) for wide in widest], True
    wanted = [wide - least for wide, least in zip(widest, narrowest)]
    return [least + (width - sum(narrowest)) * extra / sum(wanted) for least, extra in zip(narrowest, wanted)], False


def _row_height(brand: Brand, row: list[str], fonts: list[tuple[str, int]], widths: list[float]) -> float:
    return max(len(wrap(text, _measured(brand.font_file(font[0]), font[1]), max(width - 2 * CELL_PAD, 10))) * font[1] * LINE_SPACING for text, font, width in zip(row, fonts, widths)) + 2 * CELL_PAD


def _fit_table(brand: Brand, cells: list[list[str]], figures: list[bool], lit: int | None, measure: int | None, width: float, height: float) -> tuple[TableFit | None, bool]:
    # The words are as large as they can be with the whole table in the room, and each column is wide enough for its words. A size that keeps every cell on one line is taken over a larger one that does not.
    fits, wide_enough = [], False
    for size in range(TABLE_SIZES[0], TABLE_SIZES[1] - 1, -1):
        fonts = _cell_fonts(cells, figures, lit, measure, size)
        columns = _column_widths(brand, cells, fonts, figures, width)
        if columns is None:
            continue
        wide_enough = True
        widths, one_line = columns
        heights = [_row_height(brand, row, row_fonts, widths) for row, row_fonts in zip(cells, fonts)]
        if sum(heights) <= height:
            fits.append(TableFit(size, widths, _with_room(heights, height, any(figures[1:])), fonts, one_line))
    return next((fit for fit in fits if fit.one_line and fit.size >= ONE_LINE_FROM), fits[0] if fits else None), wide_enough


def _with_room(heights: list[float], height: float, has_figures: bool) -> list[float]:
    # The rows under the headings share the room there is, all one height where they can be, up to the tallest a row should be, so a short table is not squeezed into the top of the slide.
    body, room = heights[1:], height - heights[0]
    even = min(TALLEST_FIGURE_ROW if has_figures else TALLEST_WORD_ROW, room / len(body))
    for _ in body:
        taller = [high for high in body if high > even]
        if len(taller) == len(body):
            break
        even = min(even, (room - sum(taller)) / (len(body) - len(taller)))
    return heights[:1] + [max(high, even) for high in body]


def _far_off(labels: list[str], *columns: list[str]) -> str:
    # What a slide says about a figure far from the others, or nothing when none is. Words such as not received are not figures, so they are not judged.
    names = [labels[place] for column in columns for place in outliers(column)]
    return FAR_OFF.format(names=" and ".join(dict.fromkeys(names))) if names else ""


def _table_flag(cells: list[list[str]]) -> str:
    # Any column with enough figures to judge one by the others. Words in it and a unit after a figure change nothing. A column of years is not judged, and the first column, which names the rows, only when no other column has figures.
    numbers = {at: [_cell_figure(row[at]) for row in cells[1:]] for at in range(len(cells[0])) if not YEARS_HEADING.fullmatch(cells[0][at])}
    judged = [at for at, column in numbers.items() if sum(number is not None for number in column) >= FEWEST_PEERS]
    return _far_off([row[0] for row in cells[1:]], *(["" if number is None else number for number in numbers[at]] for at in ([at for at in judged if at] or judged)))


def _underline(cell, look: Look) -> None:
    # A thin line under a row in the text colour, because the accent is for the one thing that matters most on a slide. It goes first, ahead of the fill, which is where the file format wants it.
    line = etree.Element(f"{DRAWING}lnB", w=str(RULE_WIDTH))
    etree.SubElement(etree.SubElement(line, f"{DRAWING}solidFill"), f"{DRAWING}srgbClr", val=look.line.removeprefix("#"))
    cell._tc.get_or_add_tcPr().insert(0, line)


def _cell_colour(look: Look, text: str, number: int, at: int, large: bool, lit: bool) -> str:
    if number == 0 or text == NOT_RECEIVED:
        return look.soft
    if lit:
        return look.lit
    return look.words if at == 0 or large else look.soft


def _set_table(slide, brand: Brand, look: Look, cells: list[list[str]], figures: list[bool], fit: TableFit, left: int, top: int, lit: int | None, measure: int | None, highlight: str) -> None:
    table = slide.shapes.add_table(len(cells), len(cells[0]), Pt(left), Pt(top), Pt(sum(fit.widths)), Pt(sum(fit.heights))).table
    table.first_row = table.horz_banding = False
    # So that every line and fill on the table is one chosen here, and a theme's own table style adds none.
    table._tbl.tblPr.find(f"{DRAWING}tableStyleId").text = NO_STYLE_NO_GRID
    for at, column_width in enumerate(fit.widths):
        table.columns[at].width = Pt(column_width)
    for number, row in enumerate(cells):
        table.rows[number].height = Pt(fit.heights[number])
        for at, text in enumerate(row):
            cell = table.cell(number, at)
            cell.fill.background()
            cell.margin_top = cell.margin_bottom = Pt(CELL_PAD)
            cell.margin_left = Pt(CELL_PAD if at else 0)
            cell.margin_right = Pt(CELL_PAD + (FIGURE_GAP if figures[at] and at < len(row) - 1 else 0))
            cell.vertical_anchor = MSO_ANCHOR.BOTTOM if number == 0 else MSO_ANCHOR.MIDDLE
            cell.text_frame.word_wrap = True
            paragraph = cell.text_frame.paragraphs[0]
            # A column of figures is lined up on its right, and so is its heading and any figure that did not come.
            paragraph.alignment = PP_ALIGN.RIGHT if figures[at] else PP_ALIGN.LEFT
            role, size = fit.fonts[number][at]
            on = number == lit and (at == measure or bool(highlight and highlight in text))
            run = paragraph.add_run()
            run.text = text
            run.font.size = Pt(size)
            run.font.name = brand.fonts[role]
            _paint(run, slide.part, brand, look, _cell_colour(look, text, number, at, role == "heading", on))
            _underline(cell, look)


def _make_table(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "table")
    cells = _table_cells(spec)
    highlight = _periods_together(_words_of_field(spec, "highlight"))
    _check_highlight(highlight, _periods_together(title), *(text for row in cells[1:] for text in row))
    figures = [_column_of_figures(cells, at) for at in range(len(cells[0]))]
    # The figure that matters is in the last column of figures, the newest in a table of periods, and never the first column, which names the rows.
    measure = next((at for at in reversed(range(1, len(figures))) if figures[at]), None)
    lit = _lit_row(cells, measure, highlight)
    lit_title = "" if lit is not None else highlight
    # Only where the figures have sources, because a menu's dearest dish is not an odd figure anyone has to answer for.
    flag = _table_flag(cells) if spec.get("sources") else ""
    look = _look(brand, loud=False)
    side_left = look.left + SIDE_TITLE_WIDTH + SIDE_GAP
    # Beside its title a table can run to the slide's right margin, above the corner logo unless the logo is down in the foot.
    side_bottom = BODY_BOTTOM if brand.style == TOUCHSTONE else ABOVE_CORNER_LOGO
    beside, _ = _fit_table(brand, cells, figures, lit, measure, SIDE_RIGHT - side_left, side_bottom - TITLE_TOP)
    if beside is not None and beside.one_line and beside.size >= ONE_LINE_FROM:
        slide = _new_slide(deck, brand, look)
        _title_and_words(slide, brand, look, (look.left, TITLE_TOP, SIDE_TITLE_WIDTH, BODY_BOTTOM), title, [(flag, look.words)] if flag else [], 34, lit_title)
        _set_table(slide, brand, look, cells, figures, beside, side_left, TITLE_TOP, lit, measure, highlight)
    else:
        slide, look, (left, top, width, height) = _titled_slide(deck, brand, title, lit_title)
        if flag:
            _text_box(slide, brand, look, "body", look.words, (left, top - 14, width, 22), [flag], 15, 9)
            top, height = top + 12, height - 12
        under, wide_enough = _fit_table(brand, cells, figures, lit, measure, width, height)
        if under is None:
            # Too tall when the words fit across the slide at some size and the rows still do not fit down it, and too wide when no size lets the words sit side by side.
            raise MakerError(TABLE_TOO_TALL if wide_enough else TABLE_TOO_WIDE)
        _set_table(slide, brand, look, cells, figures, under, left, top, lit, measure, highlight)
    _corner_logo(slide, brand, look)


def _chart_record(path: Path) -> str:
    # What draw_chart wrote beside a chart: its title, labels and figures. Only beside a picture the tool may show, so the words of one that is another client's are never read.
    try:
        return Path(f"{confine.picture(str(path))}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, MakerError):
        return ""


def _picture(path_text: str) -> tuple[Path, tuple[int, int]]:
    path = confine.picture(path_text)
    if not path.is_file():
        raise MakerError(f"There is no picture at {path_text}. Give the absolute path of a {' or '.join(PICTURE_KINDS)} file.")
    if path.suffix.lower() not in PICTURE_KINDS:
        raise MakerError(f"{path.name} is not a {' or '.join(PICTURE_KINDS)} file.")
    try:
        with Image.open(path) as image:
            return path, image.size
    except OSError as error:
        raise MakerError(f"{path.name} is not a picture I can read.") from error


def _make_picture(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "picture")
    path, (pixels_wide, pixels_high) = _picture(_required(spec, "path", "picture"))
    highlight = _words_of_field(spec, "highlight")
    _check_highlight(highlight, title)
    slide, look, (left, top, width, height) = _titled_slide(deck, brand, title, highlight)
    # The whole picture, as large as the room allows, in the middle of it.
    scale = min(width / pixels_wide, height / pixels_high)
    wide, high = pixels_wide * scale, pixels_high * scale
    slide.shapes.add_picture(str(path), Pt(left + (width - wide) / 2), Pt(top), width=Pt(wide), height=Pt(high))
    _corner_logo(slide, brand, look)
    # A chart is an image, so the words and figures it drew go in the notes, where the number check reads the deck's text.
    record = _chart_record(path)
    if record:
        slide.notes_slide.notes_text_frame.text = record


def _make_statement(deck: Presentation, brand: Brand, spec: dict) -> None:
    text = _required(spec, "text", "statement")
    highlight = _words_of_field(spec, "highlight")
    _check_highlight(highlight, text)
    look = _look(brand, loud=True)
    slide = _new_slide(deck, brand, look)
    if not highlight:
        _accent_rule(slide, brand, 96, 110)
    _title(slide, brand, look, (96, 130, 740, 290), text, 60, 22, middle=True, highlight=highlight)
    _corner_logo(slide, brand, look)


# Each point is itself, because two can have the same label: Q1 comes round again in a series over time.
@dataclass(frozen=True, eq=False)
class Point:
    label: str
    value: float | None
    # The figure as it is written, or the words saying it did not come.
    written: str
    unit: str

    @property
    def shown(self) -> str:
        return self.written + self.unit


def _chart_value(value: object, label: str) -> float | None:
    if value is None or (isinstance(value, str) and value.strip().casefold() == NOT_RECEIVED):
        return None
    if not _is_figure(value):
        raise MakerError(NOT_A_FIGURE.format(label=label, value=value))
    if value < 0:
        raise MakerError(NEGATIVE_STROKE.format(label=label))
    return value


def _points(spec: dict) -> list[Point]:
    # What a chart slide shows, in the order the maker gave it.
    layout, labels, values = spec["layout"], spec.get("labels"), spec.get("values")
    if not isinstance(labels, list) or not isinstance(values, list) or not labels or len(labels) != len(values):
        raise MakerError(CHART_NEEDS.format(layout=layout, labels=len(labels) if isinstance(labels, list) else 0, values=len(values) if isinstance(values, list) else 0))
    if len(labels) > MOST_STROKES:
        raise MakerError(TOO_MANY_STROKES.format(layout=layout, most=MOST_STROKES, count=len(labels)))
    points = []
    for label, value in zip(labels, values):
        if not isinstance(label, str) or not label.strip():
            raise MakerError(NO_LABEL)
        known = _chart_value(value, label)
        points.append(Point(label.strip(), known, NOT_RECEIVED if known is None else figure_text(known), "" if known is None else _words_of_field(spec, "unit")))
    return points


def _lit_point(points: list[Point], spec: dict) -> Point:
    highlight = _words_of_field(spec, "highlight")
    if highlight:
        lit = next((point for point in points if point.label == highlight), None)
        if lit is None:
            raise MakerError(HIGHLIGHT_A_LABEL.format(layout=spec["layout"], labels=", ".join(point.label for point in points), highlight=highlight))
        return lit
    return max(points, key=lambda point: -1 if point.value is None else point.value)


def _in_place(points: list[Point], spec: dict) -> list[Point]:
    # Largest first, so the eye runs down the order, and a figure that did not come after all that did. A series over time keeps its order.
    return points if spec.get("keep_order") else sorted(points, key=lambda point: (point.value is None, -(point.value or 0)))


def _shape_name(text: str) -> str:
    # A shape's name cannot hold a control character, though its text can.
    return "".join(character for character in text if character.isprintable())


def _line(slide, brand: Brand, look: Look, role: str, colour: str, box: tuple[float, float, float, float], text: str, size: float, unit: str = "", align: PP_ALIGN = PP_ALIGN.LEFT, anchor: MSO_ANCHOR = MSO_ANCHOR.MIDDLE, name: str = "", wraps: bool = False) -> None:
    # Real text at the size asked for, with a unit after a figure set smaller. It does not wrap unless asked, so a figure is never broken across two lines.
    shape = slide.shapes.add_textbox(*(Pt(value) for value in box))
    shape.name = _shape_name(name) or shape.name
    frame = shape.text_frame
    frame.word_wrap = wraps
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = anchor
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    for piece, piece_size in ((text, size), (unit, size * UNIT_SHARE)):
        if piece:
            run = paragraph.add_run()
            run.text = piece
            run.font.size = Pt(round(max(piece_size, 8)))
            run.font.name = brand.fonts[role]
            _paint(run, shape.part, brand, look, colour)


def _stroke(slide, brand: Brand, look: Look, label: str, box: tuple[float, float, float, float], lit: bool, upright: bool = False) -> None:
    # One figure's mark, exactly as long as the figure on the slide's one scale. A figure of nothing has no mark.
    left, top, width, height = box
    if width <= 0 or height <= 0:
        return
    if brand.style == TOUCHSTONE:
        length, thick = (height, width) if upright else (width, height)
        picture, pad = touchstone.rub(length, thick, brand.colors["accent"] if lit else look.back, lit, upright, f"{label}|{length}|{lit}")
        shape = slide.shapes.add_picture(io.BytesIO(picture), Pt(left - pad), Pt(top - pad), width=Pt(width + 2 * pad), height=Pt(height + 2 * pad))
    else:
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(left), Pt(top), Pt(width), Pt(height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(look.lit if lit else look.back)
        shape.line.fill.background()
        shape.shadow.inherit = False
    shape.name = _shape_name(f"{label} stroke")


def _shown_width(brand: Brand, point: Point, size: float) -> float:
    return _width_of(brand, ("heading", round(size)), point.written) + (_width_of(brand, ("heading", round(max(size * UNIT_SHARE, 8))), point.unit) if point.unit else 0)


def _size_to_fit(brand: Brand, point: Point, width: float, largest: int, least: int) -> int:
    size = next((size for size in range(largest, least - 1, -1) if _shown_width(brand, point, size) <= width), None)
    if size is None:
        raise MakerError(FIGURE_TOO_WIDE.format(figure=point.shown[:40]))
    return size


def _clear_of_stroke(size: int) -> float:
    # How far the foot of a large figure stands off the stroke under it. Generous, because where a font's digits stop in their box differs between fonts, and when PowerPoint has to substitute one.
    return size * 0.13


def _lit_figure(slide, brand: Brand, look: Look, point: Point, left: float, baseline: float, size: int) -> None:
    # The figure the slide is for, placed by the foot of its digits. Words saying it did not come are not lit, because there is nothing to light.
    colour = look.soft if point.value is None else look.lit
    top = baseline - BASELINE_SHARE * size
    _line(slide, brand, look, "heading", colour, (left, top, _shown_width(brand, point, size) + size * 0.1, size * 0.92), point.written, size, point.unit, anchor=MSO_ANCHOR.TOP, name="Lit figure")


def _title_and_words(slide, brand: Brand, look: Look, box: tuple[float, float, float, float], title: str, words: list[tuple[str, str]], largest: int, highlight: str = "") -> None:
    # A title with its smaller lines under it, the title taking whatever room they leave. Each is only as tall as it is measured to be, so nothing runs into what comes next.
    left, top, width, bottom = box
    # PowerPoint sets a line of small words slightly wider than the measure here does.
    heights = [len(wrap(text, _measured(brand.font_file("body"), SMALL_WORDS), width * 0.96)) * SMALL_WORDS * LINE_SPACING + 2 for text, _ in words]
    together = _periods_together(title)
    room = bottom - top - sum(heights) - 8 * len(heights)
    if room < 16 * LINE_SPACING:
        raise MakerError(WORDS_TOO_LONG.format(words=max((text for text, _ in words), key=len)[:40]))
    size = fit_size(together, brand.font_file("heading"), width, room, largest, 16)
    high = len(wrap(together, _measured(brand.font_file("heading"), size), width)) * size * LINE_SPACING + 2
    _title(slide, brand, look, (left, top, width, high), title, size, size, highlight=highlight)
    y = top + high + 8
    for (text, colour), height in zip(words, heights):
        _text_box(slide, brand, look, "body", colour, (left, y, width, height), [_periods_together(text)], SMALL_WORDS, SMALL_WORDS)
        y += height + 8


def _chart_words(look: Look, spec: dict, points: list[Point]) -> list[tuple[str, str]]:
    # What the chart is, and any figure far from the others, said in words on the slide.
    flag = _far_off([point.label for point in points], [point.written for point in points])
    caption = _words_of_field(spec, "caption")
    return [*([(caption, look.soft)] if caption else []), *([(flag, look.words)] if flag else [])]


def _make_big_number(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "big_number")
    if "labels" not in spec and "values" not in spec:
        if "number" not in spec or (isinstance(spec["number"], str) and not spec["number"].strip()):
            raise MakerError(NOTHING_TO_SHOW)
        _number_alone(deck, brand, spec, title)
    else:
        _number_over_strokes(deck, brand, spec, title)


def _written_number(number: str | float) -> str:
    # A number is always in a figure's place, so a year-shaped one gets its comma with or without words after it.
    return with_commas(number.strip()) if isinstance(number, str) else figure_text(number)


def _number_alone(deck: Presentation, brand: Brand, spec: dict, title: str) -> None:
    number = spec["number"]
    if not (number is None or isinstance(number, str) or _is_figure(number)):
        raise MakerError(NOT_A_NUMBER.format(value=number))
    missing = number is None or (isinstance(number, str) and number.strip().casefold() == NOT_RECEIVED)
    written = NOT_RECEIVED if missing else _written_number(number)
    look = _look(brand, loud=True)
    slide = _new_slide(deck, brand, look)
    _title(slide, brand, look, (look.left, TITLE_TOP, SIDE_RIGHT - look.left, TITLE_HEIGHT), title, 36, 16)
    point = Point("", None if missing else 1, written, "" if missing else _words_of_field(spec, "unit"))
    size = _size_to_fit(brand, point, look.right - look.left, ALONE_LARGEST, HERO_LEAST)
    _lit_figure(slide, brand, look, point, look.left, 360, size)
    caption = _words_of_field(spec, "caption")
    if caption:
        _text_box(slide, brand, look, "body", look.soft, (look.left, 390, look.right - look.left, 80), [_periods_together(caption)], 22, SMALL_WORDS)
    _corner_logo(slide, brand, look)


def _number_over_strokes(deck: Presentation, brand: Brand, spec: dict, title: str) -> None:
    given = _points(spec)
    lit = _lit_point(given, spec)
    points = _in_place(given, spec)
    look = _look(brand, loud=True)
    # Measured before anything is placed, so a label that cannot fit is refused with the reason.
    label_size = next((size for size in range(LABEL_LARGEST, LABEL_LEAST - 1, -1) if max(_width_of(brand, ("body", size), point.label) for point in points) <= WIDEST_LABEL), None)
    if label_size is None:
        raise MakerError(LABEL_TOO_LONG.format(label=max((point.label for point in points), key=len)[:40]))
    slide = _new_slide(deck, brand, look)
    rows = len(points)
    thick = min(THICKEST_ROW, ROWS_HEIGHT / (rows + (rows - 1) * ROW_GAP_SHARE))
    gap = thick * ROW_GAP_SHARE
    plot_top = BODY_BOTTOM - rows * thick - (rows - 1) * gap
    column = look.left + BIG_COLUMN
    _title_and_words(slide, brand, look, (column, TOP_OF_FIGURES - 4, SIDE_RIGHT - column, plot_top - 10), title, _chart_words(look, spec, given), 29)
    if any(point.value is not None for point in points):
        _line(slide, brand, look, "body", look.words, (look.left, TOP_OF_FIGURES - 4, column - look.left - 20, 22), lit.label, 15, name="Lit label")
    size = _size_to_fit(brand, lit, column - look.left - 24, 64 if lit.value is None else HERO_LARGEST, HERO_LEAST)
    _lit_figure(slide, brand, look, lit, look.left, plot_top - 44, size)
    plot_left = look.left + max(_width_of(brand, ("body", label_size), point.label) for point in points) + 14
    row_figure = max(LEAST_FIGURE, min(ROW_FIGURE_LARGEST, round(thick * 0.66)))
    # One scale for every stroke, as long as it can be with each figure still on the slide after its stroke.
    most = max((point.value for point in points if point.value), default=1)
    room = look.right - plot_left
    for point in points:
        if point is not lit and point.value is not None and _shown_width(brand, point, row_figure) >= room - 10:
            raise MakerError(FIGURE_TOO_WIDE.format(figure=point.shown[:40]))
    scale = min([room / most, *((room - 10 - _shown_width(brand, point, row_figure)) / point.value for point in points if point.value and point is not lit)])
    for at, point in enumerate(points):
        top = plot_top + at * (thick + gap)
        lit_row = point is lit and point.value is not None
        _line(slide, brand, look, "body", look.words if lit_row else look.soft, (look.left, top, plot_left - look.left - 6, thick), point.label, label_size, name=f"{point.label} label")
        length = (point.value or 0) * scale
        if point.value is not None:
            _stroke(slide, brand, look, point.label, (plot_left, top, length, thick), lit_row)
        if not lit_row:
            wide = _width_of(brand, ("heading", row_figure), NOT_RECEIVED) if point.value is None else _shown_width(brand, point, row_figure)
            _line(slide, brand, look, "heading", look.soft, (plot_left + length + (10 if point.value is not None else 0), top, wide + 6, thick), point.written, row_figure, point.unit, name=f"{point.label} figure")
    _corner_logo(slide, brand, look)


def _make_chart(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "chart")
    given = _points(spec)
    lit = _lit_point(given, spec)
    points = _in_place(given, spec)
    look = _look(brand, loud=True)
    slide = _new_slide(deck, brand, look)
    _title_and_words(slide, brand, look, (look.left, TITLE_TOP, TALL_LEFT_WIDTH, BODY_BOTTOM), title, _chart_words(look, spec, given), 34)
    plot_left = look.left + TALL_LEFT_WIDTH + TALL_GAP
    pitch = (look.right - plot_left) / len(points)
    thick = min(THICKEST_TALL, pitch * TALL_SHARE)
    base = BODY_BOTTOM - TALL_FOOT
    others = [point for point in points if point is not lit and point.value is not None]
    figure_size = min([TALL_FIGURE_LARGEST, *(_size_to_fit(brand, point, pitch - 12, TALL_FIGURE_LARGEST, LEAST_FIGURE) for point in others)])
    figure_high = figure_size * 1.15
    size = _size_to_fit(brand, lit, look.right - plot_left, 64 if lit.value is None else TALL_HERO_LARGEST, TALL_HERO_LEAST)
    lit_at = points.index(lit)
    place = [plot_left + at * pitch + (pitch - thick) / 2 for at in range(len(points))]
    wide = _shown_width(brand, lit, size)
    hero_left = max(plot_left, min(place[lit_at], look.right - wide))
    # The strokes under the lit figure's width have to leave room for it, and their own figures, under the top of the slide.
    under = [point for at, point in enumerate(points) if point in others and place[at] < hero_left + wide and place[at] + thick > hero_left]
    most = max((point.value for point in points if point.value), default=1)
    head_room = base - TOP_OF_FIGURES - DIGIT_SHARE * size
    limits = [base - TOP_OF_FIGURES, *((base - TOP_OF_FIGURES - figure_high) * most / point.value for point in others if point.value), *((head_room - figure_high - 4) * most / point.value for point in under if point.value)]
    if lit.value:
        limits.append((head_room - _clear_of_stroke(size)) * most / lit.value)
    tallest = min(limits)
    scale = tallest / most
    tops = {point: base - (point.value or 0) * scale for point in points}
    baseline = min([tops[lit] - _clear_of_stroke(size), *(tops[point] - figure_high - 4 for point in under)])
    _lit_figure(slide, brand, look, lit, hero_left, baseline, size)
    for at, point in enumerate(points):
        lit_one = point is lit and point.value is not None
        if point.value is not None:
            _stroke(slide, brand, look, point.label, (place[at], tops[point], thick, (point.value or 0) * scale), lit_one, upright=True)
        if point.value is None and point is not lit:
            _line(slide, brand, look, "heading", look.soft, (plot_left + at * pitch + 2, base - 44, pitch - 4, 44), point.written, 16, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM, name=f"{point.label} figure", wraps=True)
        elif point is not lit:
            _line(slide, brand, look, "heading", look.soft, (plot_left + at * pitch + 2, tops[point] - figure_high, pitch - 4, figure_high), point.written, figure_size, point.unit, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM, name=f"{point.label} figure")
        label_box = (plot_left + at * pitch + 1, base + 5, pitch - 2, BODY_BOTTOM - base - 5)
        shape = slide.shapes.add_textbox(*(Pt(value) for value in label_box))
        shape.name = _shape_name(f"{point.label} label")
        _write(shape, brand, look, "body", look.words if lit_one else look.soft, label_box, [point.label], LABEL_LARGEST, LABEL_LEAST, align=PP_ALIGN.CENTER)
    _corner_logo(slide, brand, look)


LOUD_LAYOUTS = ("title", "statement", "big_number", "chart")
LAYOUTS = {"title": _make_title, "content": _make_content, "statement": _make_statement, "table": _make_table, "picture": _make_picture, "big_number": _make_big_number, "chart": _make_chart}


def _source(item: object, slide: int, words: list[str]) -> Link:
    if not isinstance(item, dict):
        raise MakerError(SOURCE_SHAPE)
    value, entry, label = item.get("value"), item.get("entry"), item.get("label")
    if not isinstance(value, str) or not value.strip():
        raise MakerError(f'A source needs its "value", the number it is for. {SOURCE_SHAPE}')
    if isinstance(entry, bool) or not isinstance(entry, int):
        raise MakerError(f'A source needs its "entry", the whole number job_facts gave for it. {SOURCE_SHAPE}')
    if not isinstance(label, str) or not label.strip():
        raise MakerError(f'A source needs its "label", who gave it and when. {SOURCE_SHAPE}')
    if NOT_RECEIVED in value.casefold():
        raise MakerError(NO_SOURCE_FOR_NOTHING)
    if not numbers_in(value):
        raise MakerError(NO_FIGURE_IN_SOURCE.format(value=value))
    # However the figure is written, and as a whole figure, so 4 is not on a slide that says 4,730.
    if not carries("\n".join(word for word in words if isinstance(word, str)), value):
        raise MakerError(f"A source's value must be words on its slide. {value!r} is not on it.")
    return Link(slide, value, entry, label)


def _sources_of(spec: dict, slide: int) -> list[Link]:
    given = spec.get("sources") or []
    if not isinstance(given, list):
        raise MakerError(f'A slide\'s "sources" must be a list. {SOURCE_SHAPE}')
    words = [spec.get(key, "") for key in ("title", "subtitle", "text")] + list(spec.get("bullets", [])) + _data_words(spec)
    return [_source(item, slide, words) for item in given]


def _data_words(spec: dict) -> list[str]:
    # The words a table's cells and a chart's record put on their slide. Left alone when they are not shaped right, which the layout will say.
    if spec.get("layout") == "table" and isinstance(spec.get("rows"), list):
        rows = [row for row in spec["rows"] if isinstance(row, list)]
        return [text for row in _written_rows(rows) for text in row] if rows else []
    if spec.get("layout") == "picture" and isinstance(spec.get("path"), str):
        return _chart_record(Path(spec["path"])).splitlines()
    if spec.get("layout") in ("big_number", "chart"):
        return _chart_slide_words(spec)
    return []


def _is_figure(value: object) -> bool:
    # Any whole number is a figure, even one too long for a float to hold.
    return not isinstance(value, bool) and (isinstance(value, int) or (isinstance(value, float) and math.isfinite(value)))


def _chart_slide_words(spec: dict) -> list[str]:
    # The figures a chart slide writes, with and without its unit, and its words.
    values = spec["values"] if isinstance(spec.get("values"), list) else []
    written = [figure_text(value) for value in values if _is_figure(value)]
    # A number beside labels and values is not shown, so it is not on the slide.
    if "labels" not in spec and "values" not in spec and (_is_figure(spec.get("number")) or isinstance(spec.get("number"), str)):
        written.append(_written_number(spec["number"]))
    unit = spec.get("unit", "") if isinstance(spec.get("unit", ""), str) else ""
    labels = spec["labels"] if isinstance(spec.get("labels"), list) else []
    words = [*written, *(text + unit for text in written), *labels, spec.get("caption")]
    return [word for word in words if isinstance(word, str)]


def _print_sources(slide, brand: Brand, links: list[Link], layout: str) -> None:
    # In the same place on every slide, under whatever the slide holds. The line stays one string, because the number check knows it by those exact words.
    look = _look(brand, loud=layout in LOUD_LAYOUTS)
    box = (look.left, SOURCE_TOP, SOURCE_RIGHT - look.left, SOURCE_HEIGHT)
    _text_box(slide, brand, look, "body", look.source, box, [source_line(links)], *SOURCE_SIZES)


def _name_layout(deck: Presentation, layout: str) -> None:
    # A slide's name shows nowhere on it. check_design reads it, because a layout can't be told from where its shapes fell.
    deck.slides[-1]._element.cSld.set("name", layout)


@mcp.tool()
def build_deck(brand_dir: str, title: str, slides: list[dict], out_path: str, highlight: str = "", sources: list[dict] | None = None, subtitle: str = "", bullets: list[str] | None = None) -> str:
    """Build an on-brand .pptx and return its absolute path. The title slide comes first, from title, with subtitle as a smaller line under it when you give one,
    such as a line the brand kit wants on the first slide. Keep the title to its own words.

    For a deck of one slide, give no slides and put its points in bullets. It is then one content slide on the brand's paper, with title, subtitle and bullets on it.

    Each slide is one of:
    {"layout": "big_number", "title": "...", "caption": "What the figure is, with its unit", "labels": ["Office A", "Office B"], "values": [6420, null], "highlight": "Office A"}
    {"layout": "big_number", "title": "...", "number": "19,800", "caption": "What the figure is, with its unit"}
    {"layout": "chart", "title": "...", "caption": "What the figures are", "labels": ["Office A", "Office B"], "values": [18.62, 15.3], "unit": "%"}
    {"layout": "table", "title": "...", "rows": [["Region", "Revenue"], ["North", "100"]]} where the first row is the headings, at most 8 columns, and the table must fit on the slide
    {"layout": "content", "title": "...", "bullets": ["...", "..."]}
    {"layout": "statement", "text": "One big sentence."}
    {"layout": "title", "title": "...", "subtitle": "..."}
    {"layout": "picture", "title": "...", "path": "/absolute/path/chart.png"} where the picture is a .png or .jpg, shown whole

    When a slide is about figures, use these without being asked. big_number is for one figure that matters, shown very large, with the others as strokes under it, or alone.
    chart is for comparing figures, as upright strokes, with the one that matters over its own stroke. Give "keep_order": true for a series over time, which otherwise goes largest first.
    A table is for who gave what, or for more than one column of figures. It sets its figures large and lights one, the largest in its last column of figures, or the row a highlight names.
    draw_chart and the picture layout are for a chart with a figure below zero, which a stroke cannot show. draw_chart also delivers a chart on its own.

    In labels and values, at most 10 of each, a value is a number from calculate or job_facts, never your own sum. The slide writes it with commas, so give 6420, and unit goes after it, such as "%".
    The largest is lit, and on a chart slide highlight must be one of the labels if you want another lit.
    A value is null when nobody sent that figure, and so is a cell of a table's rows. The slide then says "not received", with no number and no stroke. Give it no source, and never fill in a figure.
    A figure far from the others is said on the slide in words by itself, such as "Office E: far from the others. Shown as given.", on these two layouts and on a table whose slide has sources and whose column holds at least three figures. A table on a slide with no sources does not say it, so say it in that slide's title. Do not leave the figure out or correct it.

    Any other slide can also have "highlight": words on that slide to light in the brand's accent colour, for the one thing that matters most. A slide with no highlight and nothing lit shows the accent as a short mark.
    highlight does the same for the title slide. Text that cannot fit raises an error. Shorten it or split the slide.

    Only when foundry-desk's message asks for sources, a slide can also have "sources": [{"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 IST"}],
    one for each number on that slide that came from a log entry. value is that number as it is on the slide, and a value with no figure in it is refused. entry is the number job_facts gave that entry.
    label is the name job_facts shows for that entry, a comma, and the date and time it shows, written as in the example. The slide prints them as a small line, and the links are saved beside the deck.
    sources does the same for the first slide, which is all a one-slide deck has.
    """
    highlight = highlight or ""
    if Path(out_path).suffix.lower() != ".pptx":
        raise MakerError(f"A deck is saved as a .pptx, so out_path must end in .pptx, not {Path(out_path).suffix!r}.")
    brand = load_brand_dir(brand_dir)
    # A client's own makers write only in their own folder, and show pictures only from it and the client's brand folder. Both are settled before any of the deck is built.
    path = confine.output(out_path)
    for spec in slides:
        if isinstance(spec, dict) and spec.get("layout") == "picture" and isinstance(spec.get("path"), str):
            confine.picture(spec["path"])
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(WIDTH), Pt(HEIGHT)
    _apply_theme(deck, brand)
    # The library's own author is a real person's name, which does not belong on a client's work. The file is the brand's.
    deck.core_properties.author = deck.core_properties.last_modified_by = brand.name[:MOST_PROPERTY_CHARS]
    # A file property holds at most 255 characters, and a title too long for that is the deck's own problem to say, which the slide's check does, so it is cut here and not refused.
    deck.core_properties.title = "".join(character for character in " ".join(title.split()) if character.isprintable())[:MOST_PROPERTY_CHARS]
    if slides and bullets:
        raise MakerError("bullets are for a deck of one slide. Put these on a slide of their own in slides.")
    if slides:
        _title_slide(deck, brand, title, subtitle, highlight)
        _name_layout(deck, "title")
    else:
        _one_slide(deck, brand, title, subtitle, bullets or [], highlight)
        _name_layout(deck, "content")
    links = _sources_of({"title": title, "subtitle": subtitle, "sources": sources} if slides else {"title": title, "subtitle": subtitle, "bullets": bullets or [], "sources": sources}, 1)
    if links:
        _print_sources(deck.slides[-1], brand, links, "title" if slides else "content")
    for number, spec in enumerate(slides, start=2):
        layout = LAYOUTS.get(spec.get("layout"))
        if layout is None:
            raise MakerError(f"Unknown layout {spec.get('layout')!r}. Use one of: {', '.join(LAYOUTS)}.")
        given = _sources_of(spec, number)
        layout(deck, brand, spec)
        _name_layout(deck, spec["layout"])
        if given:
            _print_sources(deck.slides[-1], brand, given, spec["layout"])
            links += given
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))
    write_links(path, links)
    return str(path)


if __name__ == "__main__":
    mcp.run()
