from __future__ import annotations

import re
from collections.abc import Sequence

_GLUE_RE = re.compile(r"^[0-9\s=\+\-\*\/±≈\.,_():;\[\]!<>|–\w\.]+$")
_GLUE_WORD_RE = re.compile(r"\w+")
_MATH_FUNCTION_NAMES = frozenset({"max", "min", "sin", "cos", "tan", "log", "ln", "exp", "lim", "det", "arg"})


def render_markdown_table(rows: Sequence[Sequence[str]]) -> list[str]:
    lines: list[str] = []
    for row_index, row in enumerate(rows):
        cells = [cell.replace("|", "\\|") for cell in row]
        lines.append(f"| {' | '.join(cells)} |")
        if row_index == 0:
            lines.append(f"| {' | '.join(['---'] * len(cells))} |")
    return lines


def is_math_glue(part: str) -> bool:
    # Only math symbols, numbers, and whitespace, or very short words/abbreviations,
    # may merge into an adjacent formula without breaking it apart.
    stripped = part.strip()
    if not stripped:
        return True
    if not _GLUE_RE.match(stripped):
        return False
    words = _GLUE_WORD_RE.findall(stripped)
    return all(len(w) <= 4 or w.lower() in _MATH_FUNCTION_NAMES for w in words)
