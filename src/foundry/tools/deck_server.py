"""MCP tool for maker agents: builds a slide deck whose colours, fonts, logo and layout come from the brand kit."""

import re
from pathlib import Path

from lxml import etree
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Pt

from foundry.brand import Brand, load_brand_dir
from foundry.chain import Link, source_line, write_links
from foundry.tools.layout import fit_size

mcp = MCPServer("foundry-deck")

WIDTH, HEIGHT = 960, 540
TITLE_ONLY = 5
BULLET_GAP = 16
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
# The small line under a slide's content that says where its numbers came from. It stops short of the corner logo.
SOURCE_BOX = (56, 500, 780, 28)
NARROW_SOURCE_BOX = (56, 500, 580, 28)
SOURCE_SIZES = (11, 7)
SOURCE_SHAPE = 'Each source is {"value": "62%", "entry": 123, "label": "Team Lead B, 6:12 pm"}.'


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
        raise ValueError(f"A {layout} slide needs its {field}.")
    return spec[field]


def _check_highlight(highlight: str, *texts: str) -> None:
    if highlight and not any(highlight in text for text in texts):
        raise ValueError(f"The highlight must be words on the slide. {highlight!r} is not on it.")


def _make_title(deck: Presentation, brand: Brand, spec: dict) -> None:
    _title_slide(deck, brand, _required(spec, "title", "title"), spec.get("subtitle", ""), spec.get("highlight", ""))


def _make_content(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "content")
    points = [f"• {point}" for point in _required(spec, "bullets", "content")]
    highlight = spec.get("highlight", "")
    _check_highlight(highlight, title, *points)
    slide = _new_slide(deck, brand, "paper")
    if brand.style == "solid":
        _block(slide, brand, "primary", 0, 0, WIDTH, 110)
        _write(slide.shapes.title, brand, "heading", "paper", (56, 22, 848, 70), [title], 34, 16, middle=True, highlight=highlight)
        _text_box(slide, brand, "body", "ink", (56, 140, 790, 350), points, 32, 13, BULLET_GAP, highlight)
    else:
        _block(slide, brand, "primary", 0, 0, 24, HEIGHT)
        _write(slide.shapes.title, brand, "heading", "primary", (72, 44, 780, 90), [title], 36, 16, highlight=highlight)
        _text_box(slide, brand, "body", "ink", (72, 150, 780, 340), points, 32, 13, BULLET_GAP, highlight)
    _corner_logo(slide, brand, on_paper=True)


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


LAYOUTS = {"title": _make_title, "content": _make_content, "statement": _make_statement}


class SourceError(ToolError, ValueError):
    """A source the maker got wrong. As a ToolError the maker is shown why, which a plain ValueError would not be."""


def _source(item: object, slide: int, words: list[str]) -> Link:
    if not isinstance(item, dict):
        raise SourceError(SOURCE_SHAPE)
    value, entry, label = item.get("value"), item.get("entry"), item.get("label")
    if not isinstance(value, str) or not value.strip():
        raise SourceError(f'A source needs its "value", the words or number it is for. {SOURCE_SHAPE}')
    if isinstance(entry, bool) or not isinstance(entry, int):
        raise SourceError(f'A source needs its "entry", the whole number job_facts gave for it. {SOURCE_SHAPE}')
    if not isinstance(label, str) or not label.strip():
        raise SourceError(f'A source needs its "label", who gave it and when. {SOURCE_SHAPE}')
    if not any(value in text for text in words):
        raise SourceError(f"A source's value must be words on its slide. {value!r} is not on it.")
    return Link(slide, value, entry, label)


def _sources_of(spec: dict, slide: int) -> list[Link]:
    given = spec.get("sources") or []
    if not isinstance(given, list):
        raise SourceError(f'A slide\'s "sources" must be a list. {SOURCE_SHAPE}')
    words = [spec.get(key, "") for key in ("title", "subtitle", "text")] + list(spec.get("bullets", []))
    return [_source(item, slide, words) for item in given]


def _print_sources(slide, brand: Brand, links: list[Link], layout: str) -> None:
    # Over the brand's dark colour the words are paper, and elsewhere they are ink.
    solid = brand.style == "solid"
    colour = "paper" if solid and layout in ("title", "statement") else "ink"
    box = NARROW_SOURCE_BOX if solid and layout == "title" else SOURCE_BOX
    _text_box(slide, brand, "body", colour, box, [source_line(links)], *SOURCE_SIZES)


@mcp.tool()
def build_deck(brand_dir: str, title: str, slides: list[dict], out_path: str, highlight: str = "") -> str:
    """Build an on-brand .pptx and return its absolute path. The title slide comes first, from title.

    Each slide is one of:
    {"layout": "content", "title": "...", "bullets": ["...", "..."]}
    {"layout": "statement", "text": "One big sentence."}
    {"layout": "title", "title": "...", "subtitle": "..."}
    Any slide can also have "highlight": words on that slide to put on the brand's accent colour, for the one thing that matters most.
    highlight does the same for the title slide. Text that cannot fit raises an error. Shorten it or split the slide.

    Any slide can also have "sources": [{"value": "62%", "entry": 123, "label": "Team Lead B, 6:12 pm"}], one for each number or
    fact on that slide that came from the log. value is the words on the slide. entry is the number job_facts gave that entry.
    label says who gave it and when. The slide prints them as a small line, and the links are saved beside the deck for the chain.
    """
    brand = load_brand_dir(brand_dir)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(WIDTH), Pt(HEIGHT)
    _apply_theme(deck, brand)
    _title_slide(deck, brand, title, "", highlight)
    links: list[Link] = []
    for number, spec in enumerate(slides, start=2):
        layout = LAYOUTS.get(spec.get("layout"))
        if layout is None:
            raise ValueError(f"Unknown layout {spec.get('layout')!r}. Use one of: {', '.join(LAYOUTS)}.")
        sources = _sources_of(spec, number)
        layout(deck, brand, spec)
        if sources:
            _print_sources(deck.slides[-1], brand, sources, spec["layout"])
            links += sources
    path = Path(out_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))
    write_links(path, links)
    return str(path)


if __name__ == "__main__":
    mcp.run()
