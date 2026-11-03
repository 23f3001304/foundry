"""Generate Foundry's art with Gemini image models on Vertex AI, then cut it to size.

Usage: uv run --no-project --with pillow tools/gen_assets.py [name ...]
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
from pathlib import Path

from PIL import Image, ImageDraw

MODEL = os.environ.get("FOUNDRY_IMAGE_MODEL", "gemini-nano-banana-2.1")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "raw"

LOGO_STYLE = (
    "A clean, original circular emblem logo for a fictional business. Flat vector with no gradients or shadows, "
    "readable at small sizes, centred on a plain white background with nothing else in the frame."
)

ASSETS = {
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


def finish(name: str, spec: dict) -> Path:
    out = ROOT / spec["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(RAW / f"{name}.png")
    cut = {"logo": cut_logo}.get(spec.get("cut"))
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
