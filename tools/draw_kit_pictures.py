"""Draws a picture in code for the three demo brands that had none, so a full-page poster works for them too. No image model made them, and they hold no words.

uv run python tools/draw_kit_pictures.py [folder]

With no folder it writes into brands/. Every shape is fixed, so drawing again gives the same files.
"""

import io
import math
import sys
from pathlib import Path

from foundry.brand import load_brand_dir
from foundry.tools import touchstone
from foundry.tools.layout import mix, rgb
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
SIDE, STONE_SIDE, SMOOTHING = 2800, 1800, 2


def _colours(slug: str) -> dict[str, str]:
    return load_brand_dir(REPO / "brands" / slug).colors


def first_light() -> Image.Image:
    # Bhorvela Studio: first light. The sun comes up out of still water, in steps of colour and no gradient, as in its logo.
    colours = _colours("demo-agency")
    side = SIDE * SMOOTHING
    image = Image.new("RGB", (side, side), rgb(colours["primary"]))
    draw = ImageDraw.Draw(image)
    horizon = round(side * 0.52)
    steps = 6
    for step in range(steps):
        draw.rectangle((0, round(horizon * step / steps), side, horizon), fill=rgb(mix(colours["paper"], colours["accent"], 0.42 * step / steps)))
    centre, radius = side / 2, side * 0.2
    draw.pieslice((centre - radius, horizon - radius, centre + radius, horizon + radius), 180, 360, fill=rgb(colours["accent"]))
    draw.rectangle((0, horizon, side, side), fill=rgb(colours["primary"]))
    # Three lines of light on the water, close under the sun, where a panel of words low on the page will not cut across them.
    for number, length in enumerate((0.34, 0.22, 0.11)):
        y = horizon + side * (0.016 + number * 0.022)
        half = side * length / 2
        draw.rounded_rectangle((centre - half, y, centre + half, y + side * 0.008), radius=side * 0.004, fill=rgb(mix(colours["accent"], colours["primary"], 0.1 + number * 0.22)))
    return image.resize((SIDE, SIDE), Image.LANCZOS)


def feather() -> Image.Image:
    # Morpankh Systems: morpankh is a peacock's feather. Its quill up the middle, its barbs repeating to the edge of the page, and its eye, as in the firm's logo.
    colours = _colours("demo-it-firm")
    side = SIDE * SMOOTHING
    teal, gold, paper = colours["primary"], colours["accent"], colours["paper"]
    image = Image.new("RGB", (side, side), rgb(teal))
    draw = ImageDraw.Draw(image)
    # The eye is small and a little above the middle, so a wide crop keeps all of it, and so does a square page with a panel over its lower half.
    centre = (side / 2, side * 0.375)
    reach = side * 0.6
    rise = reach * math.tan(math.radians(38))
    for number in range(-8, 40):
        y = side * (0.03 * number)
        tint = mix(teal, paper, 0.1 if number % 2 else 0.2)
        for direction in (-1, 1):
            draw.line((side / 2, y, side / 2 + direction * reach, y - rise), fill=rgb(tint), width=round(side * 0.005))
    draw.line((side / 2, centre[1], side / 2, side), fill=rgb(mix(teal, paper, 0.45)), width=round(side * 0.009))
    for wide, high, colour in ((0.105, 0.135, teal), (0.09, 0.118, gold), (0.062, 0.084, mix(teal, "#000000", 0.25)), (0.032, 0.047, gold)):
        draw.ellipse((centre[0] - side * wide, centre[1] - side * high, centre[0] + side * wide, centre[1] + side * high), fill=rgb(colour))
    return image.resize((SIDE, SIDE), Image.LANCZOS)


def touchstone_rub() -> Image.Image:
    # Kasauti Capital Partners: kasauti is the touchstone. The black stone, and one long rub of gold across it.
    colours = _colours("demo-investment-firm")
    with Image.open(io.BytesIO(touchstone.stone(colours["paper"]))) as stone:
        scale = STONE_SIDE / min(stone.size)
        ground = stone.convert("RGB").resize((math.ceil(stone.width * scale), math.ceil(stone.height * scale)), Image.LANCZOS)
    left = (ground.width - STONE_SIDE) // 2
    ground = ground.crop((left, 0, left + STONE_SIDE, STONE_SIDE)).convert("RGBA")
    art, _ = touchstone.cover_rub(760, 86, colours["accent"])
    with Image.open(io.BytesIO(art)) as rub:
        long = rub.convert("RGBA").resize((STONE_SIDE * 3 // 2, STONE_SIDE * 3 // 2 * rub.height // rub.width), Image.LANCZOS)
    turned = long.rotate(24, expand=True, resample=Image.BICUBIC)
    at = ((STONE_SIDE - turned.width) // 2, round(STONE_SIDE * 0.42) - turned.height // 2)
    layer = Image.new("RGBA", ground.size, (0, 0, 0, 0))
    layer.paste(turned, at, turned)
    ground.alpha_composite(layer)
    return ground.convert("RGB").quantize(128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")


PICTURES = {"demo-agency": first_light, "demo-it-firm": feather, "demo-investment-firm": touchstone_rub}


def draw_all(folder: Path) -> list[Path]:
    made = []
    for slug, draw in PICTURES.items():
        path = folder / slug / "hero.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        draw().save(path, optimize=True)
        made.append(path)
    return made


if __name__ == "__main__":
    for path in draw_all(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "brands"):
        print(path)
