from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .batch_ui_render import (
    add_queue_columns as _add_queue_columns,
    add_result_columns as _add_result_columns,
    add_status_file_columns as _add_status_file_columns,
    estimate_label as _estimate_label,
    marker_for as _marker_for,
    panel_title as _panel_title,
    render_process_panel as _render_process_panel,
    render_renderable as _render_renderable,
    render_summary_panel as _render_summary_panel,
    truncate_filename as _truncate_filename,
)
from ..core.formatting import format_duration
from ..core.path_utils import enable_vt_mode
from .ui_constants import (
    BATCH_UI_WIDTH,
    PROGRESS_BAR_WIDTH,
    PROGRESS_DISPLAY_DELAY,
    QUEUE_FILE_WIDTH,
    RESULTS_COLOR,
)

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger("hammerdown")


class _LiveBatchRenderable:
    def __init__(self, batch_ui: BatchUI, final: bool = False):
        self.batch_ui = batch_ui
        self.final = final

    def __rich_console__(self, console, options):
        yield self.batch_ui._renderable(final=self.final)


class BatchUI:
    """Helper for managing an in-place updating batch conversion queue."""

    def __init__(self, file_paths: list[str], estimates: list[float | None] | None = None):
        self.files = [Path(path) for path in file_paths]
        self.estimates = estimates or [None] * len(self.files)
        if len(self.estimates) != len(self.files):
            raise ValueError("estimates must match file_paths")
        self._file_started_at: list[float | None] = [None] * len(self.files)
        self._batch_started_at: float | None = None
        self._progress_details: list[str] = [""] * len(self.files)
        self._progress_current: list[int] = [0] * len(self.files)
        self._progress_total: list[int] = [0] * len(self.files)
        self._file_durations: list[str] = [""] * len(self.files)
        self._file_images: list[int] = [0] * len(self.files)
        self._file_tokens: list[int] = [0] * len(self.files)
        self.is_tty = sys.stdout.isatty()
        self.can_redraw = self.is_tty
        if self.is_tty:
            self.can_redraw = enable_vt_mode()
        self.statuses: list[str] = ["[ ]"] * len(self.files)
        self.details: list[str] = [""] * len(self.files)
        self.current_idx: int = -1
        self._progress_started_at = 0.0
        self.errors: list[tuple[str, str]] = []
        self.total_tokens = 0
        self.skipped_count = 0
        self.overwritten_count = 0
        self.results: list[tuple[str, int]] = []
        self.converted_count = 0
        self.image_count = 0
        self._logger_was_disabled = False
        self._live = None
        self._console: Console | None = None

    def start(self) -> None:
        if not self.can_redraw:
            return
        from rich.console import Console
        from rich.live import Live

        self._logger_was_disabled = logger.disabled
        logger.disabled = True
        self._console = Console(width=BATCH_UI_WIDTH, force_terminal=True)
        self._live = Live(
            _LiveBatchRenderable(self),
            console=self._console,
            screen=False,
            refresh_per_second=8,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
            vertical_overflow="crop",
        )
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        if self.can_redraw:
            logger.disabled = self._logger_was_disabled

    def finish(self) -> None:
        if not self.can_redraw or self._live is None:
            return
        self._live.update(_LiveBatchRenderable(self, final=True), refresh=False)
        self.stop()

    def print_error_list(self) -> None:
        if not self.errors:
            return
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        self._console = self._console or Console(width=BATCH_UI_WIDTH, force_terminal=sys.stdout.isatty())
        error_table = Table.grid(expand=True, padding=(0, 0))
        _add_status_file_columns(error_table)
        for file_name, reason in self.errors:
            error_table.add_row(
                Text("[!]", style="red"),
                Text(_truncate_filename(file_name, QUEUE_FILE_WIDTH), style="red", no_wrap=True),
                Text(reason, style="white"),
            )
        self._console.print(
            Panel(
                error_table,
                title=_panel_title(f"Error list ({len(self.errors)})", "red"),
                title_align="left",
                border_style="red",
                box=box.ROUNDED,
                width=BATCH_UI_WIDTH,
            )
        )

    def add_result(self, label: str, count: int) -> None:
        if count > 0:
            self.results.append((label, count))

    def print_summary(self) -> None:
        from rich.console import Console

        if self._console is None:
            self._console = Console(width=BATCH_UI_WIDTH, force_terminal=sys.stdout.isatty())
        self._console.print(self._summary_renderable())

    def print_results(self) -> None:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        if self._console is None:
            self._console = Console(width=BATCH_UI_WIDTH, force_terminal=sys.stdout.isatty())
        table = Table.grid(expand=True, padding=(0, 0))
        _add_result_columns(table)
        for label, count in self.results:
            table.add_row(
                Text(f"{count:_}", style=RESULTS_COLOR),
                Text(label.lower(), style="white"),
            )
        self._console.print(
            Panel(
                table,
                title=_panel_title("Results", RESULTS_COLOR),
                title_align="left",
                border_style=RESULTS_COLOR,
                box=box.ROUNDED,
                width=BATCH_UI_WIDTH,
            )
        )

    def render(self) -> None:
        if self._live is not None:
            self._live.update(_LiveBatchRenderable(self), refresh=True)

    def _renderable(self, final: bool = False):
        return _render_renderable(self, final=final)

    def _process_renderable(self, final: bool = False):
        return _render_process_panel(self, final=final)

    def _summary_renderable(self):
        return _render_summary_panel(self)

    def _marker_for(self, index: int, state: str) -> tuple[str, str]:
        return _marker_for(self, index, state)

    def _estimate_label(self, index: int) -> str:
        return _estimate_label(self, index)

    def start_file(self, index: int, hint: str = "") -> None:
        self.current_idx = index
        self._progress_started_at = time.monotonic()
        self._batch_started_at = self._batch_started_at or self._progress_started_at
        self._file_started_at[index] = self._progress_started_at
        self._progress_details[index] = ""
        self._progress_current[index] = 0
        self._progress_total[index] = 0
        self._file_durations[index] = ""
        self._file_images[index] = 0
        self._file_tokens[index] = 0
        self.statuses[index] = "[>]"
        self.details[index] = hint
        if self.can_redraw:
            self.render()
        else:
            logger.info("Processing %s%s...", self.files[index].name, f" {hint}" if hint else "")

    def update_progress(self, index: int, current: int, total: int, unit: str = "pages") -> None:
        if total <= 0:
            return
        self._progress_current[index] = current
        self._progress_total[index] = total
        pct = int((current / total) * 100)
        bar_len = PROGRESS_BAR_WIDTH
        filled = int(round(bar_len * current / float(total)))
        bar = "█" * filled + "░" * (bar_len - filled)
        self._progress_details[index] = f"{bar} {pct}%"
        if self.can_redraw and time.monotonic() - self._progress_started_at >= PROGRESS_DISPLAY_DELAY:
            self.render()

    def fail_file(self, index: int, reason: str) -> None:
        self.statuses[index] = "[!]"
        self.details[index] = "-"
        self._file_durations[index] = "-"
        self._file_images[index] = 0
        self._file_tokens[index] = 0
        self.errors.append((self.files[index].name, reason))
        if self.can_redraw:
            self.render()

    def complete_file(
        self,
        index: int,
        success: bool,
        duration: str | float,
        images: int = 0,
        tokens: int = 0,
        info: str = "",
    ) -> None:
        duration_text = format_duration(duration) if isinstance(duration, (int, float)) else duration
        if success:
            self.statuses[index] = "[x]"
            self._file_durations[index] = duration_text
            self._file_images[index] = images
            self._file_tokens[index] = tokens
            self.image_count += images
            self.total_tokens += tokens
            if "skipped" not in info.lower():
                self.converted_count += 1
            if "skipped" in info.lower():
                self.skipped_count += 1
            if "overwritten" in info.lower():
                self.overwritten_count += 1
            token_info = f", ~{tokens:_} tokens" if tokens > 0 else ""
            img_info = f", {images} images" if images > 0 else ""
            self.details[index] = f"({duration_text}{img_info}{token_info})"
        else:
            self.statuses[index] = "[!]"
            self._file_durations[index] = "-"
            self._file_images[index] = 0
            self._file_tokens[index] = 0
            self.details[index] = "-"
            self.errors.append((self.files[index].name, info or "conversion failed"))
        if self.can_redraw:
            self.render()
        elif success:
            details = [duration_text]
            if images > 0:
                details.append(f"{images} images")
            if tokens > 0:
                details.append(f"~{tokens:_} tokens")
            if info:
                details.append(info)
            logger.info("Completed %s (%s)", self.files[index].name, ", ".join(details))
