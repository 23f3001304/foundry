"""Charts for the dashboard, drawn on the server as SVG. Positions go in attributes and colour comes from classes in the stylesheet, so a page needs no script and no inline style.

Each chart says what it shows in words, for anyone who can't see it. They take numbers and names and know nothing about where those came from.
"""

from collections.abc import Sequence
from math import ceil, pi

from markupsafe import Markup, escape


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _svg(classes: str, label: str, body: str, *attributes: str) -> Markup:
    words = escape(label)
    extra = " ".join(attributes)
    return Markup(f'<svg class="chart {escape(classes)}" role="img" aria-label="{words}" {extra}><title>{words}</title>{body}</svg>')


def _scale_top(highest: int) -> int:
    # The top of a scale, even so that the line halfway up it is a whole number.
    return max(2, ceil(highest / 2) * 2)


def sparkline(values: Sequence[int], days: Sequence[str], label: str, tone: str = "") -> Markup:
    """A thin line with one point per day, the highest day at the top, and the first and last day named under it."""
    count, highest = len(values), max(values, default=0)
    top, bottom = 18, 76
    if count < 2:
        return _svg(f"spark {tone}", f"{label}: nothing to show yet", "", 'width="100%"', 'height="72"')

    def x(index: int) -> float:
        return 1 + 98 * index / (count - 1)

    def y(value: int) -> float:
        return bottom - (bottom - top) * value / highest if highest else bottom

    parts = [f'<line class="grid" x1="0" x2="100%" y1="{bottom}%" y2="{bottom}%"/>', f'<line class="grid" x1="0" x2="100%" y1="{top}%" y2="{top}%"/>']
    # Lines rather than one polyline, because only these can be placed in percentages and so stay sharp at any width.
    parts += [f'<line class="spark-line" x1="{_n(x(i))}%" y1="{_n(y(values[i]))}%" x2="{_n(x(i + 1))}%" y2="{_n(y(values[i + 1]))}%"/>' for i in range(count - 1)]
    parts.append(f'<circle class="spark-end" cx="{_n(x(count - 1))}%" cy="{_n(y(values[-1]))}%" r="2.5"/>')
    width = 100 / count
    parts += [f'<rect class="hit" x="{_n(width * i)}%" y="0" width="{_n(width)}%" height="100%"><title>{escape(days[i])}: {values[i]}</title></rect>' for i in range(count)]
    parts += [
        f'<text class="axis" x="0" y="{top}%" dy="-3">{highest}</text>',
        f'<text class="axis" x="0" y="100%" dy="-1">{escape(days[0])}</text>',
        f'<text class="axis" x="100%" y="100%" dy="-1" text-anchor="end">{escape(days[-1])}</text>',
    ]
    said = f"{label}: {sum(values)} in the last {count} days, and at most {highest} in a day." if highest else f"{label}: none in the last {count} days."
    return _svg(f"spark {tone}", said, "".join(parts), 'width="100%"', 'height="72"')


def bars(days: Sequence[str], series: Sequence[tuple[str, str, Sequence[int]]], label: str) -> Markup:
    """Bars for each day, side by side and all on one scale. Each of the series is a name, a class and one number per day."""
    count = len(days)
    if not count or not series:
        return _svg("bars", f"{label}: nothing to show yet", "", 'width="100%"', 'height="220"')
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
        parts.append(f'<text class="axis" x="0" y="{_n(y(tick))}%" dy="3.5">{tick}</text>')
    for index, day in enumerate(days):
        start = left + each * index
        said = ", ".join(f"{values[index]} {name.lower()}" for name, _, values in series)
        cells = [f'<title>{escape(day)}: {escape(said)}</title>', f'<rect class="hit" x="{_n(start)}%" y="0" width="{_n(each)}%" height="{_n(bottom)}%"/>']
        for place, (_, css, values) in enumerate(series):
            if values[index]:
                height = max((bottom - top) * values[index] / scale, 1.5)
                cells.append(f'<rect class="bar {escape(css)}" x="{_n(start + each * 0.12 + bar * place)}%" y="{_n(bottom - height)}%" width="{_n(bar * 0.86)}%" height="{_n(height)}%" rx="1.5"/>')
        parts.append(f'<g class="day">{"".join(cells)}</g>')
    step = max(1, ceil(count / 5))
    parts += [f'<text class="axis" x="{_n(left + each * (index + 0.5))}%" y="100%" dy="-1" text-anchor="middle">{escape(days[index])}</text>' for index in range(0, count, step)]
    totals = ", ".join(f"{sum(values)} {name.lower()}" for name, _, values in series)
    return _svg("bars", f"{label}, last {count} days: {totals}.", "".join(parts), 'width="100%"', 'height="220"')


def donut(parts: Sequence[tuple[str, str, int]], label: str, middle: str, under: str = "") -> Markup:
    """A ring cut into parts, with a number in the middle. Each part is a name, a class and a count."""
    total = sum(count for _, _, count in parts)
    radius, centre = 50, 60
    round_it = 2 * pi * radius
    shapes = [f'<circle class="donut-track" cx="{centre}" cy="{centre}" r="{radius}"/>']
    used = 0.0
    showing = sum(1 for _, _, count in parts if count)
    gap = 2.5 if showing > 1 else 0
    for _, css, count in parts:
        if not count:
            continue
        length = round_it * count / total
        shapes.append(
            f'<circle class="donut-part {escape(css)}" cx="{centre}" cy="{centre}" r="{radius}" stroke-dasharray="{_n(max(length - gap, 0.5))} {_n(round_it)}" '
            f'stroke-dashoffset="{_n(-used)}" transform="rotate(-90 {centre} {centre})"/>'
        )
        used += length
    shapes.append(f'<text class="donut-middle" x="{centre}" y="{centre + (2 if under else 8)}" text-anchor="middle">{escape(middle)}</text>')
    if under:
        shapes.append(f'<text class="donut-under" x="{centre}" y="{centre + 18}" text-anchor="middle">{escape(under)}</text>')
    said = ", ".join(f"{count} {name.lower()}" for name, _, count in parts) if total else "nothing yet"
    return _svg("donut", f"{label}: {said}.", "".join(shapes), 'viewBox="0 0 120 120"')


def flow(stages: Sequence[tuple[str, str, int]], label: str) -> Markup:
    """A band across the stages, as thick at each one as the number of jobs there. Each stage is a key, a name and a count."""
    count = len(stages)
    if not count:
        return _svg("flow", f"{label}: nothing to show yet", "", 'width="100%"', 'height="88"')
    highest = max((number for _, _, number in stages), default=0)
    width, middle, most = 600.0, 50.0, 46.0
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
        f'<path class="flow-band" d="M 0 {_n(middle - half[0])} {over} L {_n(width)} {_n(middle + half[-1])} {under} Z"/>',
        f'<path class="flow-edge" d="M 0 {_n(middle - half[0])} {over}"/>',
        f'<path class="flow-edge" d="M {_n(width)} {_n(middle + half[-1])} {under}"/>',
    ]
    said = ", ".join(f"{name} {number}" for _, name, number in stages)
    return _svg("flow", f"{label}: {said}.", "".join(shapes), f'viewBox="0 0 {_n(width)} 100"', 'preserveAspectRatio="none"', 'width="100%"', 'height="88"')


def meter(value: int, total: int, label: str, tone: str = "") -> Markup:
    """A thin rounded bar on a dark track."""
    share = 100 * value / total if total else 0
    fill = f'<rect class="meter-fill" width="{_n(max(share, 2))}%" height="6" rx="3"/>' if value else ""
    return _svg(f"meter {tone}", f"{label}: {value} of {total}", f'<rect class="meter-track" width="100%" height="6" rx="3"/>{fill}', 'width="100%"', 'height="6"')
