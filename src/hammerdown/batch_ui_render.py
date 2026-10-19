from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich.cells import cell_len

from hammerdown.formatting import format_duration
from hammerdown.ui_constants import (
    BATCH_UI_VISIBLE_FILES,
    BATCH_UI_WIDTH,
    PROCESS_COMPLETE_COLOR,
    PROCESS_RUNNING_COLOR,
    PROGRESS_BAR_WIDTH,
    QUEUE_FILE_WIDTH,
    QUEUE_IMAGES_WIDTH,
    QUEUE_MARKER_WIDTH,
    QUEUE_SPACER_WIDTH,
    QUEUE_TIME_WIDTH,
    QUEUE_TOKENS_WIDTH,
    RESULTS_COLOR,
    SUMMARY_COLOR,
)

if TYPE_CHECKING:
    from hammerdown.batch_ui import BatchUI


def panel_title(label: str, style: str):
    from rich.text import Text

    return Text(label, style=style)


def add_status_file_columns(table) -> None:
    table.add_column(width=QUEUE_MARKER_WIDTH, justify="center", no_wrap=True)
    table.add_column(width=QUEUE_FILE_WIDTH, overflow="ellipsis", no_wrap=True)
    table.add_column(ratio=1, no_wrap=False, overflow="fold")


def add_result_columns(table) -> None:
    table.add_column(width=QUEUE_MARKER_WIDTH, justify="center", no_wrap=True)
    table.add_column(ratio=1, no_wrap=False, overflow="fold")


def add_queue_columns(table) -> None:
    table.add_column(width=QUEUE_MARKER_WIDTH, justify="center", no_wrap=True)
    table.add_column(width=QUEUE_FILE_WIDTH, overflow="ellipsis", no_wrap=True)
    table.add_column(width=QUEUE_TIME_WIDTH, no_wrap=True, justify="right")
    table.add_column(width=QUEUE_SPACER_WIDTH, no_wrap=True)
    table.add_column(width=QUEUE_IMAGES_WIDTH, no_wrap=True, justify="right")
    table.add_column(width=QUEUE_TOKENS_WIDTH, no_wrap=True, justify="right")


def truncate_filename(filename: str, max_width: int) -> str:
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


def marker_for(ui: BatchUI, index: int, state: str) -> tuple[str, str]:
    if state == "[x]":
        return "[✓]", "green"
    if state == "[!]":
        return "[!]", "red"
    if state == "[>]":
        total = ui._progress_total[index]
        current = ui._progress_current[index]
        filled = int(round(PROGRESS_BAR_WIDTH * current / total)) if total else 0
        bar = "█" * filled + "░" * (PROGRESS_BAR_WIDTH - filled)
        return f"[{bar}]", "dark_orange"
    return "[ ]", "dim"


def estimate_label(ui: BatchUI, index: int) -> str:
    estimate = ui.estimates[index]
    return f"~{format_duration(estimate)}" if estimate is not None else ""


def render_renderable(ui: BatchUI, final: bool = False):
    from rich.console import Group

    return Group(render_summary_panel(ui), render_process_panel(ui, final=final))


def render_process_panel(ui: BatchUI, final: bool = False):
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(ui.files)
    completed = sum(status in {"[x]", "[!]"} for status in ui.statuses)
    percent = completed / total if total else 0
    title = panel_title(
        f"Processing {total} files {percent:.0%} ({completed}/{total})",
        PROCESS_COMPLETE_COLOR if final else PROCESS_RUNNING_COLOR,
    )

    queue = Table.grid(expand=True, padding=(0, 0))
    add_queue_columns(queue)
    queue.add_row(
        Text("state", style="dim", no_wrap=True),
        Text("file", style="dim", no_wrap=True),
        Text("time", style="dim", no_wrap=True),
        Text("", style="dim", no_wrap=True),
        Text("images", style="dim", no_wrap=True),
        Text("tokens", style="dim", no_wrap=True),
    )
    if ui.current_idx < 0:
        start = 0
    else:
        remaining = max(0, total - ui.current_idx - 1)
        target_position = 4 - min(remaining, 2)
        start = max(0, min(ui.current_idx - target_position, total - BATCH_UI_VISIBLE_FILES))
    end = min(total, start + BATCH_UI_VISIBLE_FILES)
    for index in range(start, end):
        state = ui.statuses[index]
        marker, style = marker_for(ui, index, state)
        if state == "[ ]":
            duration = estimate_label(ui, index)
            images = ""
            tokens = ""
        elif state == "[>]":
            started_at = ui._file_started_at[index]
            elapsed_file = time.monotonic() - started_at if started_at is not None else 0.0
            elapsed_str = format_duration(elapsed_file)
            est = estimate_label(ui, index)
            duration = f"{elapsed_str} / {est}" if est else elapsed_str
            if cell_len(duration) > QUEUE_TIME_WIDTH:
                duration = elapsed_str
            images = ""
            tokens = ""
        elif state == "[!]":
            duration = "-"
            images = "-"
            tokens = "-"
        else:
            duration = ui._file_durations[index]
            images = str(ui._file_images[index]) if ui._file_images[index] else "-"
            tokens = f"~{ui._file_tokens[index]:_}" if ui._file_tokens[index] else ""
        queue.add_row(
            Text(marker, style=style, no_wrap=True),
            Text(truncate_filename(ui.files[index].name, QUEUE_FILE_WIDTH), style=style, no_wrap=True),
            Text(duration, style="dim" if state == "[ ]" else style, no_wrap=True),
            Text("", no_wrap=True),
            Text(images, style="dim" if state == "[ ]" else style, no_wrap=True),
            Text(tokens, style="dim" if state == "[ ]" else style, no_wrap=True),
        )
    for _ in range(BATCH_UI_VISIBLE_FILES - (end - start)):
        queue.add_row("", "", "", "", "", "")

    border_style = PROCESS_COMPLETE_COLOR if final else PROCESS_RUNNING_COLOR
    return Panel(
        queue,
        title=title,
        title_align="left",
        border_style=border_style,
        box=box.ROUNDED,
        width=BATCH_UI_WIDTH,
    )


def render_summary_panel(ui: BatchUI):
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    elapsed = time.monotonic() - ui._batch_started_at if ui._batch_started_at is not None else 0.0
    estimated_total = sum(value for value in ui.estimates if value is not None)
    timing = Table.grid(expand=True, padding=(0, 0))
    timing.add_column(width=22, no_wrap=True, overflow="ellipsis")
    timing.add_column(width=22, no_wrap=True, overflow="ellipsis")
    timing.add_column(width=16, no_wrap=True, overflow="ellipsis")
    completed = sum(status in {"[x]", "[!]"} for status in ui.statuses)
    failed = len(ui.errors)
    error_label = Text(f"Errors: {failed}", style="red") if failed else Text("")
    timing.add_row(
        f"Time passed: {format_duration(elapsed)}",
        f"Estimated: ~{format_duration(estimated_total)}" if estimated_total else "",
        error_label,
    )
    timing.add_row(f"Completed: {completed}", f"Tokens: ~{ui.total_tokens:_}", f"Overwritten: {ui.overwritten_count}")
    if ui.skipped_count:
        timing.add_row(f"Skipped: {ui.skipped_count}", "", "")
    return Panel(
        Group(timing),
        title=panel_title("Summary", SUMMARY_COLOR),
        title_align="left",
        border_style=SUMMARY_COLOR,
        box=box.ROUNDED,
        width=BATCH_UI_WIDTH,
    )
