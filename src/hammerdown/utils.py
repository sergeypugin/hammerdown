from __future__ import annotations

import logging
import os
import re

import sys
import time
from pathlib import Path

logger = logging.getLogger("hammerdown")

COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[38;2;167;201;57m"   # #a7c939
COLOR_ORANGE = "\033[38;2;236;124;57m"  # #ec7c39
COLOR_RED = "\033[38;2;157;47;52m"     # #9d2f34
COLOR_DIM = "\033[90m"                  # Dim gray
COLOR_BOLD = "\033[1m"
PROGRESS_DISPLAY_DELAY = 0.5
BATCH_UI_WIDTH = 80
BATCH_UI_VISIBLE_FILES = 5


def enable_vt_mode() -> bool:
    if os.name == "nt":
        import ctypes
        try:
            kernel32 = ctypes.windll.kernel32
            hStdOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if not kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode)):
                return False
            return bool(kernel32.SetConsoleMode(hStdOut, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


def normalize_path(path_str: str | os.PathLike[str]) -> str:
    value = os.fspath(path_str).strip().strip("'\"")
    if not value:
        return ""

    if os.name == "nt":
        if value.lower().startswith("/mnt/"):
            parts = value.split("/")
            if len(parts) >= 3 and len(parts[2]) == 1:
                value = f"{parts[2].upper()}:\\" + "\\".join(parts[3:])
    else:
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
        if match:
            value = f"/mnt/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/') }"

    return str(Path(value).expanduser().resolve())


def get_images_dir_name(file_path: str | os.PathLike[str]) -> str:
    source = Path(file_path)
    stem = source.stem
    ext_clean = source.suffix.lower().lstrip(".")
    return f"hm_images_{stem}_{ext_clean}" if ext_clean else f"hm_images_{stem}"


def format_duration(seconds: float) -> str:
    if seconds < 1.0:
        return f"{seconds:.2f}s"
    total_seconds = int(round(seconds))
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        rem_seconds = total_seconds % 60
        return f"{minutes}m{rem_seconds}s" if rem_seconds else f"{minutes}m"
    hours = total_seconds // 3600
    rem_minutes = int(round((total_seconds % 3600) / 60))
    return f"{hours}h{rem_minutes}m" if rem_minutes else f"{hours}h"


class BatchUI:
    """Helper for managing an in-place updating batch conversion queue."""

    def __init__(self, file_paths: list[str], quiet: bool = False):
        self.files = [Path(p) for p in file_paths]
        self.quiet = quiet
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
        self._live = None
        self._console = None

    def start(self) -> None:
        if not self.can_redraw:
            return
        from rich.console import Console
        from rich.live import Live

        self._console = Console(width=BATCH_UI_WIDTH, force_terminal=True)
        self._live = Live(
            self._renderable(),
            console=self._console,
            screen=True,
            refresh_per_second=8,
            transient=False,
            vertical_overflow="crop",
        )
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
            if self._console is not None:
                self._console.print(self._renderable())

    def print_error_list(self) -> None:
        if not self.errors:
            return
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        from rich.console import Console

        if self._console is None:
            self._console = Console(width=BATCH_UI_WIDTH, force_terminal=sys.stdout.isatty())

        error_table = Table.grid(expand=True, padding=(0, 1))
        error_table.add_column(style="bold red")
        error_table.add_column(ratio=1, style="red")
        for file_name, reason in self.errors:
            error_table.add_row(f"[!] {file_name}", reason)
        self._console.print(
            Panel(
                error_table,
                title=f"Error list ({len(self.errors)})",
                border_style="red",
                box=box.ROUNDED,
                width=BATCH_UI_WIDTH,
            )
        )

    def render(self) -> None:
        if self._live is not None:
            self._live.update(self._renderable(), refresh=True)

    def _renderable(self):
        from rich import box
        from rich.console import Group
        from rich.panel import Panel
        from rich.progress_bar import ProgressBar
        from rich.table import Table
        from rich.text import Text

        total = len(self.files)
        completed = sum(status in {"[x]", "[!]"} for status in self.statuses)
        succeeded = sum(status == "[x]" for status in self.statuses)
        failed = len(self.errors)
        percent = completed / total if total else 0

        summary = Table.grid(expand=True, padding=(0, 1))
        summary.add_column(ratio=1)
        summary.add_row(f"Processing {total} files    {percent:.0%}    {completed} / {total}")
        summary.add_row(ProgressBar(total=100, completed=percent * 100, pulse=False))
        summary.add_row(f"Success: {succeeded}    Skipped: {self.skipped_count}    Errors: {failed}")
        summary.add_row(f"Tokens: ~{self.total_tokens}    Overwritten: {self.overwritten_count}")

        queue = Table.grid(expand=True, padding=(0, 1))
        queue.add_column(width=2, no_wrap=True)
        queue.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        if self.current_idx < 0:
            start = 0
        else:
            start = max(0, min(self.current_idx - 2, total - BATCH_UI_VISIBLE_FILES))
        end = min(total, start + BATCH_UI_VISIBLE_FILES)
        for index in range(start, end):
            state = self.statuses[index]
            marker, style = {
                "[x]": ("✓", "green"),
                "[!]": ("!", "red"),
                "[>]": (">", "dark_orange"),
                "[ ]": (" ", "dim"),
            }[state]
            queue.add_row(Text(marker, style=style), Text(self.files[index].name, style=style, no_wrap=True))
        for _ in range(BATCH_UI_VISIBLE_FILES - (end - start)):
            queue.add_row("", "")

        sections = [Panel(Group(summary, queue), box=box.ROUNDED, padding=(0, 1), width=BATCH_UI_WIDTH)]
        recent = self.errors[-2:]
        error_table = Table.grid(expand=True, padding=(0, 1))
        error_table.add_column(style="red", no_wrap=True, overflow="ellipsis")
        error_table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        for index in range(2):
            if index < len(recent):
                file_name, reason = recent[index]
                error_table.add_row(f"[!] {file_name}", reason)
            else:
                error_table.add_row("", "")
        sections.append(
            Panel(
                error_table,
                title=f"Error summary (last {len(recent)} of {failed})",
                border_style="red" if failed else "dim",
                width=BATCH_UI_WIDTH,
            )
        )
        return Group(*sections)

    def start_file(self, index: int, hint: str = "") -> None:
        self.current_idx = index
        self._progress_started_at = time.monotonic()
        self.statuses[index] = "[>]"
        self.details[index] = hint
        if self.can_redraw:
            self.render()
        elif not self.quiet:
            logger.info("Processing %s%s...", self.files[index].name, f" {hint}" if hint else "")

    def update_progress(self, index: int, current: int, total: int, unit: str = "pages") -> None:
        if total <= 0:
            return
        pct = int((current / total) * 100)
        bar_len = 10
        filled = int(round(bar_len * current / float(total)))
        bar = "█" * filled + "░" * (bar_len - filled)
        self.details[index] = f"[{bar}] {pct}% ({current}/{total} {unit})"
        if self.can_redraw and time.monotonic() - self._progress_started_at >= PROGRESS_DISPLAY_DELAY:
            self.render()

    def fail_file(self, index: int, reason: str) -> None:
        self.statuses[index] = "[!]"
        self.details[index] = ""
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
            self.total_tokens += tokens
            if "skipped" in info.lower():
                self.skipped_count += 1
            if "overwritten" in info.lower():
                self.overwritten_count += 1
            token_info = f", ~{tokens} tokens" if tokens > 0 else ""
            img_info = f", {images} images" if images > 0 else ""
            extra_info = f", {info}" if info else ""
            self.details[index] = f"({duration}{img_info}{token_info}{extra_info})"
        else:
            self.statuses[index] = "[!]"
            self.details[index] = ""
            self.errors.append((self.files[index].name, info or "conversion failed"))
        if self.can_redraw:
            self.render()
        elif not self.quiet:
            if success:
                details = [duration]
                if images > 0:
                    details.append(f"{images} images")
                if tokens > 0:
                    details.append(f"~{tokens} tokens")
                if info:
                    details.append(info)
                logger.info("Completed %s (%s)", self.files[index].name, ", ".join(details))
            else:
                logger.error("Failed to convert %s%s", self.files[index].name, f" -- {info}" if info else "")


def format_progress_bar(current: int, total: int, unit: str = "pages", bar_length: int = 20) -> str:
    if total <= 0:
        return f"{current} {unit}"
    percent = min(100.0, max(0.0, (current / total) * 100))
    filled_len = int(round(bar_length * current / float(total)))
    bar = "█" * filled_len + "░" * (bar_length - filled_len)
    return f"[{bar}] {percent:.0f}% ({current}/{total} {unit})"
