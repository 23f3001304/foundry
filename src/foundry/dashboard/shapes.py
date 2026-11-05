"""The dashboard's abstract shapes, drawn on the server as SVG paths of our own. Colour comes from classes in the stylesheet and from the gradients in defs(), so a page needs no script and no inline style.

Every shape is decoration, so it is hidden from a screen reader, and the words on it say what matters.
"""

from markupsafe import Markup

FAMILIES = ("lime", "ember", "azure", "orchid", "sun")
# A long rise from the left, over a crest something can stand on, curling back into one sharp cusp, then one long sweep up to the right edge.
CUT_OUT = "M0 400V270C190 256 380 128 610 112C716 104 842 122 800 232C860 170 1010 70 1200 30V400Z"
GRID_CELL = 64


def _stops(family: str) -> str:
    return "".join(f'<stop offset="{offset}" class="stop-{family}-{place}"/>' for place, offset in ((1, 0), (2, 0.52), (3, 1)))


def defs() -> Markup:
    """The gradients and the grid every chart and shape on a page shares. It is drawn once, with no size, and each part names it by its id."""
    parts = []
    for family in FAMILIES:
        parts.append(f'<linearGradient id="deep-{family}" x1="0" y1="1" x2="1" y2="0">{_stops(family)}</linearGradient>')
        parts.append(f'<linearGradient id="tile-{family}" x1="0" y1="1" x2="1" y2="0"><stop offset="0" class="stop-{family}-2"/><stop offset="1" class="stop-{family}-3"/></linearGradient>')
        parts.append(f'<linearGradient id="soft-{family}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="stop-soft-{family}"/><stop offset="1" class="stop-none-{family}"/></linearGradient>')
    parts.append(f'<pattern id="grid-cells" width="{GRID_CELL}" height="{GRID_CELL}" patternUnits="userSpaceOnUse"><path class="grid-cell" d="M{GRID_CELL - 0.5} 0V{GRID_CELL}M0 {GRID_CELL - 0.5}H{GRID_CELL}"/></pattern>')
    return Markup(f'<svg class="defs" aria-hidden="true" focusable="false" width="0" height="0"><defs>{"".join(parts)}</defs></svg>')


def cut_out(family: str) -> Markup:
    """A flat cut-out for the bottom of a rounded panel: long curves and one cusp, in one family."""
    return Markup(f'<svg class="cut-out" viewBox="0 0 1200 400" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path fill="url(#deep-{family})" d="{CUT_OUT}"/></svg>')


def grid_tile(family: str) -> Markup:
    """A gradient tile with thin dark grid lines. Whatever sits on it overlaps it and runs off one edge."""
    return Markup(f'<svg class="grid-tile" aria-hidden="true" focusable="false" width="100%" height="100%"><rect width="100%" height="100%" fill="url(#tile-{family})"/><rect width="100%" height="100%" fill="url(#grid-cells)"/></svg>')
