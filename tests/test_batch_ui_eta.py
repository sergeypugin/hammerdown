from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import time

from rich.console import Console

import hammerdown.batch as batch
from hammerdown.core import get_conversion_estimate, get_conversion_estimate_seconds
from hammerdown.utils import BATCH_UI_WIDTH, BatchUI, _LiveBatchRenderable


def test_text_file_estimate_is_approximate(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("brief text", encoding="utf-8")

    assert get_conversion_estimate_seconds(source) == 0.5
    assert get_conversion_estimate(source) == "~0.50s"


def test_batch_ui_shows_cached_estimates_and_total(tmp_path: Path):
    ui = BatchUI(
        [str(tmp_path / "one.pdf"), str(tmp_path / "two.pdf")],
        quiet=True,
        estimates=[1.0, 2.0],
    )
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())

    assert "~1s" in output.getvalue()
    assert "~2s" in output.getvalue()
    assert "Estimated total: ~3s" in output.getvalue()


def test_run_batch_precomputes_all_estimates_before_conversion(tmp_path: Path, monkeypatch):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    events: list[tuple[str, str]] = []

    def estimate(path: Path) -> float:
        events.append(("estimate", path.name))
        return 0.5

    def convert(file_path, **kwargs):
        source = Path(file_path)
        events.append(("convert", source.name))
        kwargs["completion_callback"](True, 0.01, 0, 0)
        return True

    monkeypatch.setattr(batch, "get_conversion_estimate_seconds", estimate)
    monkeypatch.setattr(batch, "convert_file", convert)
    args = argparse.Namespace(
        files=[str(first), str(second)],
        coordinator=False,
        in_place=False,
        overwrite=False,
        skip_existing=False,
        quiet=True,
        merge=None,
    )

    assert batch.run_batch(args) == 0
    assert events == [
        ("estimate", "a.txt"),
        ("estimate", "b.txt"),
        ("convert", "a.txt"),
        ("convert", "b.txt"),
    ]


def test_batch_live_renderable_refreshes_elapsed_time(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "active.pdf")], quiet=True)
    ui.start_file(0)
    renderable = _LiveBatchRenderable(ui)
    console = Console(width=BATCH_UI_WIDTH, force_terminal=False)

    def render() -> str:
        output = StringIO()
        Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(renderable)
        return output.getvalue()

    before = render()
    time.sleep(0.03)
    after = render()

    assert "active.pdf" in before
    assert before != after


def test_batch_ui_shows_active_progress(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "active.pdf")], quiet=True, estimates=[5.0])
    ui.start_file(0)
    ui.update_progress(0, 3, 4, "pages")
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())

    assert "active.pdf" in output.getvalue()
    assert "75%" in output.getvalue()
