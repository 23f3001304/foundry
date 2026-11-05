"""Draws the reversed logo of each demo kit whose logo is lost on its own colour, from that logo, in code.

uv run python tools/draw_reversed_logos.py [folder]

With no folder it writes into brands/. The logo's dark parts become the kit's paper colour, its accent stays, and what was only there to sit behind them goes, so the ground shows through.
These are all fictional kits. A real client's reversed logo comes from the client, and Foundry never recolours one on the fly. Every step is fixed, so drawing again gives the same files.
"""

import sys
from pathlib import Path

import numpy as np
from foundry.brand import LOGO_ON_DARK, load_brand_dir
from foundry.tools.layout import rgb
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
# What each logo is drawn in: the colour that goes, the dark colour that turns to paper, and the colour that stays. A logo's dark colour may not be one the kit names, as with the cafe's brown.
RECIPES = {
    "demo-it-firm": ("#FFFFFF", "#0F4C5C", "#D9A52E"),
    "demo-agency": ("#F8F4EC", "#23284F", "#F28C28"),
    "demo-agency-client-a": ("#C4161F", "#1C1233", "#FFC82E"),
    "demo-agency-client-b": ("#F5EEDF", "#2F4A3A", "#B98A3E"),
    "lalten-cafe": ("#FFFFFF", "#5A2A12", None),
    "shilagate-homes": ("#FFFFFF", "#2C4A5E", "#9A8F7E"),
}
# Below this share of a colour, a pixel is only the file's own noise, on a logo a model drew.
NOISE = 0.08


def reversed_logo(slug: str) -> Image.Image:
    goes, dark, stays = RECIPES[slug]
    paper = np.array(rgb(load_brand_dir(REPO / "brands" / slug).colors["paper"]), float)
    with Image.open(REPO / "brands" / slug / "logo.png") as logo:
        pixels = np.array(logo.convert("RGBA"), float)
    start, parts = np.array(rgb(goes), float), [np.array(rgb(dark), float)]
    if stays:
        parts.append(np.array(rgb(stays), float))
    # Each pixel as a mix of those colours, so a soft edge between two of them stays a soft edge.
    towards = np.stack([part - start for part in parts], axis=1)
    amounts = np.clip((pixels[..., :3] - start) @ np.linalg.pinv(towards).T, 0, 1)
    amounts[amounts < NOISE] = 0
    total = amounts.sum(axis=-1, keepdims=True)
    over = np.maximum(total, 1)
    amounts, total = amounts / over, np.minimum(total, 1)
    kept = amounts[..., 1:2] * np.array(rgb(stays), float) if stays else 0
    colour = (amounts[..., :1] * paper + kept) / np.maximum(total, 1e-6)
    alpha = pixels[..., 3:] * total
    # Where nothing is left, the pixel carries no colour.
    colour[alpha[..., 0] == 0] = 0
    return Image.fromarray(np.concatenate([colour, alpha], axis=-1).round().astype("uint8"), "RGBA")


def draw_all(folder: Path) -> list[Path]:
    made = []
    for slug in RECIPES:
        path = folder / slug / LOGO_ON_DARK
        path.parent.mkdir(parents=True, exist_ok=True)
        reversed_logo(slug).save(path, optimize=True)
        made.append(path)
    return made


if __name__ == "__main__":
    for path in draw_all(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "brands"):
        print(path)
