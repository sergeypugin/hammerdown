from __future__ import annotations

from hammerdown.core.formatting import format_progress_bar


def test_progress_bar_clamps_overcount_to_bar_length():
    bar = format_progress_bar(25, 20, unit="pages", bar_length=10)
    assert bar == "[██████████] 100% (25/20 pages)"


def test_progress_bar_clamps_negative_to_empty():
    bar = format_progress_bar(-3, 20, unit="pages", bar_length=10)
    assert bar == "[░░░░░░░░░░] 0% (-3/20 pages)"
