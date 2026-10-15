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
    process_output = StringIO()
    Console(file=process_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())
    summary_output = StringIO()
    Console(file=summary_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())

    assert "~1s" in process_output.getvalue()
    assert "~2s" in process_output.getvalue()
    assert "Estimated total: ~3s" in summary_output.getvalue()
    assert "Time passed:" in summary_output.getvalue()
    assert "Elapsed:" not in summary_output.getvalue()


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


def test_batch_ui_process_shows_bracketed_markers_without_error_summary(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt"), str(tmp_path / "broken.txt")], quiet=True)
    ui.statuses = ["[x]", "[!]"]
    ui.errors.append(("broken.txt", "conversion failed"))

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())
    rendered = output.getvalue()

    assert "[✓]" in rendered
    assert "[!]" in rendered
    assert "Error summary" not in rendered


def test_batch_ui_summary_contains_compact_stats(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt")], quiet=True)
    ui.total_tokens = 1234567
    ui.overwritten_count = 2
    ui.skipped_count = 1
    ui.errors.append(("broken.txt", "file or directory not found"))
    ui.add_summary_message("Merged 4 documents into TODELETE.md")

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())
    rendered = output.getvalue()

    assert "Summary" in rendered
    assert "Errors: 1" in rendered
    assert "Tokens: ~1_234_567" in rendered
    assert "Overwritten: 2" in rendered
    assert "Skipped: 1" in rendered
    assert "Merged 4 documents into TODELETE.md" in rendered
    assert "---" in rendered


def test_batch_ui_places_current_file_by_remaining_queue(tmp_path: Path):
    files = [str(tmp_path / f"file_{index}.txt") for index in range(5)]
    ui = BatchUI(files, quiet=True)
    ui.current_idx = 3
    ui.statuses[3] = "[>]"

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._process_renderable())
    rendered = output.getvalue()

    assert rendered.index("file_3.txt") > rendered.index("file_0.txt")
    assert rendered.index("file_3.txt") > rendered.index("file_2.txt")
    assert "file_4.txt" in rendered


def test_batch_ui_final_render_contains_one_process_and_summary(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt")], quiet=True)
    ui.statuses[0] = "[x]"
    ui.can_redraw = True
    output = StringIO()
    ui._console = Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False)

    ui.print_final()
    rendered = output.getvalue()

    assert rendered.count("Processing 1 files") == 1
    assert rendered.count("Summary") == 1


def test_batch_ui_truncates_long_filenames_and_formats_tokens(tmp_path: Path):
    filename = "document_" + "x" * 160 + ".txt"
    ui = BatchUI([str(tmp_path / filename)], quiet=True)
    ui.start_file(0)
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())

    rendered = output.getvalue()
    assert "Tokens: ~1_234_567" not in rendered
    assert "…" in rendered
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH
