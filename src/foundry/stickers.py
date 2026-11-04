"""Which sticker goes with which moment, per the business pack's sticker_mode."""

from pathlib import Path

STICKERS = Path(__file__).resolve().parents[2] / "stickers"
EVENTS = {"brief_received", "working", "needs_input", "approved", "shipped", "revise", "blocked", "celebrate"}
SUBTLE = {"needs_input", "approved", "shipped", "blocked"}


def sticker_for(event: str, mode: str, pack: str = "base") -> Path | None:
    if event not in EVENTS or mode == "off" or (mode == "subtle" and event not in SUBTLE):
        return None
    for folder in (pack, "base"):
        path = STICKERS / folder / f"{event}.png"
        if path.exists():
            return path
    return None
