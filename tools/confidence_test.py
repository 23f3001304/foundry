"""Measures whether a model's low confidence means anything. Half of each set is deliberately garbled, and it all goes through the real clean-up and reading code.

Exits 1 unless low confidence catches at least half the garbled and marks under a quarter of the clean, in both sets.

uv run --env-file .env python tools/confidence_test.py
"""

import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foundry.checks import LOW_CONFIDENCE
from foundry.cleanup import CleanupFailed, clean_note
from foundry.intake import default_llm
from foundry.items import Item, ItemState
from foundry.pack import load_pack
from foundry.reading import read_message

BRAND = Path(__file__).resolve().parent.parent / "brands" / "demo-it-firm"
AT_ONCE = 4
SENT_AT = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)

# (what a Team Lead sent, whether it is deliberately garbled). All made up.
NOTES = [
    ("Team A closed 41 stories this sprint. The customer portal release goes to UAT tomorrow.", False),
    ("QA finished the payments retest today and found no new defects.", False),
    ("Team B fixed the login defect and moved it to QA this morning.", False),
    ("Sprint planning for Team C is on Monday. We have 18 stories lined up for reporting.", False),
    ("UAT for the reporting module started today. 12 of 40 test cases have passed so far.", False),
    ("aaj Team A ne 41 stories close kar di, customer portal kal UAT mein jayega", False),
    ("QA ne payments retest khatam kar diya, koi naya defect nahi mila", False),
    ("Team B ka deployment aaj shaam ko hoga, sab ready hai", False),
    ("The database migration for reporting finished last night with no errors.", False),
    ("Team C has 3 defects open. All three are in the export screen and are being fixed today.", False),
    ("team ne vo wala kar diya par phir uske baad 4 ya shayad 14 ka kuch hua toh dekh lena", True),
    ("Portal... the, um, it went to, no wait, not that one, the other build, maybe Tuesday or", True),
    ("qa ka sab theek nahi tha ya tha pata nahi uske baad jo bola tha", True),
    ("stories closed 4?1 defects open three or 30 UAT moved back or forward not sure", True),
    ("kal parso wala release jo tha vo shayad nahi hua par ho bhi sakta hai", True),
    ("the the migration wrk dun bt rprtng brkn or mybe nt chk wth sm1", True),
    ("Sprint something closed, or the sprint before it, some number of stories, I lost the sheet", True),
    ("usne bola 20 ho gaya phir bola nahi 12 phir kuch aur bola network kat gaya", True),
    ("payment wala team lead ne bola retest pass ho gaya ya fail, voice clear nahi tha", True),
    ("xqj deploy portal 44 hmm yes no staging prod which one call me", True),
]

# (a reply to the one item asked of a Team Lead, whether it is deliberately garbled).
REPLIES = [
    ("Team A closed 41 stories this sprint.", False),
    ("41 stories closed.", False),
    ("We closed 38 stories.", False),
    ("41", False),
    ("Stories closed this sprint: 27.", False),
    ("Team A ne 41 stories close ki hain.", False),
    ("Final count is 52 stories closed.", False),
    ("33 stories closed, that is the final number.", False),
    ("It's 19 stories for this sprint.", False),
    ("Hamare 60 stories close ho gaye is sprint mein.", False),
    ("maybe 40 or 14 not sure the sheet is gone", True),
    ("4?1 stories or so", True),
    ("uh thirty something, or was that last sprint", True),
    ("41 ya 14, pata nahi, phir dekhta hoon", True),
    ("some of them closed I think", True),
    ("stries clsd mybe 2x or 3x chk", True),
    ("the number the other team said, roughly", True),
    ("20 ho gaya phir nahi 12 phir network kat gaya", True),
    ("less than last time but more than before maybe", True),
    ("hmm 7 or 70 depends how you count", True),
]


@dataclass(frozen=True)
class Score:
    caught: int
    garbled: int
    marked: int
    clean: int

    @property
    def meets_bar(self) -> bool:
        return self.caught * 2 >= self.garbled and self.marked * 4 < self.clean


def score(results: list[tuple[bool, float | None]]) -> Score:
    low = [garbled for garbled, confidence in results if confidence is not None and confidence < LOW_CONFIDENCE]
    return Score(sum(low), sum(garbled for garbled, _ in results), len(low) - sum(low), sum(not garbled for garbled, _ in results))


def _cleanup_confidence(note: str, llm: Callable[[str], str]) -> float | None:
    pack = load_pack(BRAND)
    try:
        return clean_note(note, SENT_AT, pack, llm).confidence
    except CleanupFailed:
        return None


def _reading_confidence(reply: str, llm: Callable[[str], str]) -> float | None:
    item = Item("item-1", "job-1", "demo-it-firm", "@team-lead-a:localhost", "team-lead-a", "room-1", "Team A release status", "stories closed this sprint, a whole number", SENT_AT, ItemState.OPEN, None, None, None, SENT_AT, None, True, True)
    return read_message(reply, [item], ["team-lead-a", "delivery-manager"], "team-lead-a", llm, SENT_AT.date()).confidence


def _measure(name: str, cases: list[tuple[str, bool]], ask: Callable[[str], float | None]) -> Score:
    with ThreadPoolExecutor(AT_ONCE) as pool:
        confidences = list(pool.map(ask, [text for text, _ in cases]))
    for (text, garbled), confidence in zip(cases, confidences):
        print(f"{name} {'garbled' if garbled else 'clean  '} {'no answer' if confidence is None else f'{confidence:.2f}'} {text}", flush=True)
    found = score([(garbled, confidence) for (_, garbled), confidence in zip(cases, confidences)])
    print(f"{name}: garbled caught {found.caught} of {found.garbled}, clean marked {found.marked} of {found.clean}. {'Meets the bar.' if found.meets_bar else 'Misses the bar.'}", flush=True)
    return found


def main(cleanup_llm: Callable[[str], str], reading_llm: Callable[[str], str]) -> int:
    scores = [
        _measure("Clean-up", NOTES, lambda note: _cleanup_confidence(note, cleanup_llm)),
        _measure("Reading", REPLIES, lambda reply: _reading_confidence(reply, reading_llm)),
    ]
    return 0 if all(found.meets_bar for found in scores) else 1


if __name__ == "__main__":
    sys.exit(main(default_llm(os.environ.get("FOUNDRY_CLEANUP_MODEL", "claude-sonnet-5-5")), default_llm()))
