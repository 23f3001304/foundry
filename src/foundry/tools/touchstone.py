"""Black stone and rubbed metal, drawn in code for a kit whose style is touchstone. Everything is seeded, so the same figures draw the same pictures, and nothing comes from a model."""

import hashlib
import io
from functools import lru_cache

import numpy as np
from PIL import Image

from foundry.tools.layout import rgb

# Pixels drawn for each point on the slide. A slide is 960 points wide, so this is sharp at the sizes a deck is shown at and keeps the file small.
PIXELS = 2.5
STONE_SIZE, METAL_SIZE = (1920, 1080), (1000, 350)
STONE_QUALITY, METAL_QUALITY = 82, 80
# A rub is saved with this many colours, so the file stays small. The noise in it hides the steps.
RUB_COLOURS = 192
# How far a rub's threads may fray either side of its true end, in points. The value is the length; the fray is only this much of texture round it.
FRAY = 3.0
COVER_FRAY = 8.0
# Where each share of brightness falls on a rub, as a multiple of the kit's colour. Metal gets deeper and warmer as it darkens. Stone dust only gets darker.
METAL_STOPS = ((0.0, 0.39), (0.28, 0.64), (0.52, 0.87), (0.74, 1.0))
METAL_LIGHTS = ((0.92, 0.35), (1.0, 0.7))
ASH_STOPS = ((0.0, 0.36), (0.4, 0.59), (0.7, 0.82), (1.0, 1.12))


def _seed(*parts: object) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _noise(height: int, width: int, across: float, down: float, rng: np.random.Generator) -> np.ndarray:
    # Random numbers smoothed by these many pixels each way, so a long smooth across and a short one down makes threads.
    spectrum = np.fft.rfft2(rng.standard_normal((height, width)))
    down_freq, across_freq = np.fft.fftfreq(height)[:, None], np.fft.rfftfreq(width)[None, :]
    smooth = np.fft.irfft2(spectrum * np.exp(-2 * np.pi**2 * ((across * across_freq) ** 2 + (down * down_freq) ** 2)), s=(height, width))
    return (smooth - smooth.mean()) / (smooth.std() + 1e-9)


def _wander(length: int, smooth: float, rng: np.random.Generator) -> np.ndarray:
    return _noise(1, length, smooth, 0, rng)[0]


def _ease(start: float | np.ndarray, end: float | np.ndarray, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - start) / (end - start), 0, 1)
    return t * t * (3 - 2 * t)


def _jpeg(pixels: np.ndarray, quality: int) -> bytes:
    out = io.BytesIO()
    Image.fromarray((np.clip(pixels, 0, 1) * 255 + 0.5).astype(np.uint8)).save(out, "JPEG", quality=quality, subsampling=0, optimize=True)
    return out.getvalue()


def _png(pixels: np.ndarray) -> bytes:
    # Fewer colours, kept with their transparency, so that a slide's strokes cost little.
    out = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGBA").quantize(RUB_COLOURS, method=Image.Quantize.FASTOCTREE).save(out, "PNG", optimize=True)
    return out.getvalue()


@lru_cache(maxsize=8)
def stone(paper: str) -> bytes:
    """A slide's ground in the kit's paper colour: fine tooth, slow mottling, faint ghosts of older rubs and a few pale flecks."""
    rng = np.random.default_rng(_seed("stone", paper))
    width, height = STONE_SIZE
    fine, grain = _noise(height, width, 0.7, 0.7, rng), _noise(height, width, 1.9, 1.9, rng)
    mottle, slow = _noise(height, width, 56, 44, rng), _noise(height, width, 255, 190, rng)
    light = 0.0075 * (fine + grain + mottle) + 0.0085 * slow
    ghosts = np.clip(_noise(height, width, 270, 0.9, rng), 0, 3) * _ease(0.55, 1.5, _noise(height, width, 210, 70, rng))
    light += 0.012 * ghosts
    light += 0.05 * np.clip(_noise(height, width, 1.1, 1.1, rng) - 3.4, 0, 1)
    base = np.array(rgb(paper)) / 255
    return _jpeg(base[None, None, :] + light[:, :, None] * np.array((1.02, 0.985, 0.94)), STONE_QUALITY)


def _deep(colour: tuple[int, int, int], share: float) -> tuple[float, float, float]:
    # Metal in shadow: the blue goes first and the red last, so it stays warm and does not turn grey.
    red, green, blue = colour
    return red * share, green * share**1.2, blue * share**2


def _ramp(colour: str, metal: bool) -> list[tuple[float, tuple[float, float, float]]]:
    channels = rgb(colour)
    if not metal:
        return [(at, tuple(min(255, part * share) for part in channels)) for at, share in ASH_STOPS]
    lights = [(at, tuple(part + (255 - part) * share for part in channels)) for at, share in METAL_LIGHTS]
    return [(at, _deep(channels, share)) for at, share in METAL_STOPS] + lights


def _painted(brightness: np.ndarray, colour: str, metal: bool) -> np.ndarray:
    stops = _ramp(colour, metal)
    places = [at for at, _ in stops]
    return np.stack([np.interp(brightness, places, [shade[channel] for _, shade in stops]) for channel in range(3)], axis=-1)


@lru_cache(maxsize=8)
def metal_sheet(accent: str) -> bytes:
    """A sheet of rubbed metal in the kit's accent, to fill a large figure's real, editable letters with."""
    rng = np.random.default_rng(_seed("metal", accent))
    width, height = METAL_SIZE
    brightness = 0.66 + 0.13 * _noise(height, width, 60, 1.0, rng) + 0.07 * _noise(height, width, 15, 0.7, rng) + 0.055 * _noise(height, width, 0.7, 0.7, rng) + 0.07 * _noise(height, width, 150, 20, rng)
    return _jpeg(_painted(np.clip(brightness, 0, 1), accent, True) / 255, METAL_QUALITY)


def _rub_layers(length: float, thick: float, colour: str, metal: bool, key: str, fray: float = FRAY) -> tuple[np.ndarray, int]:
    # One rub lying along x, as colour and opacity, and the pixels of clear ground round its true length and thickness.
    rng = np.random.default_rng(_seed("rub", key))
    long, wide = round(length * PIXELS), round(thick * PIXELS)
    pad = max(round(wide * 0.28), round(fray * 3 * PIXELS))
    height, width = wide + 2 * pad, long + 2 * pad
    y, x = np.mgrid[0:height, 0:width].astype(float)
    threads, finer = _noise(height, width, max(70, long * 0.1), 1.25, rng), _noise(height, width, 24, 0.85, rng)
    tooth, slow = _noise(height, width, 0.9, 0.9, rng), _noise(height, width, max(120, long * 0.2), wide * 0.22, rng)
    # The two long edges wander a little, the way a hand does.
    top = pad + _wander(width, max(80, long * 0.06), rng) * wide * 0.022 + _wander(width, 16, rng) * wide * 0.008
    bottom = pad + wide + _wander(width, max(80, long * 0.06), rng) * wide * 0.022 + _wander(width, 16, rng) * wide * 0.008
    soft = max(wide * 0.07, 3.0)
    across = _ease(top - soft * 0.5, top + soft * 1.2, y) * (1 - _ease(bottom - soft * 1.2, bottom + soft * 0.5, y))
    # Each thread stops at its own place, inside the fray and never further.
    reach = fray * PIXELS
    starts = np.repeat(np.clip(_wander(height, 1.4, rng), -1.6, 1.6)[:, None], width, axis=1) * reach * 0.6
    ends = np.repeat(np.clip(_wander(height, 1.4, rng), -1.6, 1.6)[:, None], width, axis=1) * reach * 0.6
    along = _ease(pad - reach + starts, pad + reach + starts, x) * (1 - _ease(pad + long - reach + ends, pad + long + reach + ends, x))
    body = across * along
    near = 0.15 + 0.85 * _ease(0.0, 0.3, body)
    opacity = _ease(0.60, 0.74, body * 1.28 + (0.26 * threads + 0.12 * finer + 0.17 * tooth) * near - (0 if metal else 0.02))
    middle = np.exp(-(((y - (pad + wide / 2)) / (wide * 0.62)) ** 2))
    brightness = 0.52 + 0.21 * threads + 0.10 * finer + 0.09 * tooth + 0.09 * slow + 0.08 * (middle - 0.5)
    return np.dstack([_painted(np.clip(brightness, 0, 1), colour, metal), opacity * 255 * (1 if metal else 0.9)]), pad


@lru_cache(maxsize=128)
def rub(length: float, thick: float, colour: str, metal: bool, upright: bool, key: str) -> tuple[bytes, float]:
    """A stroke as a transparent picture, and the points of clear ground drawn round it on every side. Its true length is exactly length: only its threads fray, by FRAY at most."""
    layers, pad = _rub_layers(length, thick, colour, metal, key)
    return _png(np.rot90(layers, 1) if upright else layers), pad / PIXELS


@lru_cache(maxsize=8)
def cover_rub(length: float, thick: float, colour: str) -> tuple[bytes, float]:
    """One long rub for the first slide: it starts dry, in broken threads, and closes up into solid metal. Which end it runs off is the picture's right."""
    layers, pad = _rub_layers(length, thick, colour, True, "cover", COVER_FRAY)
    height, width = layers.shape[:2]
    rng = np.random.default_rng(_seed("dry", colour))
    closes_up = _ease(-1.6, 0.1, _noise(height, width, 120, 1.3, rng) + (np.linspace(0, 1, width)[None, :] / 0.22 - 1) * 3.2)
    layers[..., 3] *= closes_up
    return _png(layers), pad / PIXELS
