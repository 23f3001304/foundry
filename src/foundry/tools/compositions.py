"""The compositions of a graphic a maker chooses from, besides the split: a huge headline, a picture across the page, and a big sentence on the brand's colour.

They follow the design guide. Margins are a share of the short side, wider in a quiet style. At most two sizes of type, with an obvious jump. Line spacing falls as type grows, and huge type is tracked tight.
Big type is placed by what the eye sees, not by its box. The logo sits only on the paper colour, with clear space a quarter of its width. No word is ever drawn on a picture.
"""

import io
import math
import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont, ImageOps

from foundry.brand import Brand
from foundry.tools import touchstone
from foundry.tools.layout import MakerError, check_font_can_draw, contrast, load_font, rgb, words_of

MARGIN_SHARE, QUIET_MARGIN_SHARE = 0.07, 0.10
QUIET_STYLES = ("quiet", "editorial")
TOUCHSTONE = "touchstone"
READ_CONTRAST, LARGE_CONTRAST = 4.5, 3
# Line spacing falls as type grows: 1.0 to 1.1 for huge headlines and about 1.3 for a line or two of words under them. Huge type sits tighter.
HEADLINE_PITCH, WORDS_PITCH, TIGHT_TRACKING = 1.04, 1.3, -0.018
TIGHT_FROM_SHARE = 0.1
# Sizes as shares of the short side. Nothing is set below what reads at phone size.
LEAST_WORDS, MOST_WORDS, LEAST_HEADLINE = 0.032, 0.05, 0.055
TYPE_LED_MOST, STATEMENT_MOST, PANEL_MOST = 0.46, 0.17, 0.115
LOGO_SHARE, PANEL_LOGO_SHARE = 0.15, 0.13
MARK_LENGTH_SHARE, MARK_THICK_SHARE = 0.2, 0.014
# How much of the page a panel's words may take, so the picture stays the point.
MOST_PANEL_HEIGHT, MOST_TALL_PANEL_HEIGHT, MOST_FOOTER_HEIGHT = 0.44, 0.34, 0.3
WIDE_FROM = 1.2
TOO_LONG = "This text is too long to fit: {text}... Shorten it."
LOGO_CLEAR = 4
# A line should not end on a word that leans on the next one, and a headline's last line should not be one word. These weigh against the evenness of the lines.
LEANING_WORDS = frozenset("a an and at by for from in into is of on or the to with".split())
LEANING_COST, LONE_WORD_COST = 0.12, 0.6
MOST_BALANCED_WORDS = 40
# A smaller size is taken to spare a small word a line of its own, down to this share of the size that first fitted.
LEAST_TO_SPARE_A_WORD = 0.72
NO_BREAK = "\u00a0"
# A line should break after a comma or a stop rather than run on past one, when the lengths allow.
SENSE_COST = 0.08
SENSE_MARKS = ",.;:!?"
# A letter or a number that names what comes before it, as in Office E, Sprint 14 or Nov 14. Whatever follows a comma or a stop starts afresh.
NAMING = re.compile(r"(?:\d{1,4}|[A-Z]{1,2})[,.;:!?]?")


def margin_of(brand: Brand, unit: int) -> int:
    # 5 to 8 percent of the short side for most work, and 10 percent when the style is quiet.
    quiet = any(word in brand.design_style.casefold() for word in QUIET_STYLES)
    return round(unit * (QUIET_MARGIN_SHARE if quiet else MARGIN_SHARE))


def statement_colours(brand: Brand) -> tuple[str, str]:
    # The ground and the words of a big statement. The brand's large colour, with whichever of its light and dark reads best. The stone's ash is for what recedes, so it stays on the stone.
    colours = brand.colors
    if brand.style == TOUCHSTONE:
        return colours["paper"], colours["ink"]
    return colours["primary"], max((colours["paper"], colours["ink"]), key=lambda words: contrast(words, colours["primary"]))


def heading_colour(brand: Brand) -> str:
    return brand.colors["ink" if brand.style == TOUCHSTONE else "primary"]


@dataclass
class Set:
    # Words fitted to their room, not yet drawn.
    lines: list[str]
    size: int
    font: ImageFont.FreeTypeFont
    pitch: float
    tracking: float

    @property
    def cap(self) -> int:
        return -self.font.getbbox("H", anchor="ls")[1]

    @property
    def rise(self) -> int:
        # How far the first line's tallest letter stands above its baseline, so nothing crosses the margin.
        return -self.font.getbbox(self.lines[0], anchor="ls")[1]

    @property
    def height(self) -> int:
        # From the top of the first line's letters to the foot of the last line's descenders.
        return round(self.rise + (len(self.lines) - 1) * self.size * self.pitch + max(self.font.getbbox(self.lines[-1], anchor="ls")[3], 0))


@dataclass
class Page:
    brand: Brand
    width: int
    height: int
    canvas: Image.Image
    drawn: list[dict] = field(default_factory=list)
    logo: list[int] = field(default_factory=list)
    panel: list[int] = field(default_factory=list)

    @property
    def unit(self) -> int:
        return min(self.width, self.height)

    @property
    def margin(self) -> int:
        return margin_of(self.brand, self.unit)

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.canvas)


def _tracked_width(font: ImageFont.FreeTypeFont, text: str, tracking: float) -> float:
    # By the ink as well as the advance, because a last letter like an f hangs past its own advance.
    return max(font.getlength(text), font.getbbox(text, anchor="ls")[2]) + tracking * max(len(text) - 1, 0)


def _held_together(paragraph: str, highlight: str) -> str:
    # Words that must not be parted on a line are joined by a no-break space while the lines are worked out: lit words, and a name with its letter or number.
    held = paragraph.replace(highlight, highlight.replace(" ", NO_BREAK)) if highlight else paragraph
    words = words_of(held)
    joined = words[:1]
    for word in words[1:]:
        before = joined[-1]
        leans = NAMING.fullmatch(word) and (before[-1] not in ",.;:!?" or before[0].isdigit())
        joined[-1:] = [f"{before}{NO_BREAK}{word}"] if leans else [before, word]
    return " ".join(joined)


def _whole_words(paragraph: str, font: ImageFont.FreeTypeFont, width: float, tracking: float) -> list[str] | None:
    # Lines that keep every word whole, or None when a word is wider than the room at this size.
    lines, line = [], ""
    for word in words_of(paragraph):
        if _tracked_width(font, word, tracking) > width:
            return None
        candidate = f"{line} {word}" if line else word
        if _tracked_width(font, candidate, tracking) <= width:
            line = candidate
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def _line_cost(line: list[str], font: ImageFont.FreeTypeFont, width: float, tracking: float, last: bool, alone: bool) -> float:
    wide = _tracked_width(font, " ".join(line), tracking)
    if wide > width:
        return math.inf
    # Rule 12: lines of a like length that break where the sense breaks, and no word alone on the last line. Those are preferences, so a line that can do no better still stands.
    cost = ((width - wide) / width) ** 2 * (0.4 if last else 1)
    if not last and line[-1].casefold() in LEANING_WORDS:
        cost += LEANING_COST
    if any(word[-1] in SENSE_MARKS for word in line[:-1]):
        cost += SENSE_COST
    if last and alone and len(line) == 1:
        cost += LONE_WORD_COST
    return cost


def _balanced(paragraph: str, count: int, font: ImageFont.FreeTypeFont, width: float, tracking: float) -> list[str] | None:
    # The best way to break these words into this many lines, by trying every way there is, a word at a time. Only ever run on the few words of a headline.
    words = words_of(paragraph)
    if count == 1 or len(words) > MOST_BALANCED_WORDS:
        return None
    best: dict[tuple[int, int], tuple[float, int]] = {(0, 0): (0.0, 0)}
    for lines in range(1, count + 1):
        for end in range(lines, len(words) + 1):
            for start in range(lines - 1, end):
                if (start, lines - 1) in best:
                    cost = best[(start, lines - 1)][0] + _line_cost(words[start:end], font, width, tracking, lines == count, count > 1 and len(words) > count)
                    if cost < best.get((end, lines), (math.inf, 0))[0]:
                        best[(end, lines)] = (cost, start)
    if (len(words), count) not in best:
        return None
    breaks, end = [], len(words)
    for lines in range(count, 0, -1):
        start = best[(end, lines)][1]
        breaks.append(" ".join(words[start:end]))
        end = start
    return breaks[::-1]


def balanced_lines(text: str, font: ImageFont.FreeTypeFont, width: float, count: int, highlight: str = "") -> list[str] | None:
    # Lines at a size already chosen, for a composition that has wrapped them itself.
    return _balanced(_held_together(text, highlight), count, font, width, 0)


def _strands_a_word(lines: list[str]) -> bool:
    return any(line.casefold() in LEANING_WORDS for line in lines)


def _fit(page: Page, text: str, role: str, width: float, height: float, largest: float, smallest: float, pitch: float, tight: bool = False, highlight: str = "") -> Set:
    path = page.brand.font_file("heading" if role == "headline" else "body")
    most, least = round(page.unit * largest), round(page.unit * smallest)
    check_font_can_draw(text, load_font(path, least), "heading" if role == "headline" else "body")
    paragraphs = [_held_together(paragraph, highlight) for paragraph in text.splitlines()]
    first = None
    # A break the maker gave says where a line ends, so a size that keeps each of its lines whole comes first.
    for whole_lines in (True, False) if len(paragraphs) > 1 else (False,):
        for size in range(most, least - 1, -max(1, page.unit // 250)):
            font = load_font(path, size)
            tracking = size * TIGHT_TRACKING if tight and size >= page.unit * TIGHT_FROM_SHARE else 0
            broken = [_whole_words(paragraph, font, width, tracking) for paragraph in paragraphs]
            if any(lines is None for lines in broken) or (whole_lines and any(len(lines) > 1 for lines in broken)):
                continue
            fitted = Set([line for lines in broken for line in lines], size, font, pitch, tracking)
            if fitted.height <= height:
                fitted.lines = [line.replace(NO_BREAK, " ") for paragraph, lines in zip(paragraphs, broken) for line in (_balanced(paragraph, len(lines), font, width, tracking) or lines)]
                first = first or fitted
                if not _strands_a_word(fitted.lines):
                    return fitted
                if size < first.size * LEAST_TO_SPARE_A_WORD:
                    return first
    if first:
        return first
    raise MakerError(TOO_LONG.format(text=text[:60]))


def _ink_box(font: ImageFont.FreeTypeFont, text: str, x: float, baseline: float, tracking: float) -> list[int]:
    left, top, right, bottom = font.getbbox(text, anchor="ls")
    return [math.floor(x + left), math.floor(baseline + top), math.ceil(x + right + tracking * max(len(text) - 1, 0)), math.ceil(baseline + bottom)]


def _piece(page: Page, text: str, role: str, fitted: Set, x: float, baseline: float, colour: str) -> None:
    # Letter by letter when tracked, keeping the font's own spacing between each pair.
    draw, font = page.draw, fitted.font
    if fitted.tracking:
        for at, letter in enumerate(text):
            draw.text((x + font.getlength(text[: at + 1]) - font.getlength(letter) + fitted.tracking * at, baseline), letter, font=font, fill=rgb(colour), anchor="ls")
    else:
        draw.text((x, baseline), text, font=font, fill=rgb(colour), anchor="ls")
    if text.strip():
        page.drawn.append({"role": role, "words": text, "size": fitted.size, "box": _ink_box(font, text, x, baseline, fitted.tracking), "colour": colour.upper()})


def _lit_look(brand: Brand, ground: str) -> tuple[str, str]:
    # Lit words as the accent's own letters where it reads on this ground, or on a block of it, in whichever of the kit's light and dark reads on it, where it does not.
    accent = brand.colors["accent"]
    if contrast(accent, ground) >= LARGE_CONTRAST:
        return accent, ""
    return max((brand.colors["ink"], brand.colors["paper"]), key=lambda words: contrast(words, accent)), accent


def _set_lines(page: Page, fitted: Set, role: str, x: float, top: float, colour: str, ground: str = "", highlight: str = "") -> int:
    # What the eye sees goes on the shared edge and the top line: the left of the first letter and the top of the capitals.
    baseline = top + fitted.rise
    start = " ".join(fitted.lines).find(highlight) if highlight else -1
    end, offset = start + len(highlight), 0
    lit_colour, marker = _lit_look(page.brand, ground) if highlight else ("", "")
    for line in fitted.lines:
        left = x - fitted.font.getbbox(line[:1], anchor="ls")[0]
        first, last = max(start - offset, 0), min(end - offset, len(line))
        if start >= 0 and first < last:
            before, lit, after = line[:first], line[first:last], line[last:]
            at = lambda cut: left + fitted.font.getlength(line[:cut]) + fitted.tracking * cut
            if marker:
                pad = fitted.size * 0.1
                page.draw.rectangle((at(first) - pad, baseline - fitted.cap - pad, at(last) + pad, baseline + pad), fill=rgb(marker))
            _piece(page, before, role, fitted, left, baseline, colour)
            _piece(page, lit, "lit", fitted, at(first), baseline, lit_colour)
            _piece(page, after, role, fitted, at(last), baseline, colour)
        else:
            _piece(page, line, role, fitted, left, baseline, colour)
        offset += len(line) + 1
        baseline += fitted.size * fitted.pitch
    return round(top + fitted.height)


def _paper_ground(page: Page) -> None:
    # A kit on the stone has the stone under everything it makes.
    if page.brand.style == TOUCHSTONE:
        with Image.open(io.BytesIO(touchstone.stone(page.brand.colors["paper"]))) as stone:
            page.canvas.paste(ImageOps.fit(stone.convert("RGB"), page.canvas.size, Image.LANCZOS), (0, 0))


def _place_logo(page: Page, side: int, right: int, bottom: int) -> None:
    logo = Image.open(page.brand.logo_path).convert("RGBA").resize((side, side), Image.LANCZOS)
    left, top = right - side, bottom - side
    page.canvas.paste(logo, (left, top), logo)
    page.logo = [left, top, left + side, top + side]


def _accent_mark(page: Page, left: int, top: int) -> int:
    # With nothing lit, a short mark, so the accent is on the page once. On the stone it is a rub of the metal. Returns where it ends.
    length, thick = round(page.width * MARK_LENGTH_SHARE), max(4, round(page.unit * MARK_THICK_SHARE))
    accent = page.brand.colors["accent"]
    if page.brand.style == TOUCHSTONE:
        points = 96
        art, pad = touchstone.rub(points, 8, accent, True, False, "graphic mark")
        with Image.open(io.BytesIO(art)) as picture:
            scale = length / points
            wide = picture.convert("RGBA").resize((round((points + 2 * pad) * scale), max(thick, round((8 + 2 * pad) * scale))), Image.LANCZOS)
        off = round(pad * scale)
        page.canvas.paste(wide, (left - off, top - off), wide)
        return top + round(8 * scale)
    page.draw.rectangle((left, top, left + length, top + thick), fill=rgb(accent))
    return top + thick


def _words_under(page: Page, subline: str, width: float, most_height: float) -> Set | None:
    return _fit(page, subline, "subline", width, most_height, MOST_WORDS, LEAST_WORDS, WORDS_PITCH) if subline else None


def _with_a_jump(page: Page, words: Set | None, subline: str, width: float, most_height: float, headline: Set) -> Set | None:
    # Two sizes with an obvious jump: words under a headline are at most half its size, unless that would be too small to read at phone size.
    if words is None or words.size * 2 <= headline.size:
        return words
    return _fit(page, subline, "subline", width, most_height, max(headline.size / 2 / page.unit, LEAST_WORDS), LEAST_WORDS, WORDS_PITCH)


def type_led(page: Page, headline: str, subline: str, highlight: str) -> None:
    """A huge headline filling the page, its subline and logo in the foot."""
    brand, margin = page.brand, page.margin
    ground = brand.colors["paper"]
    _paper_ground(page)
    logo_side = round(page.unit * LOGO_SHARE)
    room = page.width - 2 * margin
    words = _words_under(page, subline, room - logo_side - margin, page.height * MOST_FOOTER_HEIGHT)
    mark = 0 if highlight else max(4, round(page.unit * MARK_THICK_SHARE)) + margin // 2
    foot = max(logo_side, (words.height if words else 0) + mark)
    bottom = page.height - margin
    fitted = _fit(page, headline, "headline", room, bottom - foot - margin - margin, TYPE_LED_MOST, LEAST_HEADLINE, HEADLINE_PITCH, tight=True, highlight=highlight)
    _set_lines(page, fitted, "headline", margin, margin, heading_colour(brand), ground, highlight)
    if not highlight:
        _accent_mark(page, margin, bottom - (words.height if words else 0) - mark)
    if words:
        _set_lines(page, words, "subline", margin, bottom - words.height, brand.colors["ink"])
    _place_logo(page, logo_side, page.width - margin, bottom)


def statement(page: Page, headline: str, subline: str, highlight: str) -> None:
    """One big sentence on the brand's colour, with the logo on a piece of the paper colour that runs off the corner."""
    brand, margin = page.brand, page.margin
    ground, words_colour = statement_colours(brand)
    if brand.style == TOUCHSTONE:
        _paper_ground(page)
    logo_side = round(page.unit * LOGO_SHARE)
    # Kept on the paper colour with clear space. On the stone the page already is the paper colour, so the logo needs no piece of it.
    clear = logo_side // LOGO_CLEAR + round(page.unit * 0.012)
    block = logo_side + 2 * clear
    room = page.width - 2 * margin
    bottom_of_words = page.height - margin if page.width > page.height * WIDE_FROM else page.height - block - margin // 2
    words = _words_under(page, subline, room if page.width <= page.height * WIDE_FROM else room - block, page.height * MOST_FOOTER_HEIGHT)
    mark = 0 if highlight else max(4, round(page.unit * MARK_THICK_SHARE)) + margin
    gap = margin if words else 0
    space = bottom_of_words - margin - mark - gap - (words.height if words else 0)
    fitted = _fit(page, headline, "headline", room, space, STATEMENT_MOST, LEAST_HEADLINE, 1.08, tight=True, highlight=highlight)
    words = _with_a_jump(page, words, subline, room if page.width <= page.height * WIDE_FROM else room - block, page.height * MOST_FOOTER_HEIGHT, fitted)
    # The block as a whole sits a little above the middle of the room it has, which is where the eye settles first.
    together = mark + fitted.height + gap + (words.height if words else 0)
    top = margin + max(0, round((bottom_of_words - margin - together) * 0.42))
    if not highlight:
        _accent_mark(page, margin, top)
    end = _set_lines(page, fitted, "headline", margin, top + mark, words_colour, ground, highlight)
    if words:
        _set_lines(page, words, "subline", margin, end + gap, words_colour)
    if brand.style == TOUCHSTONE:
        _place_logo(page, logo_side, page.width - margin, page.height - margin)
    else:
        page.draw.rectangle((page.width - block, page.height - block, page.width, page.height), fill=rgb(brand.colors["paper"]))
        _place_logo(page, logo_side, page.width - clear, page.height - clear)


def _focus(picture: Image.Image) -> tuple[float, float]:
    # Where the detail in a picture is, as shares of its width and height, so a crop keeps the thing the picture is of. With no detail at all, the middle.
    small = picture.convert("L").resize((64, 64))
    pixels = small.load()
    across, down, total = 0.0, 0.0, 0.0
    for y in range(63):
        for x in range(63):
            weight = abs(pixels[x + 1, y] - pixels[x, y]) + abs(pixels[x, y + 1] - pixels[x, y])
            across, down, total = across + weight * x, down + weight * y, total + weight
    return (across / total / 63, down / total / 63) if total else (0.5, 0.5)


def _cover(page: Page, picture: Image.Image, visible: tuple[int, int, int, int]) -> None:
    # The picture across the whole page, moved so that what it is of sits in the middle of the part the panel leaves clear.
    focus_x, focus_y = _focus(picture)
    scale = max(page.width / picture.width, page.height / picture.height)
    wide, high = math.ceil(picture.width * scale), math.ceil(picture.height * scale)
    left = min(max((visible[0] + visible[2]) / 2 - focus_x * wide, page.width - wide), 0)
    top = min(max((visible[1] + visible[3]) / 2 - focus_y * high, page.height - high), 0)
    page.canvas.paste(picture.resize((wide, high), Image.LANCZOS), (round(left), round(top)))


def full_bleed(page: Page, headline: str, subline: str, highlight: str, picture: Image.Image) -> None:
    """The picture across the whole page, and the words and logo together on one clean panel of the paper colour, so no word is ever on the picture."""
    brand, margin = page.brand, page.margin
    wide = page.width > page.height * WIDE_FROM
    logo_side = round(page.unit * PANEL_LOGO_SHARE)
    pad = max(logo_side // LOGO_CLEAR + round(page.unit * 0.01), round(page.unit * 0.05))
    panel_wide = round((page.width - 2 * margin) * 0.52) if wide else page.width - 2 * margin
    room = panel_wide - 2 * pad
    tall = page.height > page.width * WIDE_FROM
    most = page.height - 2 * margin if wide else page.height * (MOST_TALL_PANEL_HEIGHT if tall else MOST_PANEL_HEIGHT)
    # The headline has the panel's whole width, with the subline and the logo in a row under it.
    words = _words_under(page, subline, room - logo_side - pad, most * 0.4)
    foot = max(logo_side, words.height if words else 0)
    gap = round(pad * 0.8)
    fitted = _fit(page, headline, "headline", room, most - 2 * pad - gap - foot, PANEL_MOST, LEAST_HEADLINE, HEADLINE_PITCH, tight=True, highlight=highlight)
    words = _with_a_jump(page, words, subline, room - logo_side - pad, most * 0.4, fitted)
    foot = max(logo_side, words.height if words else 0)
    panel_high = 2 * pad + fitted.height + gap + foot
    panel = [margin, page.height - margin - panel_high, margin + panel_wide, page.height - margin]
    _cover(page, picture, (panel[2], 0, page.width, page.height) if wide else (0, 0, page.width, panel[1]))
    paper = brand.colors["paper"]
    page.draw.rectangle(panel, fill=rgb(paper))
    page.panel = panel
    _set_lines(page, fitted, "headline", panel[0] + pad, panel[1] + pad, heading_colour(brand), paper, highlight)
    if words:
        _set_lines(page, words, "subline", panel[0] + pad, panel[3] - pad - words.height, brand.colors["ink"])
    _place_logo(page, logo_side, panel[2] - pad, panel[3] - pad)


def new_page(brand: Brand, width: int, height: int, ground: str) -> Page:
    return Page(brand, width, height, Image.new("RGB", (width, height), rgb(ground)))

