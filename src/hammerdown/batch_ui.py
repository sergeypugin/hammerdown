from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich.cells import cell_len

from hammerdown.ui_constants import (
    BATCH_UI_WIDTH,
    BATCH_UI_VISIBLE_FILES,
    PROCESS_COMPLETE_COLOR,
    PROCESS_RUNNING_COLOR,
    PROGRESS_BAR_WIDTH,
    PROGRESS_DISPLAY_DELAY,
    QUEUE_FILE_WIDTH,
    QUEUE_IMAGES_WIDTH,
    QUEUE_MARKER_WIDTH,
    QUEUE_TIME_WIDTH,
    QUEUE_TOKENS_WIDTH,
    SUMMARY_COLOR,
    SUMMARY_SEPARATOR_WIDTH,
)
from hammerdown.formatting import format_duration
from hammerdown.path_utils import enable_vt_mode

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

    def __init__(
        self,
        file_paths: list[str],
        quiet: bool = False,
        estimates: list[float | None] | None = None,
    ):
        self.files = [Path(path) for path in file_paths]
        self.quiet = quiet
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
        self.is_tty = sys.stdout.isatty() and not quiet
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
        self.summary_messages: list[str] = []
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

        if self._console is None:
            self._console = Console(width=BATCH_UI_WIDTH, force_terminal=sys.stdout.isatty())

        error_table = Table.grid(expand=True, padding=(0, 1))
        error_table.add_column(no_wrap=True, overflow="ellipsis")
        error_table.add_column(ratio=1, style="white", overflow="ellipsis")
        for file_name, reason in self.errors:
            error_table.add_row(Text(f"[!] {file_name}", style="red"), Text(reason, style="white"))
        self._console.print(
            Panel(
                error_table,
                title=Text(f"Error list ({len(self.errors)})", style="red"),
                border_style="red",
                box=box.ROUNDED,
                width=BATCH_UI_WIDTH,
            )
        )

    def add_summary_message(self, message: str) -> None:
        self.summary_messages.append(message)

    def render(self) -> None:
        if self._live is not None:
            self._live.update(_LiveBatchRenderable(self), refresh=True)

    def _renderable(self, final: bool = False):
        from rich.console import Group

        return Group(self._summary_renderable(), self._process_renderable(final=final))

    def _process_renderable(self, final: bool = False):
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        total = len(self.files)
        completed = sum(status in {"[x]", "[!]"} for status in self.statuses)
        percent = completed / total if total else 0
        title = Text(
            f"Processing {total} files {percent:.0%} ({completed}/{total})",
            style=PROCESS_COMPLETE_COLOR if final else PROCESS_RUNNING_COLOR,
        )

        queue = Table.grid(expand=True, padding=(0, 1))
        queue.add_column(width=QUEUE_MARKER_WIDTH, no_wrap=True)
        queue.add_column(width=QUEUE_FILE_WIDTH, overflow="ellipsis", no_wrap=True)
        queue.add_column(width=QUEUE_TIME_WIDTH, no_wrap=True, justify="right")
        queue.add_column(width=QUEUE_IMAGES_WIDTH, no_wrap=True, justify="right")
        queue.add_column(width=QUEUE_TOKENS_WIDTH, no_wrap=True, justify="right")
        queue.add_row(
            Text("state", style="dim", no_wrap=True),
            Text("file", style="dim", no_wrap=True),
            Text("time", style="dim", no_wrap=True),
            Text("images", style="dim", no_wrap=True),
            Text("tokens", style="dim", no_wrap=True),
        )
        if self.current_idx < 0:
            start = 0
        else:
            remaining = max(0, total - self.current_idx - 1)
            target_position = 4 - min(remaining, 2)
            start = max(0, min(self.current_idx - target_position, total - BATCH_UI_VISIBLE_FILES))
        end = min(total, start + BATCH_UI_VISIBLE_FILES)
        for index in range(start, end):
            state = self.statuses[index]
            marker, style = self._marker_for(index, state)
            if state == "[ ]":
                duration = self._estimate_label(index)
                images = ""
                tokens = ""
            elif state == "[>]":
                started_at = self._file_started_at[index]
                elapsed_file = time.monotonic() - started_at if started_at is not None else 0.0
                duration = format_duration(elapsed_file)
                images = ""
                tokens = ""
            else:
                duration = self._file_durations[index]
                images = str(self._file_images[index]) if self._file_images[index] else ""
                tokens = f"~{self._file_tokens[index]:_}" if self._file_tokens[index] else ""
            queue.add_row(
                Text(marker, style=style, no_wrap=True),
                Text(_truncate_filename(self.files[index].name, QUEUE_FILE_WIDTH), style=style, no_wrap=True),
                Text(duration, style="dim" if state == "[ ]" else style, no_wrap=True),
                Text(images, style="dim" if state == "[ ]" else style, no_wrap=True),
                Text(tokens, style="dim" if state == "[ ]" else style, no_wrap=True),
            )
        for _ in range(BATCH_UI_VISIBLE_FILES - (end - start)):
            queue.add_row("", "", "", "", "")

        border_style = PROCESS_COMPLETE_COLOR if final else PROCESS_RUNNING_COLOR
        return Panel(
            queue,
            title=title,
            title_align="center",
            border_style=border_style,
            box=box.ROUNDED,
            width=BATCH_UI_WIDTH,
        )

    def _summary_renderable(self):
        from rich.console import Group
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        elapsed = time.monotonic() - self._batch_started_at if self._batch_started_at is not None else 0.0
        estimated_total = sum(value for value in self.estimates if value is not None)
        timing = Table.grid(expand=True, padding=(0, 1))
        timing.add_column(width=18, no_wrap=True, overflow="ellipsis")
        timing.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        timing.add_column(width=14, no_wrap=True, overflow="ellipsis")
        completed = sum(status in {"[x]", "[!]"} for status in self.statuses)
        failed = len(self.errors)
        error_label = Text(f"Errors: {failed}", style="red") if failed else Text("")
        timing.add_row(
            f"Time passed: {format_duration(elapsed)}",
            f"Estimated total: ~{format_duration(estimated_total)}" if estimated_total else "",
            error_label,
        )
        timing.add_row(f"Completed: {completed}", f"Tokens: ~{self.total_tokens:_}", f"Overwritten: {self.overwritten_count}")
        if self.skipped_count:
            timing.add_row(f"Skipped: {self.skipped_count}", "", "")
        summary_parts = [timing]
        if self.summary_messages:
            messages = Table.grid(expand=True, padding=(0, 1))
            messages.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
            for message in self.summary_messages:
                messages.add_row(Text("─" * SUMMARY_SEPARATOR_WIDTH, style=SUMMARY_COLOR))
                messages.add_row(Text(message, style=SUMMARY_COLOR))
            summary_parts.append(messages)
        return Panel(
            Group(*summary_parts),
            title=Text("Summary", style=SUMMARY_COLOR),
            title_align="center",
            border_style=SUMMARY_COLOR,
            box=box.ROUNDED,
            width=BATCH_UI_WIDTH,
        )

    def _marker_for(self, index: int, state: str) -> tuple[str, str]:
        if state == "[x]":
            return "[✓]", "green"
        if state == "[!]":
            return "[!]", "red"
        if state == "[>]":
            total = self._progress_total[index]
            current = self._progress_current[index]
            filled = int(round(PROGRESS_BAR_WIDTH * current / total)) if total else 0
            bar = "█" * filled + "░" * (PROGRESS_BAR_WIDTH - filled)
            return f"[{bar}]", "dark_orange"
        return "[ ]", "dim"

    def _estimate_label(self, index: int) -> str:
        estimate = self.estimates[index]
        return f"~{format_duration(estimate)}" if estimate is not None else ""

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
        elif not self.quiet:
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
        self.details[index] = ""
        self._file_durations[index] = ""
        self.errors.append((self.files[index].name, reason))
        if self.can_redraw:
            self.render()
        elif not self.quiet:
            logger.error("\033[38;2;157;47;52m[!] %s\033[0m", self.files[index].name)
            logger.error("Errors:\n  %s -- %s", self.files[index].name, reason)

    def complete_file(
        self,
        index: int,
        success: bool,
        duration: str,
        images: int = 0,
        tokens: int = 0,
        info: str = "",
    ) -> None:
        if success:
            self.statuses[index] = "[x]"
            self._file_durations[index] = duration
            self._file_images[index] = images
            self._file_tokens[index] = tokens
            self.total_tokens += tokens
            if "skipped" in info.lower():
                self.skipped_count += 1
            if "overwritten" in info.lower():
                self.overwritten_count += 1
            token_info = f", ~{tokens:_} tokens" if tokens > 0 else ""
            img_info = f", {images} images" if images > 0 else ""
            extra_info = ""
            self.details[index] = f"({duration}{img_info}{token_info}{extra_info})"
        else:
            self.statuses[index] = "[!]"
            self._file_durations[index] = duration
            self._file_images[index] = images
            self._file_tokens[index] = tokens
            self.details[index] = duration
            self.errors.append((self.files[index].name, info or "conversion failed"))
        if self.can_redraw:
            self.render()
        elif not self.quiet:
            if success:
                details = [duration]
                if images > 0:
                    details.append(f"{images} images")
                if tokens > 0:
                    details.append(f"~{tokens:_} tokens")
                if info:
                    details.append(info)
                logger.info("Completed %s (%s)", self.files[index].name, ", ".join(details))
            else:
                logger.error("Failed to convert %s%s", self.files[index].name, f" -- {info}" if info else "")


def _truncate_filename(filename: str, max_width: int) -> str:
    """Shorten a name without dropping its extension."""
    if cell_len(filename) <= max_width:
        return filename

    path = Path(filename)
    suffix = "".join(path.suffixes)
    stem = filename[: -len(suffix)] if suffix else filename
    ellipsis = "…"
    suffix_width = cell_len(suffix)
    if suffix_width + cell_len(ellipsis) > max_width:
        suffix = suffix[-max(0, max_width - cell_len(ellipsis)) :]
        suffix_width = cell_len(suffix)
    stem_width = max(0, max_width - suffix_width - cell_len(ellipsis))
    stem_prefix = stem[:stem_width]
    return f"{stem_prefix}{ellipsis}{suffix}"
