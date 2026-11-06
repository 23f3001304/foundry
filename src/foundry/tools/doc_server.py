"""MCP tool for maker agents: writes a client's campaign copy as a branded PDF, and saves its words beside it for the number check."""

import logging
from pathlib import Path
from typing import NamedTuple

from matplotlib import rc_context
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle
from mcp.server.mcpserver import MCPServer
from PIL import Image

from foundry.brand import Brand, load_brand_dir
from foundry.tools import confine
from foundry.tools.image_server import images_on
from foundry.tools.layout import LINE_SPACING, MakerError, check_font_can_draw, fit_size, load_font, wrap

mcp = MCPServer("foundry-doc")
# The font subsetter says every table it prunes, at info level, and an MCP server's log is its controller's.
logging.getLogger("fontTools").setLevel(logging.WARNING)

# A4, in points. One point is one pixel here, so a line measured with the brand's font in Pillow is as wide as matplotlib draws it.
WIDTH, HEIGHT = 595.28, 841.89
MARGIN = 56
CONTENT_WIDTH = WIDTH - 2 * MARGIN
TITLE_SIZES, TITLE_HEIGHT = (30, 16), 90
HEADING_SIZE, BODY_SIZE, FOOTER_SIZE = 15, 11, 8.5
# A solid kit has its title in the paper colour on a band across the top of the first page, and a thin band on the pages after it. The others have a strip down the side.
SOLID_HEADER, SOLID_RUNNING_HEADER, STRIP = 150, 36, 18
HEADING_GAP, SECTION_GAP, PARAGRAPH_GAP = 4, 16, 0.6
# Under a heading, at least this many lines of its words stay on its page.
LINES_WITH_A_HEADING = 2
FIRST_PAGE_GAP, LATER_PAGE_TOP, LATER_RULE_TOP, FOOT = 26, 80, 52, 72
RULE_WIDTH, RULE_HEIGHT = 48, 4
LOGO_PIXELS = 256
MOST_PAGES = 12

SECTION_SHAPE = 'sections is a list of at least one section, and each section is {"heading": "...", "body": "..."}.'
NO_TITLE = "The copy needs a title."
NOT_A_PDF = "Written copy is saved as a .pdf, so out_path must end in .pdf, not {suffix!r}."
TOO_LONG = f"This copy is too long: it runs past {MOST_PAGES} pages. Shorten it or leave some out."
# Added by code when picture drawing is switched off, so a set that has no pictures says so in words. It holds no figures, so the number check has nothing to look for in it.
PICTURES = "Pictures"
NOT_DRAWN = "No pictures were drawn for this campaign set. Picture drawing is switched off, so the poster, the posts and the deck use only the brand's own logo and artwork."


class Item(NamedTuple):
    # "title", "heading" or "body" is a line of words. "rule" is the accent colour's short rule, which each page has once.
    kind: str
    text: str
    x: float
    # Where the line starts, in points down from the top of its page.
    top: float
    size: float


def _checked(sections: object) -> list[dict]:
    if not isinstance(sections, list) or not sections:
        raise MakerError(SECTION_SHAPE)
    for number, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise MakerError(f"Section {number} is {section!r}. {SECTION_SHAPE}")
        for field in ("heading", "body"):
            if not isinstance(section.get(field), str) or not section[field].strip():
                raise MakerError(f"Section {number} needs its {field}. {SECTION_SHAPE}")
    return sections


def _with_the_pictures_note(sections: list[dict]) -> list[dict]:
    # A maker who wrote its own pictures section, such as one saying a picture could not be drawn, is not given a second.
    if images_on() or any(section["heading"].strip().casefold() == PICTURES.casefold() for section in sections):
        return sections
    return [*sections, {"heading": PICTURES, "body": NOT_DRAWN}]


def _check_drawable(brand: Brand, title: str, sections: list[dict]) -> None:
    check_font_can_draw(" ".join([title, *(section["heading"] for section in sections)]), load_font(brand.font_file("heading"), 24), "heading")
    check_font_can_draw(" ".join(section["body"] for section in sections), load_font(brand.font_file("body"), 24), "body")


def pages_for(brand: Brand, title: str, sections: list[dict]) -> list[list[Item]]:
    """Every line of the copy, placed on its page. A heading never ends a page, and there are as many pages as the words take."""
    heading_path, body_path = brand.font_file("heading"), brand.font_file("body")
    heading_font, body_font = load_font(heading_path, HEADING_SIZE), load_font(body_path, BODY_SIZE)
    solid = brand.style == "solid"
    title_width = CONTENT_WIDTH - (100 if solid else 80)
    title_size = fit_size(title, heading_path, title_width, TITLE_HEIGHT, *TITLE_SIZES)
    title_lines = wrap(title, load_font(heading_path, title_size), title_width)
    title_top = 44 if solid else 52
    title_bottom = title_top + len(title_lines) * title_size * LINE_SPACING
    header_bottom = SOLID_HEADER if solid else title_bottom + 24
    rule_top = header_bottom + 8 if solid else header_bottom - 12
    first = [Item("title", line, MARGIN, title_top + number * title_size * LINE_SPACING, title_size) for number, line in enumerate(title_lines)]
    first.append(Item("rule", "", MARGIN, rule_top, 0))
    pages, page, top = [first], first, header_bottom + FIRST_PAGE_GAP
    bottom, line_height, heading_height = HEIGHT - FOOT, BODY_SIZE * LINE_SPACING, HEADING_SIZE * LINE_SPACING

    def next_page() -> None:
        nonlocal page, top
        page, top = [Item("rule", "", MARGIN, LATER_RULE_TOP, 0)], LATER_PAGE_TOP
        pages.append(page)

    for number, section in enumerate(sections):
        heading_lines = wrap(section["heading"].strip(), heading_font, CONTENT_WIDTH)
        body_lines = wrap(section["body"].strip(), body_font, CONTENT_WIDTH)
        if number:
            top += SECTION_GAP
        if top + len(heading_lines) * heading_height + HEADING_GAP + min(LINES_WITH_A_HEADING, len(body_lines)) * line_height > bottom:
            next_page()
        for line in heading_lines:
            page.append(Item("heading", line, MARGIN, top, HEADING_SIZE))
            top += heading_height
        top += HEADING_GAP
        for line in body_lines:
            if not line:
                # A blank line is the gap between two paragraphs, and a gap at the top of a page is dropped.
                top += 0 if top == LATER_PAGE_TOP else BODY_SIZE * PARAGRAPH_GAP
                continue
            if top + line_height > bottom:
                next_page()
            page.append(Item("body", line, MARGIN, top, BODY_SIZE))
            top += line_height
        if len(pages) > MOST_PAGES:
            raise MakerError(TOO_LONG)
    return pages


def _fraction(x: float, top: float, width: float, height: float) -> tuple[float, float, float, float]:
    # A box in points down from the page's top-left, as the figure's own units up from its bottom-left.
    return x / WIDTH, 1 - (top + height) / HEIGHT, width / WIDTH, height / HEIGHT


def _box(figure: Figure, colour: str, x: float, top: float, width: float, height: float) -> None:
    left, low, wide, high = _fraction(x, top, width, height)
    figure.add_artist(Rectangle((left, low), wide, high, transform=figure.transFigure, facecolor=colour, edgecolor="none"))


def _logo(figure: Figure, brand: Brand, x: float, top: float, side: float) -> None:
    if not brand.has_logo:
        return
    with Image.open(brand.logo_path) as logo:
        small = logo.convert("RGBA").resize((LOGO_PIXELS, LOGO_PIXELS), Image.LANCZOS)
    axes = figure.add_axes(_fraction(x, top, side, side))
    axes.imshow(small)
    axes.axis("off")
    # Above the tile it sits on, which is a figure's own shape and so is drawn after an axes unless the axes is raised.
    axes.set_zorder(2)


def _page(brand: Brand, number: int, items: list[Item]) -> Figure:
    colours, solid = brand.colors, brand.style == "solid"
    figure = Figure(figsize=(WIDTH / 72, HEIGHT / 72), dpi=72, facecolor=colours["paper"])
    if solid:
        _box(figure, colours["primary"], 0, 0, WIDTH, SOLID_HEADER if number == 1 else SOLID_RUNNING_HEADER)
    else:
        _box(figure, colours["primary"], 0, 0, STRIP, HEIGHT)
    if number == 1 and solid:
        # The logo sits on the paper, to the band's right, as it does on the other tools' solid pages.
        _box(figure, colours["paper"], WIDTH - MARGIN - 84, 33, 84, 84)
        _logo(figure, brand, WIDTH - MARGIN - 78, 39, 72)
    elif number == 1:
        _logo(figure, brand, WIDTH - MARGIN - 64, 44, 64)
    fonts = {"title": brand.font_file("heading"), "heading": brand.font_file("heading"), "body": brand.font_file("body")}
    paint = {"title": colours["paper"] if solid else colours["primary"], "heading": colours["primary"], "body": colours["ink"]}
    for item in items:
        if item.kind == "rule":
            _box(figure, colours["accent"], item.x, item.top, RULE_WIDTH, RULE_HEIGHT)
        else:
            figure.text(item.x / WIDTH, 1 - (item.top + item.size) / HEIGHT, item.text, fontproperties=FontProperties(fname=str(fonts[item.kind]), size=item.size), color=paint[item.kind], ha="left", va="baseline")
    foot = FontProperties(fname=str(brand.font_file("body")), size=FOOTER_SIZE)
    baseline = 1 - (HEIGHT - 40) / HEIGHT
    figure.text(MARGIN / WIDTH, baseline, brand.name, fontproperties=foot, color=colours["ink"], ha="left", va="baseline")
    figure.text((WIDTH - MARGIN) / WIDTH, baseline, f"Page {number}", fontproperties=foot, color=colours["ink"], ha="right", va="baseline")
    return figure


@mcp.tool()
def write_copy(brand_dir: str, title: str, sections: list[dict], out_path: str) -> str:
    """Write the campaign's copy as an on-brand .pdf and return its absolute path. The words are saved beside it.

    brand_dir is the brand folder named in the business pack. Its colours, fonts and logo are used, never your own taste.
    sections is a list, and each section is {"heading": "Poster headline", "body": "The words."}. A body can have several paragraphs, split by a blank line.
    Write each section in the brand's voice from its kit, and put in only the facts the brief and the kit give.
    Copy that the brand's fonts cannot draw, or that runs past 12 pages, raises an error. out_path ends in .pdf.
    """
    if not isinstance(title, str) or not title.strip():
        raise MakerError(NO_TITLE)
    if Path(out_path).suffix.lower() != ".pdf":
        raise MakerError(NOT_A_PDF.format(suffix=Path(out_path).suffix))
    # A client's own makers write only in their own folder.
    path = confine.output(out_path)
    sections = _with_the_pictures_note(_checked(sections))
    brand = load_brand_dir(brand_dir)
    title = title.strip()
    _check_drawable(brand, title, sections)
    pages = pages_for(brand, title, sections)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Fonts are embedded as TrueType, so the words in the file stay words that can be selected and searched.
    with rc_context({"pdf.fonttype": 42, "text.parse_math": False}), PdfPages(path, metadata={"Title": title, "Creator": "Foundry", "CreationDate": None}) as pdf:
        for number, items in enumerate(pages, start=1):
            pdf.savefig(_page(brand, number, items), facecolor=brand.colors["paper"])
    # The desk cannot read a page, so the words go beside the file for the number check, as a graphic's do. The foot's page numbers and the brand's name are not in it.
    record = "\n\n".join([title, *(f"{section['heading'].strip()}\n{section['body'].strip()}" for section in sections)])
    Path(f"{path}.txt").write_text(record, encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    mcp.run()
