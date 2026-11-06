"""Which sticker goes with which moment, per the business pack's sticker_mode, redrawn in a brand's colours."""

import colorsys
import statistics
import tempfile
from pathlib import Path

from PIL import Image

from foundry.brand import Brand, load_brand_dir

STICKERS = Path(__file__).resolve().parents[2] / "stickers"
MADE_STICKERS = Path(tempfile.gettempdir()) / "foundry-stickers"
EVENTS = {"brief_received", "working", "needs_input", "approved", "shipped", "revise", "blocked", "celebrate", "wave"}
SUBTLE = {"needs_input", "approved", "shipped", "blocked"}
ACCESSORY_WORDS = {"builder": "hard_hat", "construction": "hard_hat", "cafe": "cup", "café": "cup", "restaurant": "cup"}
OUTLINE = (32, 12, 4)
SKIN = (251, 182, 114)
# Smith's own colours, by hue in degrees. The stop sign's red sits outside the bandana's range, so it stays red.
BANDANA_HUES, APRON_HUES = (330, 358), (14, 30)
BANDANA_VALUE, APRON_VALUE = 0.72, 0.58
# Drawn in cells on the sprites' own grid. # is the outline, a the brand's main colour, s a lighter shade, c the paper colour.
HARD_HAT = """
...........########...........
.........##aaaaaaaa##.........
.......##aaaassssaaaa##.......
......#aaaaaassssaaaaaa#......
.....#aaaaaaassssaaaaaaa#.....
....#aaaaaaaassssaaaaaaaa#....
....#aaaaaaaassssaaaaaaaa#....
...#aaaaaaaaassssaaaaaaaaa#...
...#aaaaaaaaassssaaaaaaaaa#...
...#aaaaaaaaassssaaaaaaaaa#...
...#aaaaaaaaassssaaaaaaaaa#...
..##########################..
.#ssssssssssssssssssssssssss#.
.#aaaaaaaaaaaaaaaaaaaaaaaaaa#.
..##########################..
"""
CUP = """
....s...s....
...s...s.....
....s...s....
.............
###########..
#ccccccccc###
#ccccccccc#.#
#aaaaaaaaa#.#
#aaaaaaaaa###
#aaaaaaaaa#..
#ccccccccc#..
.#ccccccc#...
..#######....
"""


def sticker_for(event: str, mode: str, pack: str = "base") -> Path | None:
    if event not in EVENTS or mode == "off" or (mode == "subtle" and event not in SUBTLE):
        return None
    for folder in (pack, "base"):
        path = STICKERS / folder / f"{event}.png"
        if path.exists():
            return path
    return None


def accessory_for(business_type: str) -> str | None:
    words = business_type.casefold().split()
    return next((accessory for word, accessory in ACCESSORY_WORDS.items() if word in words), None)


def mode_for(brand: Brand, default: str) -> str:
    # A kit says how much suits the company, unless whoever runs Foundry has turned stickers off.
    return "off" if default == "off" else brand.stickers or default


def branded_sticker(event: str, mode: str, brand_dir: Path | str, out_dir: Path | str = MADE_STICKERS) -> Path | None:
    folder = Path(brand_dir)
    brand = load_brand_dir(folder)
    base = sticker_for(event, mode_for(brand, mode))
    if base is None:
        return None
    path = Path(out_dir) / folder.name / base.name
    if path.exists() and path.stat().st_mtime >= (folder / "kit.md").stat().st_mtime:
        return path
    image = Image.open(base).convert("RGBA")
    _recolour(image, _rgb(brand.colors["accent"]), _rgb(brand.colors["primary"]))
    accessory = accessory_for(brand.business_type)
    if accessory == "hard_hat":
        _put_on_head(image, _rgb(brand.colors["primary"]))
    elif accessory == "cup":
        _put_on_ground(image, _rgb(brand.colors["accent"]), _rgb(brand.colors["paper"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[start : start + 2], 16) for start in (1, 3, 5))


def _shade(colour: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(min(255, round(part * ratio)) for part in colour)


def _recolour(image: Image.Image, bandana: tuple[int, int, int], apron: tuple[int, int, int]) -> None:
    pixels = image.load()
    swaps = {}
    for x in range(image.width):
        for y in range(image.height):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if (r, g, b) not in swaps:
                swaps[r, g, b] = _swap_for(r, g, b, bandana, apron)
            pixels[x, y] = (*swaps[r, g, b], a)


def _swap_for(r: int, g: int, b: int, bandana: tuple[int, int, int], apron: tuple[int, int, int]) -> tuple[int, int, int]:
    hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    degrees = hue * 360
    if BANDANA_HUES[0] <= degrees <= BANDANA_HUES[1] and saturation > 0.45 and value > 0.3:
        return _shade(bandana, value / BANDANA_VALUE)
    # Brighter browns are skin and darker ones are hair, so only the middle is the apron.
    if APRON_HUES[0] <= degrees <= APRON_HUES[1] and saturation > 0.4 and 0.3 < value < 0.67:
        return _shade(apron, value / APRON_VALUE)
    return r, g, b


def _stamp(image: Image.Image, grid: str, left: int, top: int, cell: int, colours: dict[str, tuple[int, int, int]]) -> None:
    for row, line in enumerate(grid.strip().splitlines()):
        for column, mark in enumerate(line):
            if mark in colours:
                image.paste((*colours[mark], 255), (left + column * cell, top + row * cell, left + (column + 1) * cell, top + (row + 1) * cell))


def _head_of(image: Image.Image) -> tuple[int, int]:
    """Where the middle of the face and the forehead are. Hands are skin too, but the face has most of it."""
    pixels = image.load()
    skin = [
        (x, y)
        for x in range(image.width)
        for y in range(image.height)
        if pixels[x, y][3] and all(abs(part - want) < 16 for part, want in zip(pixels[x, y][:3], SKIN, strict=True))
    ]
    centre = round(statistics.median(x for x, _ in skin))
    return centre, min(y for x, y in skin if abs(x - centre) < 50)


def _put_on_head(image: Image.Image, colour: tuple[int, int, int]) -> None:
    centre, forehead = _head_of(image)
    cell, rows, columns = 8, len(HARD_HAT.strip().splitlines()), len(HARD_HAT.strip().splitlines()[0])
    _stamp(image, HARD_HAT, centre - columns * cell // 2, max(0, forehead - rows * cell), cell, {"#": OUTLINE, "a": colour, "s": _shade(colour, 1.5)})


def _put_on_ground(image: Image.Image, colour: tuple[int, int, int], paper: tuple[int, int, int]) -> None:
    cell, rows, columns = 6, len(CUP.strip().splitlines()), len(CUP.strip().splitlines()[0])
    bottom = image.getbbox()[3]
    _stamp(image, CUP, image.width - columns * cell - 8, bottom - rows * cell, cell, {"#": OUTLINE, "a": colour, "c": paper, "s": _shade(paper, 0.8)})
