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
        quiet=True,
        estimates=[1.0, 2.0],
    )
    process_output = StringIO()
    Console(file=process_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._renderable())
    summary_output = StringIO()
    Console(file=summary_output, width=BATCH_UI_WIDTH, force_terminal=False).print(ui._summary_renderable())

    assert "~1.0s" in process_output.getvalue()
    assert "~2.0s" in process_output.getvalue()
    assert "~3.0s" in summary_output.getvalue()
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
    time.sleep(0.11)
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
    rendered = output.getvalue()
    assert "[████░░]" in rendered
    assert "time" in rendered
    assert "images" in rendered
    assert "tokens" in rendered


def test_format_duration_uses_one_decimal_for_all_units():
    assert utils.format_duration(0.5) == "0.5s"
    assert utils.format_duration(1.0) == "1.0s"
    assert utils.format_duration(65.25) == "1m 5.2s"
    assert utils.format_duration(3665.25) == "1h 1m 5.2s"


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
    assert "1_234_567" in rendered
    assert "Overwritten: 2" in rendered
    assert "Skipped: 1" in rendered
    assert "Merged 4 documents into TODELETE.md" in rendered
    assert "─" in rendered


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
    ui = BatchUI([str(tmp_path / "done.txt")], quiet=True)
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

        def add_summary_message(self, message):
            assert merged.is_file()
            assert "converted content" in merged.read_text(encoding="utf-8")
            events.append(("summary", message))
            super().add_summary_message(message)

        def finish(self):
            events.append(("finish",))
            super().finish()

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
        in_place=False,
        overwrite=False,
        skip_existing=False,
        quiet=True,
        merge=str(merged),
    )

    assert batch.run_batch(args) == 1

    message = "Merged 1 documents into combined.md"
    assert events == [
        ("error", "a-missing.txt"),
        ("start", "b-success.txt"),
        ("convert", "b-success.txt"),
        ("complete", "b-success.txt", True),
        ("start", "z-failed.txt"),
        ("convert", "z-failed.txt"),
        ("complete", "z-failed.txt", False),
        ("summary", message),
        ("finish",),
    ]
    assert "# b-success.txt\n\nconverted content" in merged.read_text(encoding="utf-8")

    output = StringIO()
    Console(file=output, width=BATCH_UI_WIDTH, force_terminal=False).print(instances[0]._summary_renderable())
    rendered = output.getvalue()
    assert "Errors: 2" in rendered
    assert rendered.index("─") < rendered.index(message)


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
