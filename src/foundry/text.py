"""Small helpers for text the desk passes on."""

import re


# Control characters, other than the line breaks and tabs a message may hold. Postgres refuses NUL in text, so a message with one is never stored, and the rest have no reason to be there.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def no_controls(text: str) -> str:
    return CONTROL.sub("", text)


def quiet(text: str | None) -> str:
    # What people wrote must not wake an agent when the desk passes it on.
    return (text or "").replace("@", "@\u200b")


def on_the_network(text: str) -> bool:
    # A path on another machine, written \\host\share, //host/share, /\host or \/host. Asking the system where one really is contacts the host it names, so a check that
    # goes on to resolve a path asks this first. foundry.tables keeps the same test for the desk's own files.
    return text.replace("\\", "/").startswith("//")


ROOM_OF = "the room of {people}"
SWITCH_SENDER, AGENT_SENDER = "@switch-", "@switch-agent-"
LOGIN_BREAKS = re.compile(r"[-_.]+")


def shown_name(name: str | None, sender: str | None = "") -> str:
    # Chat gives Switch a person's username as their name unless it knows better, so a card would say team-lead-b. A name that is only the login at the end of the sender's id reads as words.
    # This is for showing only. What is matched on keeps the login.
    name, person = name or "", (sender or "").partition(":")[0]
    if not name or not person.startswith(SWITCH_SENDER) or person.startswith(AGENT_SENDER) or not person.endswith(f"-{name}"):
        return name
    return " ".join(word[:1].upper() + word[1:] for word in LOGIN_BREAKS.split(name) if word)


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
