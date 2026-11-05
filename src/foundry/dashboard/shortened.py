"""A long name on one line. A word with no spaces in it, like a file's name, would otherwise wrap into a block."""

import re

from markupsafe import Markup, escape

# Shorter than this a word fits beside its neighbours on a phone, so it wraps as words do.
MOST_WORD = 28
# How much of a word's end always shows, which is enough for a file's kind and the end of its name.
KEPT_END = 14
LONG_WORD = re.compile(rf"(\S{{{MOST_WORD},}})")


def shortened(text: object) -> Markup:
    # The stylesheet cuts the first part with an ellipsis if there's no room, so a wide screen shows the whole name. The page holds every letter, and the name is under the mouse.
    parts = LONG_WORD.split(str(text))
    return Markup("").join(
        Markup('<span class="long" title="{word}"><span class="long-head">{head}</span><span class="long-tail">{tail}</span></span>').format(word=part, head=part[:-KEPT_END], tail=part[-KEPT_END:]) if place % 2 else escape(part)
        for place, part in enumerate(parts)
    )
