from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from typing import Any
import time

import pytest

from rich.console import Console

import hammerdown.batch as batch
import hammerdown.utils as utils
from hammerdown.core import get_conversion_estimate, get_conversion_estimate_seconds
from hammerdown.utils import BATCH_UI_WIDTH, BatchUI, _LiveBatchRenderable


def test_text_file_estimate_is_approximate(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("brief text", encoding="utf-8")

    assert get_conversion_estimate_seconds(source) == 0.5
    assert get_conversion_estimate(source) == "~0.5s"


def test_batch_ui_shows_cached_estimates_and_total(tmp_path: Path):
    ui = BatchUI(
        [str(tmp_path / "one.pdf"), str(tmp_path / "two.pdf")],
        estimates=[1.0, 2.0],
    )
    process_output = StringIO()
    Console(file=process_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())
    summary_output = StringIO()
    Console(file=summary_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())

    assert "~1.0s" in process_output.getvalue()
    assert "~2.0s" in process_output.getvalue()
    assert "~3.0s" in summary_output.getvalue()
    assert "Estimated: ~3.0s" in summary_output.getvalue()
    assert "Estimated total:" not in summary_output.getvalue()
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
        overwrite=False,
        skip_existing=False,
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
    ui = BatchUI([str(tmp_path / "active.pdf")])
    ui.start_file(0)
    renderable = _LiveBatchRenderable(ui)
    console = Console(width=BATCH_UI_WIDTH, force_terminal=False)

    def render() -> str:
        output = StringIO()
        Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(renderable)
        return output.getvalue()

    before = render()
    time.sleep(0.11)
    after = render()

    assert "active.pdf" in before
    assert before != after


def test_batch_ui_shows_active_progress(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "active.pdf")], estimates=[5.0])
    ui.start_file(0)
    ui.update_progress(0, 3, 4, "pages")
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())

    assert "active.pdf" in output.getvalue()
    rendered = output.getvalue()
    assert "[████░]" in rendered
    assert "time" in rendered
    assert "images" in rendered
    assert "tokens" in rendered


def test_format_duration_uses_one_decimal_for_all_units():
    assert utils.format_duration(0.5) == "0.5s"
    assert utils.format_duration(1.0) == "1.0s"
    assert utils.format_duration(65.25) == "1m 5.2s"
    assert utils.format_duration(3600.0) == "1h 0m"
    assert utils.format_duration(3665.25) == "1h 1m"
    assert utils.format_duration(3600 * 5 + 60 * 4) == "5h 4m"


def test_batch_ui_process_shows_bracketed_markers_without_error_summary(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt"), str(tmp_path / "broken.txt")])
    ui.statuses = ["[x]", "[!]"]
    ui.errors.append(("broken.txt", "conversion failed"))

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())
    rendered = output.getvalue()

    assert "[✓]" in rendered
    assert "[!]" in rendered
    assert "Error summary" not in rendered


def test_batch_ui_summary_contains_compact_stats(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt")])
    ui.total_tokens = 1234567
    ui.overwritten_count = 2
    ui.skipped_count = 1
    ui.errors.append(("broken.txt", "file or directory not found"))
    ui.add_result("Converted files", 1)
    ui.add_result("Overwritten text sources", 3)
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())
    rendered = output.getvalue()

    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH
    assert "─ Summary" in rendered
    assert "Errors: 1" in rendered
    assert "1_234_567" in rendered
    assert "Overwritten: 2" in rendered
    assert "Skipped: 1" in rendered

    result_output = StringIO()
    ui._console = Console(file=result_output, width=BATCH_UI_WIDTH, force_terminal=False)
    ui.print_results()
    results_rendered = result_output.getvalue()
    assert "─ Results" in results_rendered
    assert "overwritten text sources" in results_rendered
    assert "broken.txt" not in results_rendered


def test_batch_ui_places_current_file_by_remaining_queue(tmp_path: Path):
    files = [str(tmp_path / f"file_{index}.txt") for index in range(5)]
    ui = BatchUI(files)
    ui.current_idx = 3
    ui.statuses[3] = "[>]"

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._process_renderable())
    rendered = output.getvalue()

    assert rendered.index("file_3.txt") > rendered.index("file_0.txt")
    assert rendered.index("file_3.txt") > rendered.index("file_2.txt")
    assert "file_4.txt" in rendered
def test_batch_ui_uses_aligned_placeholders_and_lowercase_results(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt"), str(tmp_path / "broken.txt")])
    ui.complete_file(0, True, 1.2, images=0, tokens=0)
    ui.fail_file(1, "conversion failed")
    ui.add_result("Converted files", 1)
    ui.add_result("Overwritten text sources", 3)
    process_output = StringIO()
    Console(file=process_output, width=BATCH_UI_WIDTH, force_terminal=False).print(
        ui._process_renderable(final=True)
    )
    process_lines = process_output.getvalue().splitlines()
    broken_line = next(line for line in process_lines if "broken.txt" in line)
    assert "-" in broken_line
    assert broken_line.count("-") >= 3

    error_output = StringIO()
    ui._console = Console(file=error_output, width=BATCH_UI_WIDTH, force_terminal=False)
    ui.print_error_list()
    error_rendered = error_output.getvalue()
    assert "─ Error list (1)" in error_rendered
    error_lines = error_rendered.splitlines()
    error_line = next(line for line in error_lines if "broken.txt" in line)
    process_file_start = next(line.index("broken.txt") for line in process_lines if "broken.txt" in line)
    assert error_line.index("broken.txt") == process_file_start

    result_output = StringIO()
    ui._console = Console(file=result_output, width=BATCH_UI_WIDTH, force_terminal=False)
    ui.print_results()
    results_rendered = result_output.getvalue()
    result_line = next(line for line in results_rendered.splitlines() if "converted files" in line)
    assert result_line.index("converted files") >= result_line.index("1")
    assert "─ Results" in results_rendered
    assert "overwritten text sources" in results_rendered
    assert "#d2a6ff" not in results_rendered

@pytest.mark.parametrize("logger_was_disabled", [False, True])
def test_batch_ui_suppresses_and_restores_logger_during_live(
    tmp_path: Path, monkeypatch, logger_was_disabled: bool
):
    logger = utils.logger
    monkeypatch.setattr(logger, "disabled", logger_was_disabled)

    class FakeLive:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            assert logger.disabled is True

        def stop(self):
            assert logger.disabled is True

    monkeypatch.setattr("rich.live.Live", FakeLive)
    ui = BatchUI([str(tmp_path / "active.txt")])
    ui.can_redraw = True

    ui.start()
    assert logger.disabled is True
    ui.stop()

    assert logger.disabled is logger_was_disabled


def test_batch_ui_finish_stages_final_frame_before_stopping(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "done.txt")])
    ui.can_redraw = True

    class FakeLive:
        def __init__(self):
            self.events = []

        def update(self, renderable, refresh=False):
            self.events.append(("update", refresh, renderable.final))

        def stop(self):
            self.events.append(("stop",))

    live: Any = FakeLive()
    ui._live = live

    ui.finish()

    assert live.events == [("update", False, True), ("stop",)]
    assert ui._live is None


def test_run_batch_merges_success_after_conversion_errors(tmp_path: Path, monkeypatch):
    successful = tmp_path / "b-success.txt"
    successful.write_text("converted content\n", encoding="utf-8")
    failed = tmp_path / "z-failed.txt"
    failed.write_text("failure expected\n", encoding="utf-8")
    missing = tmp_path / "a-missing.txt"
    merged = tmp_path / "combined.md"
    events = []
    instances = []

    class RecordingBatchUI(BatchUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.can_redraw = False
            instances.append(self)

        def fail_file(self, index, reason):
            events.append(("error", self.files[index].name))
            super().fail_file(index, reason)

        def start_file(self, index, hint=""):
            events.append(("start", self.files[index].name))
            super().start_file(index, hint)

        def complete_file(self, index, success, duration, images=0, tokens=0, info=""):
            events.append(("complete", self.files[index].name, success))
            super().complete_file(index, success, duration, images, tokens, info)

        def finish(self):
            events.append(("finish",))
            super().finish()

        def print_summary(self):
            events.append(("print_summary",))

        def print_error_list(self):
            events.append(("print_errors",))

        def print_results(self):
            events.append(("print_results",))

    def convert_file(file_path, **kwargs):
        events.append(("convert", Path(file_path).name))
        if Path(file_path) == failed:
            kwargs["completion_callback"](False, 0.01, 0, 0)
            return False
        output = Path(file_path).parent / "hm_b-success_txt.md"
        output.write_text("converted content\n", encoding="utf-8")
        kwargs["completion_callback"](True, 0.01, 0, 0)
        return True

    monkeypatch.setattr(batch, "BatchUI", RecordingBatchUI)
    monkeypatch.setattr(batch, "get_conversion_estimate_seconds", lambda path: 0.5)
    monkeypatch.setattr(batch, "convert_file", convert_file)
    args = argparse.Namespace(
        files=[str(successful), str(failed), str(missing)],
        coordinator=False,
        overwrite=False,
        skip_existing=False,
        output_dir=None,
        include=[],
        exclude=[],
        stdout=False,
        confirm=False,
        right_click=False,
        merge=str(merged),
    )

    assert batch.run_batch(args) == 1

    assert events == [
        ("error", "a-missing.txt"),
        ("start", "b-success.txt"),
        ("convert", "b-success.txt"),
        ("complete", "b-success.txt", True),
        ("start", "z-failed.txt"),
        ("convert", "z-failed.txt"),
        ("complete", "z-failed.txt", False),
        ("finish",),
        ("print_summary",),
        ("print_errors",),
        ("print_results",),
    ]
    assert "FILE: b-success.txt" in merged.read_text(encoding="utf-8")
    assert "# b-success.txt" not in merged.read_text(encoding="utf-8")
    assert "converted content" in merged.read_text(encoding="utf-8")

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(instances[0]._summary_renderable())
    rendered = output.getvalue()
    assert "Errors: 2" in rendered
    assert "Estimated: ~" in rendered
    assert "broken.txt" not in rendered
    assert instances[0].results == [("Merged documents", 1), ("Converted files", 1)]



def test_batch_ui_summary_preserves_seconds_for_minute_estimates(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "document.pdf")], estimates=[65.2])

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())

    rendered = output.getvalue()
    assert "Estimated: ~1m 5.2s" in rendered
    assert "Estimated total:" not in rendered
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH


def test_batch_ui_truncates_long_filenames_and_formats_tokens(tmp_path: Path):
    filename = "document_" + "x" * 160 + ".txt"
    ui = BatchUI([str(tmp_path / filename)])
    ui.start_file(0)
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())

    rendered = output.getvalue()
    assert "Tokens: ~1_234_567" not in rendered
    assert "….txt" in rendered
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH


def test_batch_ui_process_formats_long_durations_and_keeps_them_visible(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "long_running.txt")])
    ui.statuses = ["[x]"]
    ui.complete_file(0, True, 54 * 60, images=1, tokens=144840)

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._process_renderable(final=True))
    rendered = output.getvalue()

    assert "54m 0.0s" in rendered
    assert "~144_840" in rendered
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH

    ui.complete_file(0, True, 5 * 3600 + 4 * 60 + 59, images=1, tokens=144840)
    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._process_renderable(final=True))
    rendered = output.getvalue()

    assert "5h 4m" in rendered
    assert "5h 4m 59" not in rendered
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH


def test_batch_ui_summary_fits_three_digit_overwritten(tmp_path: Path):
    ui = BatchUI([str(tmp_path / "file.txt")], estimates=[103.2])
    ui._batch_started_at = time.monotonic() - 65.2
    ui.total_tokens = 144840
    ui.overwritten_count = 999
    ui.errors = [("broken.txt", "failed")]

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())
    rendered = output.getvalue()

    assert "Overwritten: 999" in rendered
    assert "Time passed: 1m 5." in rendered
    assert "Estimated: ~1m 43.2s" in rendered
    assert "…" not in rendered.splitlines()[2]
    assert len(max(rendered.splitlines(), key=len)) <= BATCH_UI_WIDTH
