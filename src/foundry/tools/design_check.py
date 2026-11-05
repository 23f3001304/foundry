"""Reads a finished deck or graphic and says what can really be measured in it: text that doesn't fit, type too small, contrast too low, too many words or bullets, and the same layout again and again.

It judges nothing it would have to guess. A title that is only a topic, whether a chart makes its point and whether the figures are right are not in here.
"""

import io
import json
from collections import Counter
from itertools import groupby
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from foundry.brand import Brand
from foundry.chain import SOURCE_LINE
from foundry.text import quiet
from foundry.tools.layout import LINE_SPACING, contrast, load_font, wrap, words_of

MOST_WORDS, SAID_WORDS, MOST_BULLETS, MOST_SAME_LAYOUT = 36, 30, 4, 3
# Points on a slide 960 wide. 12 is 20 pixels on a slide 1600 wide, the least that reads on a laptop across a table. A source line is a footnote.
LEAST_POINTS, LEAST_SOURCE_POINTS = 12, 9
LARGE_POINTS = 18
READ_CONTRAST, LARGE_CONTRAST = 4.5, 3
# PowerPoint and this measure differ by a word's width now and then, so only what is clearly over is said.
FIT_SLACK = 1.04
EDGE_SLACK = 1
# On a graphic, as shares of its short side. A phone shows a post about 390 wide, where 12 pixels is the least that reads.
LEAST_WORDS_SHARE, LEAST_HEADLINE_SHARE = 12 / 390, 0.05
LARGE_SHARE = 0.05
MOST_HEADLINE_WORDS = 12
RECORD = "{path}.design.json"
# Words on a chart slide that are its data, not sentences: a shape the deck tool names as a label or a figure.
DATA_SHAPES = (" label", " figure", "Lit figure", "Lit label", "Firm")
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SLIDE_MARKUP = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
RELATIONSHIPS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SOURCE_START = SOURCE_LINE.split("{", 1)[0]
QUOTED = 40
BULLET = "•"
# How far round a piece of words the ground is read, as a share of the page's short side.
GROUND_RING = 1 / 400


def record_of(path: Path | str) -> dict:
    """What render_graphic wrote beside a graphic: what it drew, where and how big."""
    try:
        return json.loads(Path(RECORD.format(path=path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hex(colour: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{part:02X}" for part in colour)


def _quoted(text: str) -> str:
    short = " ".join(quiet(text).split())
    return json.dumps(short[:QUOTED] + ("..." if len(short) > QUOTED else ""), ensure_ascii=False)


def _points(value: int | None) -> float:
    return Emu(value or 0).pt


def _ground_of_slide(slide) -> str | None:
    # The slide's own ground: a colour, or the average of its picture, which is how the stone is measured.
    ground = slide._element.find(f"{SLIDE_MARKUP}cSld/{SLIDE_MARKUP}bg/{SLIDE_MARKUP}bgPr")
    if ground is None:
        return None
    solid = ground.find(f"{DRAWING}solidFill/{DRAWING}srgbClr")
    if solid is not None:
        return f"#{solid.get('val')}"
    blip = ground.find(f"{DRAWING}blipFill/{DRAWING}blip")
    if blip is None:
        return None
    with Image.open(io.BytesIO(slide.part.related_part(blip.get(f"{RELATIONSHIPS}embed")).blob)) as picture:
        return _hex(picture.convert("RGB").resize((1, 1)).getpixel((0, 0)))


def _covers(shape, x: float, y: float) -> bool:
    return shape.left <= x <= shape.left + shape.width and shape.top <= y <= shape.top + shape.height


def _ground_under(slide, shape, slide_ground: str | None) -> str | None:
    # What is behind a box's middle: the nearest filled shape under it, or the slide. A picture under it can't be measured from the file, so it gives None and nothing is said.
    x, y = shape.left + shape.width / 2, shape.top + shape.height / 2
    below = None
    for other in slide.shapes:
        if other.shape_id == shape.shape_id:
            break
        if other.left is None or not _covers(other, x, y):
            continue
        if other.shape_type == MSO_SHAPE_TYPE.PICTURE:
            below = "picture"
        elif other.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
            solid = other._element.find(f"{SLIDE_MARKUP}spPr/{DRAWING}solidFill/{DRAWING}srgbClr")
            below = f"#{solid.get('val')}" if solid is not None else below
    if below == "picture":
        return None
    return below or slide_ground


def _colour_of(run) -> str | None:
    # A colour set on the run. Metal letters are filled with a picture and a colour left to the theme is not stated, so neither is measured.
    properties = run._r.find(f"{DRAWING}rPr")
    solid = None if properties is None else properties.find(f"{DRAWING}solidFill/{DRAWING}srgbClr")
    return f"#{solid.get('val')}" if solid is not None else None


def _font_path(brand: Brand, name: str | None) -> Path | None:
    return brand.font_file("heading" if name == brand.fonts["heading"] else "body")


def _main_runs(frame) -> list:
    # The largest run in each paragraph. A unit set small beside its figure is part of the figure, not type to read.
    largest = []
    for paragraph in frame.paragraphs:
        sized = [run for run in paragraph.runs if run.font.size and run.text.strip()]
        if sized:
            top = max(run.font.size for run in sized)
            largest += [run for run in sized if run.font.size == top]
    return largest


def _is_source_line(text: str) -> bool:
    return text.startswith(SOURCE_START)


def _is_data(shape) -> bool:
    return any(shape.name.endswith(ending) for ending in DATA_SHAPES)


def _fit_notes(number: int, shape, brand: Brand, width: float, height: float) -> list[str]:
    frame = shape.text_frame
    runs = _main_runs(frame)
    if not runs:
        return []
    size = runs[0].font.size.pt
    path = _font_path(brand, runs[0].font.name)
    # With no font of the kit's to measure with, the width of the words is not known.
    if path is None:
        return []
    inner_width = width - _points(frame.margin_left) - _points(frame.margin_right)
    inner_height = height - _points(frame.margin_top) - _points(frame.margin_bottom)
    font = load_font(path, round(size))
    if not frame.word_wrap:
        # A line that does not wrap is measured across. Its box is as tall as its digits, by design.
        widest = max((sum(load_font(_font_path(brand, run.font.name), round(run.font.size.pt)).getlength(run.text) for run in paragraph.runs if run.font.size) for paragraph in frame.paragraphs), default=0)
        return [f"Slide {number}: the words {_quoted(frame.text)} are too big for its box. Shorten them."] if widest > inner_width * FIT_SLACK + EDGE_SLACK else []
    needed = 0.0
    for paragraph in frame.paragraphs:
        pitch = paragraph.line_spacing if isinstance(paragraph.line_spacing, float) else 1.0
        needed += len(wrap("".join(run.text for run in paragraph.runs), font, inner_width)) * size * LINE_SPACING * pitch + (paragraph.space_after.pt if paragraph.space_after else 0)
    return [f"Slide {number}: the words {_quoted(frame.text)} are too big for its box. Shorten them or split the slide."] if needed > inner_height * FIT_SLACK + EDGE_SLACK else []


def _text_notes(number: int, slide, shape, runs_from, deck_width: float, deck_height: float, slide_ground: str | None) -> list[str]:
    notes, frame = [], shape.text_frame
    left, top, width, height = _points(shape.left), _points(shape.top), _points(shape.width), _points(shape.height)
    if left < -EDGE_SLACK or top < -EDGE_SLACK or left + width > deck_width + EDGE_SLACK or top + height > deck_height + EDGE_SLACK:
        notes.append(f"Slide {number}: the words {_quoted(frame.text)} run off the slide.")
    runs = _main_runs(frame)
    source = _is_source_line(frame.text)
    least = LEAST_SOURCE_POINTS if source else LEAST_POINTS
    small = min((run.font.size.pt for run in runs), default=least)
    if small < least:
        fix = "Say less in that source line." if source else "Use fewer words or rows on the slide, so the tool can set them larger."
        notes.append(f"Slide {number}: the words {_quoted(frame.text)} are {small:g} point, below the {least} that reads. {fix}")
    ground = _ground_under(slide, shape, slide_ground)
    if ground:
        worst = None
        for run in runs_from(frame):
            colour = _colour_of(run)
            if colour and run.font.size:
                limit = LARGE_CONTRAST if run.font.size.pt >= LARGE_POINTS else READ_CONTRAST
                measured = contrast(colour, ground)
                if measured < limit and (worst is None or measured < worst[0]):
                    worst = (measured, limit, run.text)
        if worst:
            notes.append(f"Slide {number}: the words {_quoted(worst[2])} have a contrast of {worst[0]:.1f} to 1 against what is behind them, and need {worst[1]:g} to 1 to read. Light other words, or use a layout on another ground.")
    return notes


def _all_runs(frame) -> list:
    return [run for paragraph in frame.paragraphs for run in paragraph.runs if run.text.strip()]


def _table_notes(number: int, slide, shape, brand: Brand, deck_height: float, slide_ground: str | None) -> list[str]:
    notes, table = [], shape.table
    sizes = [run.font.size.pt for row in table.rows for cell in row.cells for run in _main_runs(cell.text_frame)]
    if sizes and min(sizes) < LEAST_POINTS:
        notes.append(f"Slide {number}: a table's words are {min(sizes):g} point, below the {LEAST_POINTS} that reads. Show fewer rows or columns, or split the table over two slides.")
    if slide_ground and _ground_under(slide, shape, slide_ground):
        worst = None
        for row in table.rows:
            for cell in row.cells:
                for run in _all_runs(cell.text_frame):
                    colour = _colour_of(run)
                    if colour and run.font.size:
                        limit = LARGE_CONTRAST if run.font.size.pt >= LARGE_POINTS else READ_CONTRAST
                        measured = contrast(colour, slide_ground)
                        if measured < limit and (worst is None or measured < worst[0]):
                            worst = (measured, limit, run.text)
        if worst:
            notes.append(f"Slide {number}: the table's words {_quoted(worst[2])} have a contrast of {worst[0]:.1f} to 1 against what is behind them, and need {worst[1]:g} to 1 to read.")
    needed = _points(shape.top) + sum(_points(row.height) for row in table.rows)
    if needed > deck_height + EDGE_SLACK:
        notes.append(f"Slide {number}: the table runs off the slide. Show fewer rows, or split it over two slides.")
    return notes


def _slide_notes(number: int, slide, brand: Brand, deck_width: float, deck_height: float) -> list[str]:
    notes, words, bullets = [], 0, 0
    has_table = False
    slide_ground = _ground_of_slide(slide)
    for shape in slide.shapes:
        if getattr(shape, "has_table", False) and shape.has_table:
            has_table = True
            notes += _table_notes(number, slide, shape, brand, deck_height, slide_ground)
            continue
        if not shape.has_text_frame or not shape.text_frame.text.strip():
            continue
        frame = shape.text_frame
        notes += _text_notes(number, slide, shape, _all_runs, deck_width, deck_height, slide_ground)
        notes += _fit_notes(number, shape, brand, _points(shape.width), _points(shape.height))
        if not _is_source_line(frame.text) and not _is_data(shape):
            words += sum(1 for word in words_of(frame.text) if word != BULLET)
        bullets += sum(1 for paragraph in frame.paragraphs if "".join(run.text for run in paragraph.runs).startswith(BULLET))
    if not has_table and words > MOST_WORDS:
        notes.append(f"Slide {number}: it holds {words} words, and a slide that is not a table holds about {SAID_WORDS}. Cut the words or split the slide.")
    if bullets > MOST_BULLETS:
        notes.append(f"Slide {number}: it has {bullets} bullets, and a slide has at most four. Say it in a sentence, or split the slide.")
    return notes


def _layout_notes(deck) -> list[str]:
    # A deck names each slide's layout as it is built, and with no names nothing is said, because a layout can't be told from where its shapes fell.
    notes, at = [], 1
    for layout, slides in groupby(slide.name for slide in deck.slides):
        count = len(list(slides))
        if layout and count >= MOST_SAME_LAYOUT:
            notes.append(f"Slides {at} to {at + count - 1} all use the {layout} layout. Vary them: a big number, a chart, a statement, a table.")
        at += count
    return notes


def check_deck(path: Path | str, brand: Brand) -> list[str]:
    deck = Presentation(str(path))
    width, height = _points(deck.slide_width), _points(deck.slide_height)
    notes = [note for number, slide in enumerate(deck.slides, start=1) for note in _slide_notes(number, slide, brand, width, height)]
    return notes + _layout_notes(deck)


def _ground_around(picture: Image.Image, box: list[int]) -> str | None:
    # The commonest colour in a thin ring just outside the words, from the finished picture itself. Inside the box the letters are in the way.
    left, top, right, bottom = box
    ring = max(2, round(min(picture.size) * GROUND_RING))
    seen: Counter = Counter()
    for strip in ((left - ring, top - ring, right + ring, top), (left - ring, bottom, right + ring, bottom + ring), (left - ring, top, left, bottom), (right, top, right + ring, bottom)):
        edge = (max(strip[0], 0), max(strip[1], 0), min(strip[2], picture.width), min(strip[3], picture.height))
        if edge[0] < edge[2] and edge[1] < edge[3]:
            crop = picture.crop(edge)
            seen.update({found: count for count, found in crop.getcolors(crop.width * crop.height)})
    return _hex(seen.most_common(1)[0][0]) if seen else None


def check_graphic(path: Path | str, brand: Brand) -> list[str]:
    record = record_of(path)
    if not record:
        return []
    notes = []
    drawn = record["drawn"]
    with Image.open(path) as image:
        picture = image.convert("RGB")
    short = min(picture.size)
    headline = record.get("headline", "")
    subline = record.get("subline", "")
    if (count := len(words_of(headline))) > MOST_HEADLINE_WORDS:
        notes.append(f"The headline has {count} words, and one that reads at thumbnail size has about {MOST_HEADLINE_WORDS} at most. Cut it to one idea.")
    if (total := len(words_of(headline)) + len(words_of(subline))) > MOST_WORDS:
        notes.append(f"It holds {total} words, and a graphic holds about {SAID_WORDS} at most. Cut them.")
    for role, share, what in (("headline", LEAST_HEADLINE_SHARE, "The headline"), ("subline", LEAST_WORDS_SHARE, "The subline")):
        sizes = [item["size"] for item in drawn if item["role"] == role]
        if sizes and min(sizes) < share * short:
            notes.append(f"{what} is set too small to read at phone size. Use fewer words, so the tool can set them larger.")
    width, height = picture.size
    for item in drawn:
        left, top, right, bottom = item["box"]
        if left < 0 or top < 0 or right > width or bottom > height:
            notes.append(f"The words {_quoted(item['words'])} run off the page.")
            continue
        ground = _ground_around(picture, item["box"])
        if ground:
            limit = LARGE_CONTRAST if item["size"] >= LARGE_SHARE * short else READ_CONTRAST
            measured = contrast(item["colour"], ground)
            if measured < limit:
                notes.append(f"The words {_quoted(item['words'])} have a contrast of {measured:.1f} to 1 against what is behind them, and need {limit:g} to 1 to read. Use another composition, or light other words.")
    return list(dict.fromkeys(notes))


def check(path: Path | str, brand: Brand) -> list[str]:
    """Plain notes a maker can act on. An empty list means nothing this check can measure is wrong, and says nothing of how it looks."""
    return check_deck(path, brand) if Path(path).suffix.lower() == ".pptx" else check_graphic(path, brand)

