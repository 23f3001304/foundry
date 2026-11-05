"""MCP tool for maker agents: builds a slide deck whose colours, fonts, logo and layout come from the brand kit."""

import re
from dataclasses import dataclass
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
from foundry.checks import PERIOD, figure
from foundry.tools import confine
from foundry.tools.layout import LINE_SPACING, MakerError, contrast, fit_size, load_font, mix, wrap

mcp = MCPServer("foundry-deck")

WIDTH, HEIGHT = 960, 540
TITLE_ONLY = 5
BULLET_GAP = 16
MOST_TABLE_COLUMNS = 8
MOST_PROPERTY_CHARS = 255
# A table's words are sized to the largest of these that lets the whole table fit, and a cell keeps this much room around its words.
TABLE_SIZES = (20, 9)
CELL_PAD = 6
# A little more than the padding, because PowerPoint sets a word slightly wider than the measure here does.
WORD_SLACK = 4
RULE_WIDTH = 9525
PICTURE_KINDS = (".png", ".jpg", ".jpeg")
ROWS_SHAPE = 'A table\'s "rows" is a list of rows, and each row is a list of cells. The first row holds the headings.'
TABLE_TOO_TALL = "This table is too big to fit on one slide, because it is too tall. Show fewer rows, shorten the cells, or split it over two slides."
TABLE_TOO_WIDE = "This table is too big to fit on one slide, because it is too wide: its longest words do not fit side by side at the smallest size. Use fewer columns or shorter words."
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
# The small line under a slide's content that says where its numbers came from. It stops short of the corner logo.
SOURCE_RIGHT, SOURCE_TOP, SOURCE_HEIGHT = 836, 500, 28
NARROW_SOURCE_BOX = (56, 500, 580, 28)
SOURCE_SIZES = (11, 7)
SOURCE_SHAPE = 'Each source is {"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 IST"}.'
SOLID, BAND = "solid", "band"
# The accent is deepened only as far as it takes to read at this contrast, the web's measure for large type.
LIT_CONTRAST = 3
READ_CONTRAST = 4.5
# How far the words fade toward the ground for what is second on a slide, and how far the primary colour fades for a stroke that recedes.
SOFT_SHARE = 0.25
BACK_ON_DARK, BACK_ON_PAPER = 0.35, 0.65
BAND_WIDTH, COVER_BAND_WIDTH = 24, 48
SIDE_MARGINS = {SOLID: 56, BAND: 72}
TITLE_TOP, TITLE_HEIGHT = 44, 90
# What a slide holds under its title ends here, above the source line and left of the corner logo.
BODY_TOP, BODY_BOTTOM, BODY_RIGHT = 150, 490, 850
NO_BREAK = "\u00a0"


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
    # The width of the band of the primary colour down the left of a slide, if it has one.
    band: int


def _apply_theme(deck: Presentation, brand: Brand) -> None:
    # So that a person who edits the deck later still picks from the brand's colours and fonts.
    theme = deck.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme.blob)
    palette = root.find(f".//{DRAWING}clrScheme")
    for slot, name in (("accent1", "primary"), ("accent2", "accent"), ("dk2", "ink"), ("lt2", "paper")):
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
    ground, words = (colours["primary"], colours["paper"]) if dark else (colours["paper"], colours["ink"])
    return Look(
        ground=ground,
        title=words if dark else colours["primary"],
        words=words,
        soft=_faded(words, ground),
        source=words,
        lit=_readable(colours["accent"], ground, words),
        back=mix(colours["primary"], colours["paper"], BACK_ON_DARK if dark else BACK_ON_PAPER),
        line=colours["ink"],
        left=SIDE_MARGINS[SOLID if brand.style == SOLID else BAND],
        band=BAND_WIDTH if brand.style != SOLID else 0,
    )


def _new_slide(deck: Presentation, look: Look, cover: bool = False) -> object:
    slide = deck.slides.add_slide(deck.slide_layouts[TITLE_ONLY])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(look.ground)
    if look.band:
        _block(slide, look.title, 0, 0, COVER_BAND_WIDTH if cover else look.band, HEIGHT)
    return slide


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


def _write(shape, brand: Brand, look: Look, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, middle: bool = False, highlight: str = "") -> None:
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
        paragraph.alignment = PP_ALIGN.LEFT
        paragraph.space_after = Pt(gap)
        for piece in re.split(f"({re.escape(lit)})", text, maxsplit=1) if lit else [text]:
            if not piece:
                continue
            run = paragraph.add_run()
            run.text = piece
            run.font.size = Pt(size)
            run.font.name = brand.fonts[role]
            run.font.color.rgb = _rgb(look.lit if piece == lit else colour)


def _text_box(slide, brand: Brand, look: Look, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, highlight: str = "") -> None:
    shape = slide.shapes.add_textbox(*(Pt(value) for value in box))
    _write(shape, brand, look, role, colour, box, paragraphs, largest, smallest, gap, highlight=highlight)


def _title(slide, brand: Brand, look: Look, box: tuple[int, int, int, int], text: str, largest: int, smallest: int, middle: bool = False, highlight: str = "") -> None:
    _write(slide.shapes.title, brand, look, "heading", look.title, box, [_periods_together(text)], largest, smallest, middle=middle, highlight=highlight)


def _corner_logo(slide, brand: Brand, look: Look) -> None:
    # The logo goes on the paper colour, so on any other ground it brings a piece of paper with it.
    if look.ground != brand.colors["paper"]:
        _block(slide, brand.colors["paper"], 860, 440, 100, 100)
    slide.shapes.add_picture(str(brand.logo_path), Pt(872), Pt(452), width=Pt(76))


def _title_slide(deck: Presentation, brand: Brand, title: str, subtitle: str, highlight: str = "") -> None:
    _check_highlight(highlight, title)
    look = _look(brand, loud=True)
    accent = brand.colors["accent"]
    if brand.style == SOLID:
        slide = _new_slide(deck, look)
        _block(slide, brand.colors["paper"], 680, 0, 280, HEIGHT)
        if not highlight:
            _block(slide, accent, 56, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(730), Pt(180), width=Pt(180))
        title_box, subtitle_box = (56, 150, 580, 230), (56, 400, 580, 60)
    else:
        slide = _new_slide(deck, look, cover=True)
        if not highlight:
            _block(slide, accent, 96, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(770), Pt(36), width=Pt(150))
        title_box, subtitle_box = (96, 150, 640, 230), (96, 400, 640, 60)
    _title(slide, brand, look, title_box, title, 54, 22, highlight=highlight)
    if subtitle:
        _text_box(slide, brand, look, "body", look.words, subtitle_box, [_periods_together(subtitle)], 24, 14)


def _required(spec: dict, field: str, layout: str) -> str | list:
    if not spec.get(field):
        raise MakerError(f"A {layout} slide needs its {field}.")
    return spec[field]


def _check_highlight(highlight: str, *texts: str) -> None:
    if highlight and not any(highlight in text for text in texts):
        raise MakerError(f"The highlight must be words on the slide. {highlight!r} is not on it.")


def _make_title(deck: Presentation, brand: Brand, spec: dict) -> None:
    _title_slide(deck, brand, _required(spec, "title", "title"), spec.get("subtitle", ""), spec.get("highlight", ""))


def _titled_slide(deck: Presentation, brand: Brand, title: str, highlight: str) -> tuple:
    # The start of every slide that holds something under its title, and the box left for it: clear of the corner logo and the source line.
    look = _look(brand, loud=False)
    slide = _new_slide(deck, look)
    _title(slide, brand, look, (look.left, TITLE_TOP, BODY_RIGHT - look.left, TITLE_HEIGHT), title, 36, 16, highlight=highlight)
    return slide, look, (look.left, BODY_TOP, BODY_RIGHT - look.left, BODY_BOTTOM - BODY_TOP)


def _make_content(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "content")
    points = [f"• {point}" for point in _required(spec, "bullets", "content")]
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, title, *points)
    slide, look, box = _titled_slide(deck, brand, title, highlight)
    _text_box(slide, brand, look, "body", look.words, box, points, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, look)


def _one_slide(deck: Presentation, brand: Brand, title: str, subtitle: str, bullets: list[str], highlight: str) -> None:
    # A deck of one is a page someone reads, not a cover, so it is on the kit's paper like any slide that holds something.
    body = [*([subtitle] if subtitle else []), *(f"• {point}" for point in bullets)]
    _check_highlight(highlight, title, *body)
    slide, look, box = _titled_slide(deck, brand, title, highlight)
    if body:
        _text_box(slide, brand, look, "body", look.words, box, body, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, look)


def _cell_text(cell: object) -> str:
    if cell is None:
        return ""
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell).strip()


def _table_cells(spec: dict) -> list[list[str]]:
    rows = _required(spec, "rows", "table")
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        raise MakerError(ROWS_SHAPE)
    if len(rows) < 2:
        raise MakerError("A table needs its headings and at least one row under them.")
    cells = [[_cell_text(cell) for cell in row] for row in rows]
    columns = len(cells[0])
    if not columns:
        raise MakerError("A table needs at least one column.")
    if columns > MOST_TABLE_COLUMNS:
        raise MakerError(f"A table can have at most {MOST_TABLE_COLUMNS} columns, and this has {columns}.")
    for number, row in enumerate(cells[1:], start=2):
        if len(row) != columns:
            raise MakerError(f"Row {number} has {len(row)} cell{'' if len(row) == 1 else 's'}, and the headings have {columns}.")
    return cells


def _row_height(brand: Brand, row: list[str], widths: list[float], size: int, header: bool) -> float:
    font = load_font(brand.font_file("heading" if header else "body"), size)
    lines = max(len(wrap(text, font, max(width - 2 * CELL_PAD, 10))) for text, width in zip(row, widths))
    return lines * size * LINE_SPACING + 2 * CELL_PAD


def _column_widths(brand: Brand, cells: list[list[str]], width: int, size: int) -> list[float] | None:
    # Every column is at least as wide as its longest word, so no word is ever cut in two. A cell below the headings gets its whole line if the slide has room,
    # and a heading may wrap. None when the words alone are wider than the slide at this size.
    fonts = [load_font(brand.font_file("heading"), size)] + [load_font(brand.font_file("body"), size)] * (len(cells) - 1)
    pad = 2 * CELL_PAD + WORD_SLACK
    narrowest = [max((font.getlength(word) for row, font in zip(cells, fonts) for word in row[at].split()), default=0) + pad for at in range(len(cells[0]))]
    if sum(narrowest) > width:
        return None
    widest = [max(least, max((fonts[1].getlength(row[at]) for row in cells[1:]), default=0) + pad) for at, least in enumerate(narrowest)]
    if sum(widest) <= width:
        return [wide + (width - sum(widest)) * wide / sum(widest) for wide in widest]
    wanted = [wide - least for wide, least in zip(widest, narrowest)]
    return [least + (width - sum(narrowest)) * extra / sum(wanted) for least, extra in zip(narrowest, wanted)]


def _fit_table(brand: Brand, cells: list[list[str]], width: int, height: int) -> tuple[int, list[float], list[float]]:
    # The words are as large as they can be with the whole table on the slide, and each column is wide enough for its words.
    wide_enough = False
    for size in range(TABLE_SIZES[0], TABLE_SIZES[1] - 1, -1):
        widths = _column_widths(brand, cells, width, size)
        if widths is None:
            continue
        wide_enough = True
        heights = [_row_height(brand, row, widths, size, header=number == 0) for number, row in enumerate(cells)]
        if sum(heights) <= height:
            return size, widths, heights
    # Too tall when the words fit across the slide at some size and the rows still do not fit down it, and too wide when no size lets the words sit side by side.
    raise MakerError(TABLE_TOO_TALL if wide_enough else TABLE_TOO_WIDE)


def _underline(cell, look: Look) -> None:
    # A thin line under a row in the text colour, because the accent is for the one thing that matters most on a slide. It goes first, ahead of the fill, which is where the file format wants it.
    line = etree.Element(f"{DRAWING}lnB", w=str(RULE_WIDTH))
    etree.SubElement(etree.SubElement(line, f"{DRAWING}solidFill"), f"{DRAWING}srgbClr", val=look.line.removeprefix("#"))
    cell._tc.get_or_add_tcPr().insert(0, line)


def _make_table(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "table")
    cells = _table_cells(spec)
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, title)
    slide, look, (left, top, width, height) = _titled_slide(deck, brand, title, highlight)
    size, widths, heights = _fit_table(brand, cells, width, height)
    table = slide.shapes.add_table(len(cells), len(cells[0]), Pt(left), Pt(top), Pt(width), Pt(sum(heights))).table
    table.horz_banding = False
    for at, column_width in enumerate(widths):
        table.columns[at].width = Pt(column_width)
    # A column of figures is lined up on its right, and so is its heading.
    figures = [any(row[at] for row in cells[1:]) and all(figure(row[at]) is not None for row in cells[1:] if row[at]) for at in range(len(widths))]
    for number, row in enumerate(cells):
        header = number == 0
        table.rows[number].height = Pt(heights[number])
        for at, text in enumerate(row):
            cell = table.cell(number, at)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(look.title if header else look.ground)
            cell.margin_left = cell.margin_right = cell.margin_top = cell.margin_bottom = Pt(CELL_PAD)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.word_wrap = True
            paragraph = cell.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.RIGHT if figures[at] else PP_ALIGN.LEFT
            run = paragraph.add_run()
            run.text = text
            run.font.size = Pt(size)
            run.font.name = brand.fonts["heading" if header else "body"]
            run.font.color.rgb = _rgb(look.ground if header else look.words)
            if not header:
                _underline(cell, look)
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
    highlight = spec.get("highlight", "")
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
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, text)
    look = _look(brand, loud=True)
    slide = _new_slide(deck, look)
    if not highlight:
        _block(slide, brand.colors["accent"], 96, 110, 96, 6)
    _title(slide, brand, look, (96, 130, 740, 290), text, 60, 22, middle=True, highlight=highlight)
    _corner_logo(slide, brand, look)


LOUD_LAYOUTS = ("title", "statement")
LAYOUTS = {"title": _make_title, "content": _make_content, "statement": _make_statement, "table": _make_table, "picture": _make_picture}


def _source(item: object, slide: int, words: list[str]) -> Link:
    if not isinstance(item, dict):
        raise MakerError(SOURCE_SHAPE)
    value, entry, label = item.get("value"), item.get("entry"), item.get("label")
    if not isinstance(value, str) or not value.strip():
        raise MakerError(f'A source needs its "value", the words or number it is for. {SOURCE_SHAPE}')
    if isinstance(entry, bool) or not isinstance(entry, int):
        raise MakerError(f'A source needs its "entry", the whole number job_facts gave for it. {SOURCE_SHAPE}')
    if not isinstance(label, str) or not label.strip():
        raise MakerError(f'A source needs its "label", who gave it and when. {SOURCE_SHAPE}')
    if not any(value in text for text in words):
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
        return [_cell_text(cell) for row in spec["rows"] if isinstance(row, list) for cell in row]
    if spec.get("layout") == "picture" and isinstance(spec.get("path"), str):
        return _chart_record(Path(spec["path"])).splitlines()
    return []


def _print_sources(slide, brand: Brand, links: list[Link], layout: str) -> None:
    # In the same place on every slide, under whatever the slide holds. The line stays one string, because the number check knows it by those exact words.
    look = _look(brand, loud=layout in LOUD_LAYOUTS)
    box = NARROW_SOURCE_BOX if brand.style == SOLID and layout == "title" else (look.left, SOURCE_TOP, SOURCE_RIGHT - look.left, SOURCE_HEIGHT)
    _text_box(slide, brand, look, "body", look.source, box, [source_line(links)], *SOURCE_SIZES)


@mcp.tool()
def build_deck(brand_dir: str, title: str, slides: list[dict], out_path: str, highlight: str = "", sources: list[dict] | None = None, subtitle: str = "", bullets: list[str] | None = None) -> str:
    """Build an on-brand .pptx and return its absolute path. The title slide comes first, from title, with subtitle as a smaller line under it when you give one,
    such as a line the brand kit wants on the first slide. Keep the title to its own words.

    For a deck of one slide, give no slides and put its points in bullets. It is then one content slide on the brand's paper, with title, subtitle and bullets on it.

    Each slide is one of:
    {"layout": "content", "title": "...", "bullets": ["...", "..."]}
    {"layout": "statement", "text": "One big sentence."}
    {"layout": "title", "title": "...", "subtitle": "..."}
    {"layout": "table", "title": "...", "rows": [["Region", "Revenue"], ["North", "100"]]} where the first row is the headings, at most 8 columns, and the table must fit on the slide
    {"layout": "picture", "title": "...", "path": "/absolute/path/chart.png"} where the picture is a .png or .jpg, such as a chart draw_chart made, shown whole
    Any slide can also have "highlight": words on that slide to put on the brand's accent colour, for the one thing that matters most.
    highlight does the same for the title slide. Text that cannot fit raises an error. Shorten it or split the slide.

    Only when foundry-desk's message asks for sources, a slide can also have "sources": [{"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 IST"}],
    one for each number or fact on that slide that came from a log entry. value is the words on the slide. entry is the number job_facts gave that entry.
    label is the name job_facts shows for that entry, a comma, and the date and time it shows, written as in the example. The slide prints them as a small line, and the links are saved beside the deck.
    sources does the same for the first slide, which is all a one-slide deck has.
    """
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
    else:
        _one_slide(deck, brand, title, subtitle, bullets or [], highlight)
    links = _sources_of({"title": title, "subtitle": subtitle, "sources": sources} if slides else {"title": title, "subtitle": subtitle, "bullets": bullets or [], "sources": sources}, 1)
    if links:
        _print_sources(deck.slides[-1], brand, links, "title" if slides else "content")
    for number, spec in enumerate(slides, start=2):
        layout = LAYOUTS.get(spec.get("layout"))
        if layout is None:
            raise MakerError(f"Unknown layout {spec.get('layout')!r}. Use one of: {', '.join(LAYOUTS)}.")
        given = _sources_of(spec, number)
        layout(deck, brand, spec)
        if given:
            _print_sources(deck.slides[-1], brand, given, spec["layout"])
            links += given
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))
    write_links(path, links)
    return str(path)


if __name__ == "__main__":
    mcp.run()
