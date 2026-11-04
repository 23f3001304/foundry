"""MCP tool for maker agents: builds a slide deck whose colours, fonts, logo and layout come from the brand kit."""

import re
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
from foundry.checks import figure
from foundry.tools.layout import LINE_SPACING, MakerError, fit_size, load_font, wrap

mcp = MCPServer("foundry-deck")

WIDTH, HEIGHT = 960, 540
TITLE_ONLY = 5
BULLET_GAP = 16
MOST_TABLE_COLUMNS = 8
# A table's words are sized to the largest of these that lets the whole table fit, and a cell keeps this much room around its words.
TABLE_SIZES = (20, 9)
CELL_PAD = 6
# A little more than the padding, because PowerPoint sets a word slightly wider than the measure here does.
WORD_SLACK = 4
RULE_WIDTH = 9525
PICTURE_KINDS = (".png", ".jpg", ".jpeg")
ROWS_SHAPE = 'A table\'s "rows" is a list of rows, and each row is a list of cells. The first row holds the headings.'
TABLE_TOO_BIG = "This table is too big to fit on one slide. Show fewer rows, shorten the words, or split it over two slides."
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
# The small line under a slide's content that says where its numbers came from. It stops short of the corner logo.
SOURCE_BOX = (56, 500, 780, 28)
NARROW_SOURCE_BOX = (56, 500, 580, 28)
SOURCE_SIZES = (11, 7)
SOURCE_SHAPE = 'Each source is {"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 UTC"}.'


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


def _colour(brand: Brand, name: str) -> RGBColor:
    return RGBColor.from_string(brand.colors[name].removeprefix("#"))


def _new_slide(deck: Presentation, brand: Brand, background: str):
    slide = deck.slides.add_slide(deck.slide_layouts[TITLE_ONLY])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _colour(brand, background)
    return slide


def _block(slide, brand: Brand, colour: str, left: int, top: int, width: int, height: int) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(left), Pt(top), Pt(width), Pt(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _colour(brand, colour)
    shape.line.fill.background()
    # Behind the text, which was placed first.
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2, shape._element)


def _mark(run, brand: Brand) -> None:
    run.font.color.rgb = _colour(brand, "ink")
    fill = run._r.find(f"{DRAWING}rPr/{DRAWING}solidFill")
    marker = etree.Element(f"{DRAWING}highlight")
    etree.SubElement(marker, f"{DRAWING}srgbClr", val=brand.colors["accent"].removeprefix("#"))
    fill.addnext(marker)


def _write(shape, brand: Brand, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, middle: bool = False, highlight: str = "") -> None:
    left, top, width, height = box
    shape.left, shape.top, shape.width, shape.height = Pt(left), Pt(top), Pt(width), Pt(height)
    frame = shape.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE if middle else MSO_ANCHOR.TOP
    size = fit_size("\n".join(paragraphs), brand.font_file(role), width, height - gap * len(paragraphs), largest, smallest)
    for index, text in enumerate(paragraphs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.LEFT
        paragraph.space_after = Pt(gap)
        for piece in re.split(f"({re.escape(highlight)})", text, maxsplit=1) if highlight else [text]:
            if not piece:
                continue
            run = paragraph.add_run()
            run.text = piece
            run.font.size = Pt(size)
            run.font.name = brand.fonts[role]
            run.font.color.rgb = _colour(brand, colour)
            if piece == highlight:
                _mark(run, brand)


def _text_box(slide, brand: Brand, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, highlight: str = "") -> None:
    shape = slide.shapes.add_textbox(*(Pt(value) for value in box))
    _write(shape, brand, role, colour, box, paragraphs, largest, smallest, gap, highlight=highlight)


def _corner_logo(slide, brand: Brand, on_paper: bool) -> None:
    if not on_paper:
        _block(slide, brand, "paper", 860, 440, 100, 100)
    slide.shapes.add_picture(str(brand.logo_path), Pt(872), Pt(452), width=Pt(76))


def _title_slide(deck: Presentation, brand: Brand, title: str, subtitle: str, highlight: str = "") -> None:
    _check_highlight(highlight, title)
    if brand.style == "solid":
        slide = _new_slide(deck, brand, "primary")
        _block(slide, brand, "paper", 680, 0, 280, HEIGHT)
        if not highlight:
            _block(slide, brand, "accent", 56, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(730), Pt(180), width=Pt(180))
        _write(slide.shapes.title, brand, "heading", "paper", (56, 150, 580, 230), [title], 54, 22, highlight=highlight)
        ink = "paper"
        subtitle_box = (56, 400, 580, 60)
    else:
        slide = _new_slide(deck, brand, "paper")
        _block(slide, brand, "primary", 0, 0, 48, HEIGHT)
        if not highlight:
            _block(slide, brand, "accent", 96, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(770), Pt(36), width=Pt(150))
        _write(slide.shapes.title, brand, "heading", "primary", (96, 150, 640, 230), [title], 54, 22, highlight=highlight)
        ink = "ink"
        subtitle_box = (96, 400, 640, 60)
    if subtitle:
        _text_box(slide, brand, "body", ink, subtitle_box, [subtitle], 24, 14)


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
    slide = _new_slide(deck, brand, "paper")
    if brand.style == "solid":
        _block(slide, brand, "primary", 0, 0, WIDTH, 110)
        _write(slide.shapes.title, brand, "heading", "paper", (56, 22, 848, 70), [title], 34, 16, middle=True, highlight=highlight)
        return slide, (56, 140, 790, 350)
    _block(slide, brand, "primary", 0, 0, 24, HEIGHT)
    _write(slide.shapes.title, brand, "heading", "primary", (72, 44, 780, 90), [title], 36, 16, highlight=highlight)
    return slide, (72, 150, 780, 340)


def _make_content(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "content")
    points = [f"• {point}" for point in _required(spec, "bullets", "content")]
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, title, *points)
    slide, box = _titled_slide(deck, brand, title, highlight)
    _text_box(slide, brand, "body", "ink", box, points, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, on_paper=True)


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
    for size in range(TABLE_SIZES[0], TABLE_SIZES[1] - 1, -1):
        widths = _column_widths(brand, cells, width, size)
        if widths is None:
            continue
        heights = [_row_height(brand, row, widths, size, header=number == 0) for number, row in enumerate(cells)]
        if sum(heights) <= height:
            return size, widths, heights
    raise MakerError(TABLE_TOO_BIG)


def _underline(cell, brand: Brand) -> None:
    # A thin line under a row in the text colour, because the accent is for the one thing that matters most on a slide. It goes first, ahead of the fill, which is where the file format wants it.
    line = etree.Element(f"{DRAWING}lnB", w=str(RULE_WIDTH))
    etree.SubElement(etree.SubElement(line, f"{DRAWING}solidFill"), f"{DRAWING}srgbClr", val=brand.colors["ink"].removeprefix("#"))
    cell._tc.get_or_add_tcPr().insert(0, line)


def _make_table(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "table")
    cells = _table_cells(spec)
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, title)
    slide, (left, top, width, height) = _titled_slide(deck, brand, title, highlight)
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
            cell.fill.fore_color.rgb = _colour(brand, "primary" if header else "paper")
            cell.margin_left = cell.margin_right = cell.margin_top = cell.margin_bottom = Pt(CELL_PAD)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.word_wrap = True
            paragraph = cell.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.RIGHT if figures[at] else PP_ALIGN.LEFT
            run = paragraph.add_run()
            run.text = text
            run.font.size = Pt(size)
            run.font.name = brand.fonts["heading" if header else "body"]
            run.font.color.rgb = _colour(brand, "paper" if header else "ink")
            if not header:
                _underline(cell, brand)
    _corner_logo(slide, brand, on_paper=True)


def _chart_record(path: Path) -> str:
    # What draw_chart wrote beside a chart: its title, labels and figures.
    try:
        return Path(f"{path}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _picture(path_text: str) -> tuple[Path, tuple[int, int]]:
    path = Path(path_text)
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
    slide, (left, top, width, height) = _titled_slide(deck, brand, title, highlight)
    # The whole picture, as large as the room allows, in the middle of it.
    scale = min(width / pixels_wide, height / pixels_high)
    wide, high = pixels_wide * scale, pixels_high * scale
    slide.shapes.add_picture(str(path), Pt(left + (width - wide) / 2), Pt(top), width=Pt(wide), height=Pt(high))
    _corner_logo(slide, brand, on_paper=True)
    # A chart is an image, so the words and figures it drew go in the notes, where the number check reads the deck's text.
    record = _chart_record(path)
    if record:
        slide.notes_slide.notes_text_frame.text = record


def _make_statement(deck: Presentation, brand: Brand, spec: dict) -> None:
    text = _required(spec, "text", "statement")
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, text)
    solid = brand.style == "solid"
    slide = _new_slide(deck, brand, "primary" if solid else "paper")
    if not highlight:
        _block(slide, brand, "accent", 96, 110, 96, 6)
    _write(slide.shapes.title, brand, "heading", "paper" if solid else "primary", (96, 130, 740, 290), [text], 60, 22, middle=True, highlight=highlight)
    _corner_logo(slide, brand, on_paper=not solid)


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
    # Over the brand's dark colour the words are paper, and elsewhere they are ink.
    solid = brand.style == "solid"
    colour = "paper" if solid and layout in ("title", "statement") else "ink"
    box = NARROW_SOURCE_BOX if solid and layout == "title" else SOURCE_BOX
    _text_box(slide, brand, "body", colour, box, [source_line(links)], *SOURCE_SIZES)


@mcp.tool()
def build_deck(brand_dir: str, title: str, slides: list[dict], out_path: str, highlight: str = "", sources: list[dict] | None = None, subtitle: str = "") -> str:
    """Build an on-brand .pptx and return its absolute path. The title slide comes first, from title, with subtitle as a smaller line under it when you give one,
    such as a line the brand kit wants on the first slide. Keep the title to its own words.

    Each slide is one of:
    {"layout": "content", "title": "...", "bullets": ["...", "..."]}
    {"layout": "statement", "text": "One big sentence."}
    {"layout": "title", "title": "...", "subtitle": "..."}
    {"layout": "table", "title": "...", "rows": [["Region", "Revenue"], ["North", "100"]]} where the first row is the headings, at most 8 columns, and the table must fit on the slide
    {"layout": "picture", "title": "...", "path": "/absolute/path/chart.png"} where the picture is a .png or .jpg, such as a chart draw_chart made, shown whole
    Any slide can also have "highlight": words on that slide to put on the brand's accent colour, for the one thing that matters most.
    highlight does the same for the title slide. Text that cannot fit raises an error. Shorten it or split the slide.

    Only when foundry-desk's message asks for sources, a slide can also have "sources": [{"value": "62%", "entry": 123, "label": "Team Lead B, 2026-11-04 18:12 UTC"}],
    one for each number or fact on that slide that came from a log entry. value is the words on the slide. entry is the number job_facts gave that entry.
    label is the name job_facts shows for that entry, a comma, and the date and time it shows, written as in the example. The slide prints them as a small line, and the links are saved beside the deck.
    sources does the same for the title slide, which is all a one-slide deck has.
    """
    brand = load_brand_dir(brand_dir)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(WIDTH), Pt(HEIGHT)
    _apply_theme(deck, brand)
    _title_slide(deck, brand, title, subtitle, highlight)
    links = _sources_of({"title": title, "sources": sources}, 1)
    if links:
        _print_sources(deck.slides[-1], brand, links, "title")
    for number, spec in enumerate(slides, start=2):
        layout = LAYOUTS.get(spec.get("layout"))
        if layout is None:
            raise MakerError(f"Unknown layout {spec.get('layout')!r}. Use one of: {', '.join(LAYOUTS)}.")
        given = _sources_of(spec, number)
        layout(deck, brand, spec)
        if given:
            _print_sources(deck.slides[-1], brand, given, spec["layout"])
            links += given
    path = Path(out_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))
    write_links(path, links)
    return str(path)


if __name__ == "__main__":
    mcp.run()
