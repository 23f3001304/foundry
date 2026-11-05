"""Small helpers for text the desk passes on."""

import re


def quiet(text: str | None) -> str:
    # What people wrote must not wake an agent when the desk passes it on.
    return (text or "").replace("@", "@\u200b")


ROOM_OF = "the room of {people}"


def same_login(text: object) -> str:
    # How a login is compared: a pack's list, what is typed at sign-in, and what a command carries all match without regard to case or spaces.
    # Lowered and not case-folded, because that is how Switch tells accounts apart. Folding makes a long s the same as an s, and for Switch they are two accounts.
    return str(text or "").strip().lower()


MOST_HEADLINE_CHARS = 80
CUT_SHORT = "..."


def headline(text: str) -> str:
    line = re.sub(r"[*_`#]", "", text.strip().splitlines()[0]).strip()
    line = line.removeprefix("What is being made:").strip()
    if len(line) <= MOST_HEADLINE_CHARS:
        return line
    # Cut on a whole word, because it goes in the middle of a sentence as often as on a card.
    cut = line[: MOST_HEADLINE_CHARS - len(CUT_SHORT)]
    return f"{(cut.rsplit(' ', 1)[0] if ' ' in cut else cut).rstrip(' ,;:')}{CUT_SHORT}"
