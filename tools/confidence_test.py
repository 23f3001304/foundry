"""Measures whether a model's low confidence means anything by the time the desk reads it. Half of the notes are deliberately garbled, and they all go through the real clean-up code.

A garbled note often comes back as a question. That stops it, and the desk never reads how sure the question was. So a question here gets a reply, and what is scored is the report made after it.

Exits 1 unless low confidence catches at least half the garbled and marks under a quarter of the clean.
On 2026-11-05 all 10 garbled notes came back as a question, and none of the clean. After the reply below, low confidence caught 7 of 10 garbled and marked 0 of 10 clean, so clean-up keeps its confidence. An earlier 10 of 10 scored the questions.
It measured the reader of replies too, on 2026-11-05. That caught 3 of 10 garbled and marked 0 of 10 clean, so the reader no longer gives a confidence.

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
from foundry.pack import load_pack

BRAND = Path(__file__).resolve().parent.parent / "brands" / "demo-it-firm"
AT_ONCE = 4
SENT_AT = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
# What someone says to a question about a note they can't make any clearer.
NOT_SURE_REPLY = "I don't know, put it in as I said it"

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


@dataclass(frozen=True)
class Measured:
    confidence: float | None
    asked: bool = False
    still_asking: bool = False


def through_the_desk_s_steps(note: str, llm: Callable[[str], str]) -> Measured:
    pack = load_pack(BRAND)
    asked = False
    try:
        result = clean_note(note, SENT_AT, pack, llm)
        if result.questions:
            asked = True
            # The question and the reply follow the note, as Desk._clean_report and Desk._take_burst write them. A second question means nothing is filed yet, so there is no score to read.
            question = "\n".join(result.questions)
            result = clean_note(f"{note}\n\nAsked: {question}\nAnswered: {NOT_SURE_REPLY}", SENT_AT, pack, llm)
    except CleanupFailed:
        return Measured(None, asked)
    return Measured(result.confidence, asked, bool(result.questions))


def _measure(name: str, cases: list[tuple[str, bool]], ask: Callable[[str], Measured]) -> Score:
    with ThreadPoolExecutor(AT_ONCE) as pool:
        measured = list(pool.map(ask, [text for text, _ in cases]))
    for (text, garbled), one in zip(cases, measured):
        print(f"{name} {'garbled' if garbled else 'clean  '} {'asked' if one.asked else '     '} {'no answer' if one.confidence is None else f'{one.confidence:.2f}'} {text}", flush=True)
    found = score([(garbled, one.confidence) for (_, garbled), one in zip(cases, measured)])
    asked = [garbled for (_, garbled), one in zip(cases, measured) if one.asked]
    print(f"Came back as a question: {sum(asked)} of {found.garbled} garbled, {len(asked) - sum(asked)} of {found.clean} clean. Still a question after the answer: {sum(one.still_asking for one in measured)}.", flush=True)
    print(f"{name}: garbled caught {found.caught} of {found.garbled}, clean marked {found.marked} of {found.clean}. {'Meets the bar.' if found.meets_bar else 'Misses the bar.'}", flush=True)
    return found


def main(llm: Callable[[str], str]) -> int:
    return 0 if _measure("Clean-up", NOTES, lambda note: through_the_desk_s_steps(note, llm)).meets_bar else 1


if __name__ == "__main__":
    sys.exit(main(default_llm(os.environ.get("FOUNDRY_CLEANUP_MODEL", "claude-sonnet-5-5"))))
