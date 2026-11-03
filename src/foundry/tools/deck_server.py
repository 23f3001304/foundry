"""MCP tool for maker agents: builds a slide deck whose colours, fonts, logo and layout come from the brand kit."""

from pathlib import Path

from lxml import etree
from mcp.server.mcpserver import MCPServer
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Pt

from foundry.brand import Brand, load_brand_dir
from foundry.tools.layout import fit_size

mcp = MCPServer("foundry-deck")

WIDTH, HEIGHT = 960, 540
TITLE_ONLY = 5
BULLET_GAP = 16
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


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


def _write(shape, brand: Brand, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0, middle: bool = False) -> None:
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
        run = paragraph.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.name = brand.fonts[role]
        run.font.color.rgb = _colour(brand, colour)


def _text_box(slide, brand: Brand, role: str, colour: str, box: tuple[int, int, int, int], paragraphs: list[str], largest: int, smallest: int, gap: int = 0) -> None:
    shape = slide.shapes.add_textbox(*(Pt(value) for value in box))
    _write(shape, brand, role, colour, box, paragraphs, largest, smallest, gap)


def _corner_logo(slide, brand: Brand, on_paper: bool) -> None:
    if not on_paper:
        _block(slide, brand, "paper", 860, 440, 100, 100)
    slide.shapes.add_picture(str(brand.logo_path), Pt(872), Pt(452), width=Pt(76))


def _title_slide(deck: Presentation, brand: Brand, title: str, subtitle: str) -> None:
    if brand.style == "solid":
        slide = _new_slide(deck, brand, "primary")
        _block(slide, brand, "paper", 680, 0, 280, HEIGHT)
        _block(slide, brand, "accent", 56, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(730), Pt(180), width=Pt(180))
        _write(slide.shapes.title, brand, "heading", "paper", (56, 150, 580, 230), [title], 54, 22)
        ink = "paper"
        subtitle_box = (56, 400, 580, 60)
    else:
        slide = _new_slide(deck, brand, "paper")
        _block(slide, brand, "primary", 0, 0, 48, HEIGHT)
        _block(slide, brand, "accent", 96, 130, 96, 6)
        slide.shapes.add_picture(str(brand.logo_path), Pt(770), Pt(36), width=Pt(150))
        _write(slide.shapes.title, brand, "heading", "primary", (96, 150, 640, 230), [title], 54, 22)
        ink = "ink"
        subtitle_box = (96, 400, 640, 60)
    if subtitle:
        _text_box(slide, brand, "body", ink, subtitle_box, [subtitle], 24, 14)


def _required(spec: dict, field: str, layout: str) -> str | list:
    if not spec.get(field):
        raise ValueError(f"A {layout} slide needs its {field}.")
    return spec[field]


def _make_title(deck: Presentation, brand: Brand, spec: dict) -> None:
    _title_slide(deck, brand, _required(spec, "title", "title"), spec.get("subtitle", ""))


def _make_content(deck: Presentation, brand: Brand, spec: dict) -> None:
    title = _required(spec, "title", "content")
    points = [f"• {point}" for point in _required(spec, "bullets", "content")]
    slide = _new_slide(deck, brand, "paper")
    if brand.style == "solid":
        _block(slide, brand, "primary", 0, 0, WIDTH, 110)
        _write(slide.shapes.title, brand, "heading", "paper", (56, 22, 848, 70), [title], 34, 16, middle=True)
        _text_box(slide, brand, "body", "ink", (56, 140, 790, 350), points, 32, 13, BULLET_GAP)
    else:
        _block(slide, brand, "primary", 0, 0, 24, HEIGHT)
        _write(slide.shapes.title, brand, "heading", "primary", (72, 44, 780, 90), [title], 36, 16)
        _text_box(slide, brand, "body", "ink", (72, 150, 780, 340), points, 32, 13, BULLET_GAP)
    _corner_logo(slide, brand, on_paper=True)


def _make_statement(deck: Presentation, brand: Brand, spec: dict) -> None:
    text = _required(spec, "text", "statement")
    solid = brand.style == "solid"
    slide = _new_slide(deck, brand, "primary" if solid else "paper")
    _block(slide, brand, "accent", 96, 110, 96, 6)
    _write(slide.shapes.title, brand, "heading", "paper" if solid else "primary", (96, 130, 740, 290), [text], 60, 22, middle=True)
    _corner_logo(slide, brand, on_paper=not solid)


LAYOUTS = {"title": _make_title, "content": _make_content, "statement": _make_statement}


@mcp.tool()
def build_deck(brand_dir: str, title: str, slides: list[dict], out_path: str) -> str:
    """Build an on-brand .pptx and return its absolute path. The title slide comes first, from title.

    Each slide is one of:
    {"layout": "content", "title": "...", "bullets": ["...", "..."]}
    {"layout": "statement", "text": "One big sentence."}
    {"layout": "title", "title": "...", "subtitle": "..."}
    Text that cannot fit raises an error. Shorten it or split the slide.
    """
    brand = load_brand_dir(brand_dir)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(WIDTH), Pt(HEIGHT)
    _apply_theme(deck, brand)
    _title_slide(deck, brand, title, "")
    for spec in slides:
        layout = LAYOUTS.get(spec.get("layout"))
        if layout is None:
            raise ValueError(f"Unknown layout {spec.get('layout')!r}. Use one of: {', '.join(LAYOUTS)}.")
        layout(deck, brand, spec)
    path = Path(out_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))
    return str(path)


if __name__ == "__main__":
    mcp.run()
