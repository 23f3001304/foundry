"""Briefs, answers and notes are written in markdown with the odd formula, so pages show them formatted instead of as raw marks.

Rendered here, on the server: the page's policy runs no script from elsewhere. Raw HTML in the text is never passed through, and a formula becomes MathML, which browsers draw themselves.
"""

from functools import lru_cache

from latex2mathml.converter import convert
from markdown_it import MarkdownIt
from markupsafe import Markup, escape
from mdit_py_plugins.dollarmath import dollarmath_plugin


def _math(content: str, options: dict) -> str:
    try:
        return convert(content, display="block" if options.get("display_mode") else "inline")
    except Exception:
        # A formula that can't be read is shown as it was written.
        return f"<code>{escape(content)}</code>"


@lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table").enable("strikethrough")
    return parser.use(dollarmath_plugin, allow_space=True, double_inline=True, renderer=_math)


def render(text: str | None) -> Markup:
    return Markup(_parser().render(text or ""))
