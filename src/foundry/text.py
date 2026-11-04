"""Small helpers for text the desk passes on."""

import re


def quiet(text: str | None) -> str:
    # What people wrote must not wake an agent when the desk passes it on.
    return (text or "").replace("@", "@\u200b")


def headline(text: str) -> str:
    line = re.sub(r"[*_`#]", "", text.strip().splitlines()[0]).strip()
    return line.removeprefix("What is being made:").strip()[:80]
