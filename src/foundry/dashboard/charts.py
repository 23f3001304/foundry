"""Charts for the dashboard, drawn on the server as SVG. Positions go in attributes and colour comes from classes in the stylesheet, so a page needs no script and no inline style.

Each chart says what it shows in words, for anyone who can't see it. They take numbers and names and know nothing about where those came from.
A chart can be given addresses, and then its parts are links for the mouse. Each is left out of the tab order, because the words and links beside the chart go to the same places.
"""

from collections.abc import Mapping, Sequence
from math import ceil, pi

from markupsafe import Markup, escape

AREA_HEIGHT, BARS_HEIGHT, FLOW_HEIGHT, METER_HEIGHT = 136, 136, 128, 8
# How far each end of a line is marked, in whole pixels either way.
END_MARK = 1


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _svg(classes: str, label: str, body: str, *attributes: str) -> Markup:
    words = escape(label)
    extra = " ".join(attributes)
    return Markup(f'<svg class="chart {escape(classes)}" role="img" aria-label="{words}" {extra}><title>{words}</title>{body}</svg>')


def _linked(shape: str, href: str) -> str:
    return f'<a href="{escape(href)}" tabindex="-1">{shape}</a>' if href else shape


def _scale_top(highest: int) -> int:
    # The top of a scale, even so that the line halfway up it is a whole number.
    return max(2, ceil(highest / 2) * 2)


def area(times: Sequence[str], lines: Sequence[tuple[str, str, Sequence[int]]], label: str, band: bool = False, running: bool = False, ends: tuple[str, str] | None = None, href: str = "") -> Markup:
    """Saturated lines with a soft fill under them, all on one scale, and a dashed line at zero. Each line is a name, a colour family and one number per time. With band, the space between the first two lines is filled, because that space means something. With running, each number already counts everything before it."""
    count, highest = len(times), max((max(values, default=0) for _, _, values in lines), default=0)
    if count < 2 or not highest:
        return _svg("area", f"{label}: nothing to show yet", "", 'width="100%"', f'height="{AREA_HEIGHT}"')
    scale = _scale_top(highest)
    left, top, bottom = 7.0, 6.0, 84.0

    def x(index: int) -> float:
        return 100 * index / (count - 1)

    def y(value: int) -> float:
        return 100 - 100 * value / scale

    def down(share: float) -> float:
        return top + (bottom - top) * share / 100

    def trace(values: Sequence[int]) -> str:
        return " ".join(f"{'L' if index else 'M'}{_n(x(index))} {_n(y(value))}" for index, value in enumerate(values))

    fills = []
    if band and len(lines) > 1:
        first, second = lines[0][2], lines[1][2]
        back = " ".join(f"L{_n(x(index))} {_n(y(second[index]))}" for index in range(count - 1, -1, -1))
        fills.append(f'<path class="band" fill="url(#soft-{escape(lines[0][1])})" d="{trace(first)} {back} Z"/>')
    else:
        fills += [f'<path class="band" fill="url(#soft-{escape(family)})" d="{trace(values)} L100 100 L0 100 Z"/>' for _, family, values in lines]
    strokes = [f'<path class="area-line line-{escape(family)}" d="{trace(values)}"/>' for _, family, values in lines]
    parts = []
    for tick in (scale, scale // 2):
        parts.append(f'<line class="grid" x1="{left}%" x2="100%" y1="{_n(down(y(tick)))}%" y2="{_n(down(y(tick)))}%"/>')
    parts.append(f'<line class="baseline" x1="{left}%" x2="100%" y1="{bottom}%" y2="{bottom}%"/>')
    for tick in (scale, scale // 2, 0):
        parts.append(f'<text class="axis" x="0" y="{_n(down(y(tick)))}%" dy="4">{tick}</text>')
    parts.append(f'<svg class="area-plot" x="{left}%" y="{top}%" width="{100 - left}%" height="{bottom - top}%" viewBox="0 0 100 100" preserveAspectRatio="none">{"".join(fills)}{"".join(strokes)}</svg>')
    width = (100 - left) / count
    for index in range(count):
        said = ", ".join(f"{values[index]} {name.lower()}" for name, _, values in lines)
        parts.append(_linked(f'<rect class="hit" x="{_n(left + width * index)}%" y="0" width="{_n(width)}%" height="{bottom}%"><title>{escape(times[index])}: {escape(said)}</title></rect>', href))
    for _, family, values in lines:
        across, height = left + (100 - left) * x(count - 1) / 100, down(y(values[-1]))
        parts.append(f'<svg class="area-end" x="{_n(across)}%" y="{_n(height)}%" width="{END_MARK}" height="{END_MARK}" overflow="visible"><path class="end-{escape(family)}" d="M0 -4L4 0L0 4L-4 0Z"/></svg>')
    first_time, last_time = ends or (times[0], times[-1])
    parts += [
        f'<text class="axis" x="{left}%" y="100%" dy="-1">{escape(first_time)}</text>',
        f'<text class="axis" x="100%" y="100%" dy="-1" text-anchor="end">{escape(last_time)}</text>',
    ]
    totals = ", ".join(f"{values[-1] if running else sum(values)} {name.lower()}" for name, _, values in lines)
    said = f"{label}: {totals}, from {first_time} to {last_time}."
    return _svg("area", said, "".join(parts), 'width="100%"', f'height="{AREA_HEIGHT}"')


def bars(days: Sequence[str], series: Sequence[tuple[str, str, Sequence[int]]], label: str, links: Mapping[str, str] | None = None) -> Markup:
    """Bars for each day, side by side and all on one scale. Each of the series is a name, a class and one number per day. Links, if given, say where each class's bars go."""
    count = len(days)
    if not count or not series:
        return _svg("bars", f"{label}: nothing to show yet", "", 'width="100%"', f'height="{BARS_HEIGHT}"')
    highest = max((max(values, default=0) for _, _, values in series), default=0)
    scale = _scale_top(highest)
    left, top, bottom = 5.0, 6.0, 86.0
    plot = 100 - left
    each = plot / count
    bar = each * 0.76 / len(series)

    def y(value: int) -> float:
        return bottom - (bottom - top) * value / scale

    parts = []
    for tick in (0, scale // 2, scale):
        parts.append(f'<line class="{"baseline" if tick == 0 else "grid"}" x1="{left}%" x2="100%" y1="{_n(y(tick))}%" y2="{_n(y(tick))}%"/>')
        parts.append(f'<text class="axis" x="0" y="{_n(y(tick))}%" dy="4">{tick}</text>')
    for index, day in enumerate(days):
        start = left + each * index
        said = ", ".join(f"{values[index]} {name.lower()}" for name, _, values in series)
        cells = [f'<title>{escape(day)}: {escape(said)}</title>', f'<rect class="hit" x="{_n(start)}%" y="0" width="{_n(each)}%" height="{_n(bottom)}%"/>']
        for place, (_, css, values) in enumerate(series):
            if values[index]:
                height = max((bottom - top) * values[index] / scale, 1.5)
                drawn = f'<rect class="bar {escape(css)}" x="{_n(start + each * 0.12 + bar * place)}%" y="{_n(bottom - height)}%" width="{_n(bar * 0.86)}%" height="{_n(height)}%" rx="2"/>'
                cells.append(_linked(drawn, (links or {}).get(css, "")))
        parts.append(f'<g class="day">{"".join(cells)}</g>')
    step = max(1, ceil(count / 5))
    parts += [f'<text class="axis" x="{_n(left + each * (index + 0.5))}%" y="100%" dy="-1" text-anchor="middle">{escape(days[index])}</text>' for index in range(0, count, step)]
    totals = ", ".join(f"{sum(values)} {name.lower()}" for name, _, values in series)
    return _svg("bars", f"{label}, last {count} days: {totals}.", "".join(parts), 'width="100%"', f'height="{BARS_HEIGHT}"')


def donut(parts: Sequence[tuple[str, str, int]], label: str, middle: str, under: str = "", href: str = "") -> Markup:
    """A ring cut into parts, with a number in the middle. Each part is a name, a class and a count."""
    total = sum(count for _, _, count in parts)
    radius, centre = 52, 60
    round_it = 2 * pi * radius
    shapes = [f'<circle class="donut-track" cx="{centre}" cy="{centre}" r="{radius}"/>']
    used = 0.0
    showing = sum(1 for _, _, count in parts if count)
    gap = 2.5 if showing > 1 else 0
    for name, css, count in parts:
        if not count:
            continue
        length = round_it * count / total
        drawn = (
            f'<circle class="donut-part {escape(css)}" cx="{centre}" cy="{centre}" r="{radius}" stroke-dasharray="{_n(max(length - gap, 0.5))} {_n(round_it)}" '
            f'stroke-dashoffset="{_n(-used)}" transform="rotate(-90 {centre} {centre})"><title>{escape(name)}: {count}</title></circle>'
        )
        shapes.append(_linked(drawn, href))
        used += length
    shapes.append(f'<text class="donut-middle" x="{centre}" y="{centre + (4 if under else 8)}" text-anchor="middle">{escape(middle)}</text>')
    if under:
        shapes.append(f'<text class="donut-under" x="{centre}" y="{centre + 20}" text-anchor="middle">{escape(under)}</text>')
    said = ", ".join(f"{count} {name.lower()}" for name, _, count in parts) if total else "nothing yet"
    return _svg("donut", f"{label}: {said}.", "".join(shapes), 'viewBox="0 0 120 120"')


def flow(stages: Sequence[tuple[str, str, int]], label: str, links: Mapping[str, str] | None = None) -> Markup:
    """A band across the stages, as thick at each one as the number of jobs there. Each stage is a key, a name and a count. Links, if given, say where each key's stretch goes."""
    count = len(stages)
    if not count:
        return _svg("flow", f"{label}: nothing to show yet", "", 'width="100%"', f'height="{FLOW_HEIGHT}"')
    highest = max((number for _, _, number in stages), default=0)
    width, middle, most = 600.0, 50.0, 34.0
    each = width / count
    half = [2 + (most - 2) * number / highest if highest and number else 1.0 for _, _, number in stages]
    edges = [(each * index + each * 0.3, each * index + each * 0.7) for index in range(count)]

    def edge(sign: int, order: Sequence[int]) -> str:
        path = []
        for place, index in enumerate(order):
            first, last = edges[index] if sign < 0 else edges[index][::-1]
            height = middle + sign * half[index]
            if place:
                before = order[place - 1]
                start = edges[before][1] if sign < 0 else edges[before][0]
                bend = (first + start) / 2
                path.append(f"C {_n(bend)} {_n(middle + sign * half[before])} {_n(bend)} {_n(height)} {_n(first)} {_n(height)}")
            path.append(f"L {_n(last)} {_n(height)}")
        return " ".join(path)

    ahead = list(range(count))
    over = f"{edge(-1, ahead)} L {_n(width)} {_n(middle - half[-1])}"
    under = f"{edge(1, ahead[::-1])} L 0 {_n(middle + half[0])}"
    shapes = [
        f'<path class="flow-band" fill="url(#through-stages)" d="M 0 {_n(middle - half[0])} {over} L {_n(width)} {_n(middle + half[-1])} {under} Z"/>',
        f'<path class="flow-edge" d="M 0 {_n(middle - half[0])} {over}"/>',
        f'<path class="flow-edge" d="M {_n(width)} {_n(middle + half[-1])} {under}"/>',
    ]
    for index, (key, name, number) in enumerate(stages):
        hit = f'<rect class="hit" x="{_n(each * index)}" y="0" width="{_n(each)}" height="100"><title>{escape(name)}: {number}</title></rect>'
        shapes.append(_linked(hit, (links or {}).get(key, "")))
    said = ", ".join(f"{name} {number}" for _, name, number in stages)
    return _svg("flow", f"{label}: {said}.", "".join(shapes), f'viewBox="0 0 {_n(width)} 100"', 'preserveAspectRatio="none"', 'width="100%"', f'height="{FLOW_HEIGHT}"')


def meter(value: int, total: int, label: str, tone: str = "") -> Markup:
    """A thin rounded bar on a quiet track."""
    share = 100 * value / total if total else 0
    fill = f'<rect class="meter-fill" width="{_n(max(share, 2))}%" height="{METER_HEIGHT}" rx="4"/>' if value else ""
    return _svg(f"meter {tone}", f"{label}: {value} of {total}", f'<rect class="meter-track" width="100%" height="{METER_HEIGHT}" rx="4"/>{fill}', 'width="100%"', f'height="{METER_HEIGHT}"')
