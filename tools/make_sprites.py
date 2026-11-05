"""Build the dashboard's sprite sheets from the team's stills and Smith's poses. No new art comes from here: every frame is the same drawing with some of its pixels moved.

Usage: uv run --no-project --with pillow --with numpy tools/make_sprites.py
Each sheet is one row of square frames, and its first frame is the still the page rests on.
The stylesheet names each sheet and how many frames it has, and DESIGN.md says what plays when.
"""

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "foundry" / "dashboard" / "static" / "sprites"
SOURCE = 128  # The stills are 512 across, and four of those pixels are one of the drawing's own.
RIM = (64, 64, 70, 255)  # A line a pixel wide round each figure, because dark hair would be lost on a dark card.
LIME = np.array((217, 242, 63))

# Where each character's eyes are in the 512 still, and a bit of their skin to shut them with.
EYES = {
    "smith": ((194, 172, 236, 212), (272, 172, 312, 212), (254, 196)),
    "apprentice": ((186, 170, 224, 208), (262, 170, 302, 208), (243, 192)),
    "reviewer": ((186, 186, 232, 230), (280, 186, 322, 230), (256, 208)),
    "designer": ((192, 158, 234, 196), (274, 158, 314, 196), (254, 186)),
}


def load(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA").resize((SOURCE, SOURCE), Image.NEAREST))


def tint_props(cells: np.ndarray) -> np.ndarray:
    # A pose's blue or green prop takes the dashboard's one accent, so the sprites don't bring back the colours the pages gave up. The characters' own clothes are left as they are.
    out = cells.copy()
    red, green, blue = (cells[..., channel].astype(int) for channel in range(3))
    prop = (cells[..., 3] > 0) & (((blue > red + 40) & (blue >= green)) | ((green > red + 40) & (green > blue + 40)))
    light = (red * 0.3 + green * 0.59 + blue * 0.11) / 150
    out[prop, :3] = np.clip(LIME[None, :] * np.clip(light[prop], 0.45, 1.2)[:, None], 0, 255).astype("uint8")
    return out


def shut_eyes(cells: np.ndarray, character: str) -> np.ndarray:
    left, right, skin = EYES[character]
    out = cells.copy()
    colour = cells[skin[1] // 4, skin[0] // 4].copy()
    for x0, y0, x1, y1 in (left, right):
        x0, y0, x1, y1 = x0 // 4, y0 // 4, x1 // 4, y1 // 4
        out[y0:y1, x0:x1] = colour
        out[(y0 + y1) // 2, x0:x1] = (40, 28, 24, 255)
    return out


def shrink(cells: np.ndarray, size: int) -> np.ndarray:
    # Each new pixel takes the colour that covers most of it. A dark outline counts for more, because it is what keeps a small figure readable.
    out = np.zeros((size, size, 4), "uint8")
    step = SOURCE / size
    for row in range(size):
        y0, y1 = row * step, (row + 1) * step
        for col in range(size):
            x0, x1 = col * step, (col + 1) * step
            weights: dict[tuple, float] = {}
            for y in range(int(y0), min(int(np.ceil(y1)), SOURCE)):
                over_y = min(y + 1, y1) - max(y, y0)
                for x in range(int(x0), min(int(np.ceil(x1)), SOURCE)):
                    over = over_y * (min(x + 1, x1) - max(x, x0))
                    colour = tuple(int(value) for value in cells[y, x])
                    weights[colour] = weights.get(colour, 0.0) + over
            solid = {colour: weight for colour, weight in weights.items() if colour[3] > 0}
            total = sum(weights.values())
            if sum(solid.values()) < total * 0.45:
                continue
            ink = {colour: weight for colour, weight in solid.items() if sum(colour[:3]) < 150}
            pool = ink if sum(ink.values()) >= sum(solid.values()) * 0.34 else solid
            out[row, col] = max(pool, key=pool.get)
    return out


def box_of(size: int, left: float, top: float, right: float, bottom: float) -> tuple[int, int, int, int]:
    return int(left * size), int(top * size), int(right * size), int(bottom * size)


def moved(frame: np.ndarray, box: tuple[int, int, int, int], dx: int = 0, dy: int = 0) -> np.ndarray:
    # What is in the box, moved by whole pixels and laid over what stays. Only drawn pixels move, so the box itself never shows.
    x0, y0, x1, y1 = box
    out = frame.copy()
    piece = frame[y0:y1, x0:x1].copy()
    out[y0:y1, x0:x1][piece[..., 3] > 0] = 0
    height, width = frame.shape[:2]
    ys, xs = np.nonzero(piece[..., 3] > 0)
    for y, x in zip(ys, xs, strict=True):
        new_y, new_x = y + y0 + dy, x + x0 + dx
        if 0 <= new_y < height and 0 <= new_x < width:
            out[new_y, new_x] = piece[y, x]
    return out


def whole(frame: np.ndarray, dx: int = 0, dy: int = 0) -> np.ndarray:
    size = frame.shape[0]
    return moved(frame, (0, 0, size, size), dx, dy)


def right_foot(frame: np.ndarray) -> tuple[int, int, int, int]:
    # The last run of drawn columns along the bottom of the figure.
    size = frame.shape[0]
    rows = np.nonzero((frame[..., 3] > 0).any(axis=1))[0]
    bottom = int(rows.max()) + 1
    top = bottom - max(size // 16, 3)
    columns = (frame[top:bottom, :, 3] > 0).any(axis=0)
    xs = np.nonzero(columns)[0]
    end = int(xs.max()) + 1
    start = end - 1
    while start > 0 and columns[start - 1]:
        start -= 1
    return start, top, end, bottom


def specks(frame: np.ndarray) -> np.ndarray:
    # Drawn pixels that aren't joined to the figure: the confetti.
    size = frame.shape[0]
    solid = frame[..., 3] > 0
    seen = np.zeros_like(solid)
    biggest: list[tuple[int, int]] = []
    groups = []
    for y, x in zip(*np.nonzero(solid), strict=True):
        if seen[y, x]:
            continue
        queue, group = deque([(int(y), int(x))]), []
        seen[y, x] = True
        while queue:
            cy, cx = queue.popleft()
            group.append((cy, cx))
            for ny in range(max(cy - 1, 0), min(cy + 2, size)):
                for nx in range(max(cx - 1, 0), min(cx + 2, size)):
                    if solid[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        groups.append(group)
        biggest = max(biggest, group, key=len)
    found = np.zeros_like(solid)
    for group in groups:
        if group is not biggest:
            for y, x in group:
                found[y, x] = True
    return found


def with_rim(frame: np.ndarray) -> np.ndarray:
    solid = frame[..., 3] > 0
    grown = solid.copy()
    grown[1:] |= solid[:-1]
    grown[:-1] |= solid[1:]
    grown[:, 1:] |= solid[:, :-1]
    grown[:, :-1] |= solid[:, 1:]
    out = frame.copy()
    out[grown & ~solid] = RIM
    return out


# What plays. Each returns the frames, the first of them the still.


def still(small: np.ndarray, unit: int) -> list[np.ndarray]:
    return [small]


def idle(character: str):
    def frames(small: np.ndarray, unit: int, source: np.ndarray) -> list[np.ndarray]:
        size = small.shape[0]
        blink = shrink(shut_eyes(source, character), size)
        body = box_of(size, 0, 0, 1, 0.62)
        return [small, blink, small, moved(small, body, dy=unit)]

    return frames


def shake(small: np.ndarray, unit: int) -> list[np.ndarray]:
    return [small, whole(small, dx=-unit), small, whole(small, dx=unit)]


def tap(small: np.ndarray, unit: int) -> list[np.ndarray]:
    # The foot taps and the question mark bobs with it.
    size = small.shape[0]
    mark = box_of(size, 0.645, 0.08, 0.86, 0.38)
    up = moved(moved(small, right_foot(small), dy=-unit), mark, dy=-unit)
    return [small, up, small, up]


def cheer(small: np.ndarray, unit: int) -> list[np.ndarray]:
    # A hop, with the confetti falling past it.
    bits = specks(small)
    figure = small.copy()
    figure[bits] = 0
    confetti = small.copy()
    confetti[~bits] = 0
    frames = []
    for place, lift in enumerate((0, 1, 2, 3, 2, 1)):
        frame = whole(figure, dy=-lift * unit)
        falling = whole(confetti, dy=place * unit)
        frame[falling[..., 3] > 0] = falling[falling[..., 3] > 0]
        frames.append(frame)
    return frames


def nod(small: np.ndarray, unit: int) -> list[np.ndarray]:
    size = small.shape[0]
    head = box_of(size, 0, 0, 1, 0.5)
    down = moved(small, head, dy=unit)
    return [small, down, small, down]


def wave(small: np.ndarray, unit: int) -> list[np.ndarray]:
    size = small.shape[0]
    hand = box_of(size, 0.23, 0.34, 0.37, 0.47)
    return [small, moved(small, hand, dx=-unit), small, moved(small, hand, dx=unit)]


# Only these have a coloured prop. Everyone else keeps every colour they were drawn in.
TINTED = ("tap", "nod")
SHEETS = {
    "apprentice": ("assets/team/apprentice.png", idle("apprentice"), (48, 96), "apprentice"),
    "designer": ("assets/team/designer.png", idle("designer"), (48, 96), "designer"),
    "reviewer": ("assets/team/reviewer.png", idle("reviewer"), (48, 96), "reviewer"),
    "smith": ("assets/team/smith.png", idle("smith"), (48, 96), "smith"),
    "shipped": ("stickers/base/shipped.png", still, (48, 96), None),
    "blocked": ("stickers/base/blocked.png", shake, (48, 96), None),
    "tap": ("stickers/base/needs_input.png", tap, (48, 96), None),
    "cheer": ("stickers/base/celebrate.png", cheer, (48, 96), None),
    "nod": ("stickers/base/approved.png", nod, (48,), None),
    "wave": ("stickers/base/wave.png", wave, (96,), None),
}


def build(name: str, source: str, play, size: int, character: str | None) -> tuple[Path, int]:
    cells = load(ROOT / source)
    if name in TINTED:
        cells = tint_props(cells)
    small = shrink(cells, size)
    unit = size // 48
    frames = play(small, unit, cells) if character else play(small, unit)
    frames = [with_rim(frame) for frame in frames]
    sheet = np.concatenate(frames, axis=1)
    image = Image.fromarray(sheet, "RGBA").quantize(colors=48, method=Image.FASTOCTREE, dither=Image.NONE)
    path = OUT / f"{name}-{size}.png"
    image.save(path, optimize=True)
    return path, len(frames)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (source, play, sizes, character) in SHEETS.items():
        for size in sizes:
            path, count = build(name, source, play, size, character)
            print(f"{path.relative_to(ROOT)}: {count} frames, {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
