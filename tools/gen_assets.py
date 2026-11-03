"""Generate Foundry's art with Gemini image models on Vertex AI, then cut it to size.

Usage: uv run --no-project --with pillow --with numpy tools/gen_assets.py [name ...]
Needs: `gcloud auth application-default login` and GOOGLE_CLOUD_PROJECT.
With no names it makes every asset that doesn't exist yet. Raw output stays in assets/raw/.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from math import ceil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MODEL = os.environ.get("FOUNDRY_IMAGE_MODEL", "gemini-nano-banana-2.1")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "raw"
GRID, COLOURS, CELL, CANVAS = 115, 30, 4, 512

CHARACTER_STYLE = (
    "Clean flat-colour chibi cartoon with a big head, thick dark outlines, flat colours with a single shadow tone, "
    "simple big eyes and a small friendly mouth. An original character, not based on any existing franchise. "
)
ON_MAGENTA = (
    " Whole body visible with nothing cut off by the frame. Solid flat pure magenta #FF00FF background with no shadow, "
    "no text, no letters, no numbers, and no pink or magenta anywhere in the artwork."
)

TEAM = {
    "smith": "short spiky black hair under a red bandana, welding goggles on the forehead, a brown leather apron over an "
    "orange t-shirt, black trousers, white sneakers, holding a small hammer",
    "apprentice": "a long black braid over one shoulder, welding goggles pushed up on the head, blue denim dungarees over "
    "an orange t-shirt, a tool belt, white sneakers, holding a big spanner",
    "reviewer": "a neat black moustache, a white hard hat, a navy work shirt with rolled sleeves, grey trousers, brown "
    "boots, holding a clipboard and a magnifying glass",
    "designer": "short wavy black hair, a paint-splashed cream apron over a teal kurta, black trousers, white sneakers, "
    "holding a paintbrush and a small colour swatch card",
}

POSES = {
    "brief_received": "holds up a sheet of paper covered in plain horizontal lines, looking pleased.",
    "working": "swings the hammer down onto a small anvil, with bright yellow sparks flying.",
    "needs_input": "scratches their head and looks up at a large blue question mark floating beside them.",
    "approved": "gives a big thumbs up next to a large round green badge with a white check mark.",
    "shipped": "runs forward carrying a brown parcel box, with short speed lines behind them.",
    "revise": "holds a big pencil next to a blue circular arrow, looking thoughtful.",
    "blocked": "stands with both palms raised next to a red octagon sign with a plain white horizontal bar.",
    "celebrate": "jumps with both arms up as orange, yellow, blue and green confetti bursts around them.",
}

LOGO_STYLE = (
    "A clean, original circular emblem logo for a fictional business. Flat vector with no gradients or shadows, "
    "readable at small sizes, centred on a plain white background with nothing else in the frame."
)

ASSETS = {
    **{
        name: {
            "prompt": CHARACTER_STYLE + f"The character has {look}. Front view, standing relaxed and friendly." + ON_MAGENTA,
            "out": f"assets/team/{name}.png",
            "cut": "pixel",
        }
        for name, look in TEAM.items()
    },
    **{
        state: {
            "prompt": "Use the exact same character as the reference image, keeping the same face, hair, bandana, goggles, "
            "apron, clothes, colours and art style. The character " + pose + ON_MAGENTA,
            "refs": ["smith"],
            "out": f"stickers/base/{state}.png",
            "cut": "pixel",
        }
        for state, pose in POSES.items()
    },
    "foundry-logo": {
        "prompt": LOGO_STYLE + " The emblem shows a crucible pouring a single stream of molten orange metal into a square "
        "mould, in charcoal #2B2D33 and molten orange #FF6A1A. No text.",
        "out": "assets/foundry-logo.png",
        "cut": "logo",
    },
    "readme-banner": {
        "prompt": "A wide banner illustration: a stream of tangled, scribbled chat bubbles on the left flows into a glowing "
        "crucible in the centre, and clean finished slides and posters come out on the right. Flat vector, charcoal "
        "#2B2D33 background, molten orange #FF6A1A and warm yellow #FFC24A highlights. No text, letters or logos.",
        "aspect": "21:9",
        "out": "assets/readme-banner.png",
    },
    "lantern-cafe-logo": {
        "prompt": LOGO_STYLE + " The emblem shows a small hanging lantern with a coffee cup as its flame window, in deep "
        "brown #7A3E1D and warm cream. The words 'LANTERN CAFE' run once along the top of the circle in a friendly serif. The bottom of the circle has only a small plain ornament, and no other words appear anywhere.",
        "out": "brands/lantern-cafe/logo.png",
        "cut": "logo",
    },
    "lantern-cafe-hero": {
        "prompt": "A warm, inviting photograph of a small neighbourhood Indian cafe counter at golden hour with brass "
        "lanterns, a chalkboard with no writing, ceramic cups and fresh pastries. No people, no text, no logos or brands.",
        "aspect": "16:9",
        "out": "brands/lantern-cafe/hero.png",
    },
    "lantern-cafe-menu": {
        "prompt": "Overhead photograph of a rustic wooden table with filter coffee in a steel tumbler, masala chai, a "
        "vada pav and a croissant, soft daylight, plenty of empty space on the right. No people, no text, no logos.",
        "aspect": "16:9",
        "out": "brands/lantern-cafe/menu.png",
    },
    "stonegate-homes-logo": {
        "prompt": LOGO_STYLE + " The emblem shows a simple arched stone gateway with a small house inside the arch, in "
        "slate blue #2C4A5E and warm stone grey. The words 'STONEGATE HOMES' run around the circle in a clean sans-serif.",
        "out": "brands/stonegate-homes/logo.png",
        "cut": "logo",
    },
    "stonegate-homes-hero": {
        "prompt": "An architectural photograph of a modern mid-rise residential building in an Indian city at dusk, warm "
        "windows, landscaped entrance, clear sky. No people, no text, no signage, no logos.",
        "aspect": "16:9",
        "out": "brands/stonegate-homes/hero.png",
    },
    "stonegate-homes-site": {
        "prompt": "A photograph of a residential building under construction in India on a bright morning, concrete frame "
        "with scaffolding and neatly stacked materials, wide empty sky at the top. No people, no text, no signage, no logos.",
        "aspect": "16:9",
        "out": "brands/stonegate-homes/site.png",
    },
}


def token() -> str:
    gcloud = shutil.which("gcloud") or str(Path(os.environ["LOCALAPPDATA"]) / "gcloud-cli/google-cloud-sdk/bin/gcloud.cmd")
    return subprocess.run(
        [gcloud, "auth", "application-default", "print-access-token"], capture_output=True, text=True, check=True
    ).stdout.strip()


def generate(name: str, spec: dict, project: str, bearer: str) -> Path:
    parts = [{"text": spec["prompt"]}]
    for ref in spec.get("refs", []):
        data = base64.b64encode((RAW / f"{ref}.png").read_bytes()).decode()
        parts.append({"inlineData": {"mimeType": "image/png", "data": data}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": spec.get("aspect", "1:1"), "imageSize": spec.get("size", "1K")},
        },
    }
    url = (
        f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
        f"/publishers/google/models/{MODEL}:generateContent"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json", "x-goog-user-project": project},
    )
    for wait in (20, 40, 80, 160, 0):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                reply = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code != 429 or not wait:
                raise
            print(f"{name}: rate limited, waiting {wait}s", flush=True)
            time.sleep(wait)
    print(f"{name}: tokens {reply.get('usageMetadata', {}).get('totalTokenCount')}, model {reply.get('modelVersion')}")
    for part in reply["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            RAW.mkdir(parents=True, exist_ok=True)
            path = RAW / f"{name}.png"
            path.write_bytes(base64.b64decode(part["inlineData"]["data"]))
            return path
    raise RuntimeError(f"{name}: no image returned: {json.dumps(reply)[:400]}")


def cut_logo(image: Image.Image) -> Image.Image:
    """Clear the white surround by filling inward from the corners."""
    image = image.convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    for corner in [(0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)]:
        ImageDraw.floodfill(image, corner, (255, 255, 255, 0), thresh=30)
    return image


def pixelate(image: Image.Image) -> Image.Image:
    """Key the magenta, flatten to a palette, then let each grid cell take its most common colour."""
    rgb = np.array(image.convert("RGB")).astype(int)
    figure = (np.minimum(rgb[..., 0], rgb[..., 2]) - rgb[..., 1]) < 60
    ys, xs = np.where(figure)
    top, bottom, left, right = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    pitch = max(bottom - top, right - left) / GRID
    rows, cols = ceil((bottom - top) / pitch), ceil((right - left) / pitch)
    quantized = Image.fromarray(rgb[top:bottom, left:right].astype("uint8"), "RGB").quantize(COLOURS, Image.MEDIANCUT, dither=Image.NONE)
    flat = np.array(quantized)
    palette = np.array(quantized.getpalette()[: COLOURS * 3]).reshape(-1, 3)
    mask = figure[top:bottom, left:right]
    ink = palette.sum(axis=1).argmin()
    cells = np.zeros((rows, cols, 4), "uint8")
    for row in range(rows):
        y0, y1 = int(row * pitch), max(int((row + 1) * pitch), int(row * pitch) + 1)
        for col in range(cols):
            x0, x1 = int(col * pitch), max(int((col + 1) * pitch), int(col * pitch) + 1)
            cover = mask[y0:y1, x0:x1]
            if cover.size == 0 or cover.mean() < 0.5:
                continue
            votes = flat[y0:y1, x0:x1][cover]
            pick = ink if (palette[votes].sum(axis=1) < 150).mean() >= 0.3 else np.bincount(votes).argmax()
            cells[row, col] = (*palette[pick], 255)
    sprite = Image.fromarray(cells, "RGBA")
    sprite = sprite.resize((sprite.width * CELL, sprite.height * CELL), Image.NEAREST)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(sprite, ((CANVAS - sprite.width) // 2, (CANVAS - sprite.height) // 2))
    return canvas


def finish(name: str, spec: dict) -> Path:
    out = ROOT / spec["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(RAW / f"{name}.png")
    cut = {"logo": cut_logo, "pixel": pixelate}.get(spec.get("cut"))
    (cut(image) if cut else image.convert("RGB")).save(out, optimize=True)
    return out


def main(names: list[str]) -> None:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    bearer = token()
    wanted = names or [n for n, s in ASSETS.items() if not (ROOT / s["out"]).exists()]
    for name in wanted:
        try:
            generate(name, ASSETS[name], project, bearer)
            print(f"  -> {finish(name, ASSETS[name]).relative_to(ROOT)}")
        except urllib.error.HTTPError as error:
            sys.exit(f"{name}: HTTP {error.code}: {error.read().decode()[:600]}")


if __name__ == "__main__":
    main(sys.argv[1:])
