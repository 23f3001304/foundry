"""Draws the logos and the picture of the marketing agency demo's three brands in code with Pillow, so no image model made them.

uv run python tools/draw_agency_art.py [folder]

With no folder it writes into brands/. Every shape is fixed, so drawing again gives the same files.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
LOGO_SIDE, HERO_SIZE, SMOOTHING = 1024, (1600, 900), 3


def _rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[start:start + 2], 16) for start in (1, 3, 5))


def _canvas(side: int) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    size = side * SMOOTHING
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), SMOOTHING


def _disc(draw: ImageDraw.ImageDraw, centre: tuple[float, float], radius: float, fill: tuple) -> None:
    draw.ellipse((centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius), fill=fill)


def _finish(image: Image.Image) -> Image.Image:
    return image.resize((LOGO_SIDE, LOGO_SIDE), Image.LANCZOS)


def _polar(centre: tuple[float, float], radius: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)


# Bhorvela Studio: the sun just over the horizon, for first light.
AGENCY = {"primary": "#23284F", "accent": "#F28C28", "paper": "#F8F4EC"}


def agency_logo() -> Image.Image:
    image, draw, scale = _canvas(LOGO_SIDE)
    side = LOGO_SIDE * scale
    centre = (side / 2, side / 2)
    indigo, orange, paper = (_rgb(AGENCY[name]) for name in ("primary", "accent", "paper"))
    _disc(draw, centre, side * 0.49, (*indigo, 255))
    _disc(draw, centre, side * 0.43, (*paper, 255))
    horizon = side * 0.60
    sun = side * 0.20
    draw.pieslice((centre[0] - sun, horizon - sun, centre[0] + sun, horizon + sun), 180, 360, fill=(*orange, 255))
    for step in range(9):
        degrees = 200 + step * 17.5
        draw.line((*_polar((centre[0], horizon), sun * 1.25, degrees), *_polar((centre[0], horizon), sun * 1.75, degrees)), fill=(*orange, 255), width=int(side * 0.022))
    for number, length in enumerate((0.60, 0.46, 0.32)):
        y = horizon + side * (0.045 + number * 0.055)
        draw.rounded_rectangle((centre[0] - side * length / 2, y, centre[0] + side * length / 2, y + side * 0.024), radius=side * 0.012, fill=(*indigo, 255))
    # The sun's flat edge rests on the first line.
    draw.rectangle((centre[0] - side * 0.30, horizon - side * 0.004, centre[0] + side * 0.30, horizon + side * 0.012), fill=(*indigo, 255))
    return _finish(image)


# Phatakha Pop: a firecracker's burst.
POP = {"primary": "#C4161F", "accent": "#FFC82E", "ink": "#1C1233", "paper": "#FFF4E0"}


def pop_logo() -> Image.Image:
    image, draw, scale = _canvas(LOGO_SIDE)
    side = LOGO_SIDE * scale
    centre = (side / 2, side / 2)
    red, yellow, ink = (_rgb(POP[name]) for name in ("primary", "accent", "ink"))
    _disc(draw, centre, side * 0.49, (*ink, 255))
    _disc(draw, centre, side * 0.45, (*red, 255))
    points = 14
    star = [_polar(centre, side * (0.40 if point % 2 == 0 else 0.20), -90 + point * 360 / (points * 2)) for point in range(points * 2)]
    draw.polygon(star, fill=(*yellow, 255))
    _disc(draw, centre, side * 0.13, (*ink, 255))
    _disc(draw, centre, side * 0.075, (*red, 255))
    return _finish(image)


# Ambaryug Teas: two leaves and a bud.
TEA = {"primary": "#2F4A3A", "accent": "#B98A3E", "ink": "#231B14", "paper": "#F5EEDF"}


def _leaf(base: tuple[float, float], length: float, width: float, degrees: float) -> list[tuple[float, float]]:
    # A pointed oval from its base along the angle, wider a third of the way along.
    angle = math.radians(degrees)
    along, across = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
    top, bottom = [], []
    for step in range(41):
        t = step / 40
        half = width * math.sin(math.pi * t) ** 0.85 * (1.15 - 0.45 * t)
        point = (base[0] + along[0] * length * t, base[1] + along[1] * length * t)
        top.append((point[0] + across[0] * half, point[1] + across[1] * half))
        bottom.append((point[0] - across[0] * half, point[1] - across[1] * half))
    return top + bottom[::-1]


def tea_logo() -> Image.Image:
    image, draw, scale = _canvas(LOGO_SIDE)
    side = LOGO_SIDE * scale
    centre = (side / 2, side / 2)
    green, amber, paper = (_rgb(TEA[name]) for name in ("primary", "accent", "paper"))
    _disc(draw, centre, side * 0.49, (*amber, 255))
    _disc(draw, centre, side * 0.455, (*paper, 255))
    _disc(draw, centre, side * 0.43, (*green, 255))
    _disc(draw, centre, side * 0.415, (*paper, 255))
    # The tea pluck: a bud at the top of a stem, and the two young leaves under it, one a little lower than the other.
    foot, tip = centre[1] + side * 0.27, centre[1] - side * 0.10
    stem = side * 0.018
    draw.rounded_rectangle((centre[0] - stem / 2, tip, centre[0] + stem / 2, foot), radius=stem / 2, fill=(*green, 255))
    plucks = (
        ((centre[0], tip + side * 0.02), 0.30, 0.055, -90),
        ((centre[0], tip + side * 0.13), 0.31, 0.085, -90 - 55),
        ((centre[0], tip + side * 0.21), 0.31, 0.085, -90 + 55),
    )
    for base, length, width, degrees in plucks:
        draw.polygon(_leaf(base, side * length, side * width, degrees), fill=(*green, 255))
        draw.line((*base, *_polar(base, side * length * 0.85, degrees)), fill=(*paper, 255), width=int(side * 0.006))
    draw.rounded_rectangle((centre[0] - side * 0.16, foot + side * 0.02, centre[0] + side * 0.16, foot + side * 0.045), radius=side * 0.012, fill=(*amber, 255))
    return _finish(image)


def _scene(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width * SMOOTHING, height * SMOOTHING))
    return image, ImageDraw.Draw(image)


def _shrunk(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.LANCZOS)


def pop_hero() -> Image.Image:
    width, height = HERO_SIZE
    image, draw = _scene(width, height)
    scale = SMOOTHING
    red, yellow, ink, paper = (_rgb(POP[name]) for name in ("primary", "accent", "ink", "paper"))
    deep = tuple(int(part * 0.78) for part in red)
    draw.rectangle((0, 0, width * scale, height * scale), fill=ink)
    centre = (width * 0.5 * scale, height * 0.52 * scale)
    reach = width * scale
    wedges = 28
    for wedge in range(wedges):
        start = wedge * 360 / wedges
        draw.polygon([centre, _polar(centre, reach, start), _polar(centre, reach, start + 360 / wedges)], fill=red if wedge % 2 == 0 else deep)
    for radius, colour in ((0.34, ink), (0.30, yellow), (0.22, red), (0.17, paper), (0.10, yellow)):
        _disc(draw, centre, height * radius * scale, colour)
    sparks = ((0.12, 0.2, 0.05), (0.88, 0.18, 0.06), (0.2, 0.78, 0.04), (0.82, 0.8, 0.05), (0.05, 0.55, 0.03), (0.95, 0.5, 0.035), (0.33, 0.1, 0.03), (0.68, 0.92, 0.03))
    for x, y, size in sparks:
        middle = (width * x * scale, height * y * scale)
        radius = height * size * scale
        draw.polygon([_polar(middle, radius if point % 2 == 0 else radius * 0.28, -90 + point * 45) for point in range(8)], fill=yellow)
    return _shrunk(image, HERO_SIZE)


def tea_hero() -> Image.Image:
    width, height = HERO_SIZE
    image, draw = _scene(width, height)
    scale = SMOOTHING
    green, amber, ink, paper = (_rgb(TEA[name]) for name in ("primary", "accent", "ink", "paper"))
    sky_top, sky_low = _rgb("#EFE3C8"), _rgb("#F8F1E1")
    for row in range(height * scale):
        mix = row / (height * scale * 0.62)
        mix = min(mix, 1.0)
        draw.line((0, row, width * scale, row), fill=tuple(round(top + (low - top) * mix) for top, low in zip(sky_top, sky_low)))
    _disc(draw, (width * 0.70 * scale, height * 0.30 * scale), height * 0.11 * scale, amber)
    # Ridges, far to near, each a slow wave, going from a pale green to the estate's own.
    ridges = ((0.50, 0.050, 0.9, "#A9B79A"), (0.58, 0.060, 1.3, "#86A07F"), (0.67, 0.065, 0.8, "#5E7F62"), (0.77, 0.050, 1.1, "#3F6149"))
    for base, rise, wavelength, colour in ridges:
        top = [(x, (height * (base - rise * math.sin(x / (width * scale) * math.pi * 2 * wavelength + base * 9))) * scale) for x in range(0, width * scale + 1, 6)]
        draw.polygon([*top, (width * scale, height * scale), (0, height * scale)], fill=_rgb(colour))
    # The nearest slope, in terraces of tea bushes: each row is a band that the next one overlaps, in two greens, with a thin dark edge.
    for terrace in range(7):
        level = 0.78 + terrace * 0.036
        line = [(x, (height * (level + 0.025 * math.sin(x / (width * scale) * math.pi * 2.2 + terrace * 0.5))) * scale) for x in range(0, width * scale + 1, 6)]
        draw.polygon([*line, (width * scale, height * scale), (0, height * scale)], fill=green if terrace % 2 == 0 else _rgb("#3A5B45"))
        draw.line(line, fill=ink, width=int(height * 0.004 * scale))
    return _shrunk(image, HERO_SIZE)


def draw_all(folder: Path) -> list[Path]:
    made = []
    for slug, name, image in (
        ("demo-agency", "logo.png", agency_logo()),
        ("demo-agency-client-a", "logo.png", pop_logo()),
        ("demo-agency-client-a", "hero.png", pop_hero()),
        ("demo-agency-client-b", "logo.png", tea_logo()),
        ("demo-agency-client-b", "hero.png", tea_hero()),
    ):
        path = folder / slug / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
        made.append(path)
    return made


if __name__ == "__main__":
    for path in draw_all(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "brands"):
        print(path)
