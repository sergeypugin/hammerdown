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


def enable_vt_mode() -> bool:
    if os.name == "nt":
        import ctypes
        try:
            kernel32 = ctypes.windll.kernel32
            hStdOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode))
            kernel32.SetConsoleMode(hStdOut, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
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
        if self.is_tty:
            enable_vt_mode()

        self.statuses: list[str] = ["[ ]"] * len(self.files)
        self.details: list[str] = [""] * len(self.files)
        self.current_idx: int = -1
        self._rendered = False
        self._progress_started_at = 0.0

    def render(self) -> None:
        if self.quiet or not self.is_tty:
            return

        header = f"Processing {len(self.files)} file{'s' if len(self.files) != 1 else ''}:"
        lines = [header, ""]
        for i, f in enumerate(self.files):
            status = self.statuses[i]
            detail = f" {self.details[i]}" if self.details[i] else ""

            if status == "[x]":
                marker = f"{COLOR_GREEN}[x]{COLOR_RESET}"
                line = f"  {marker} {COLOR_GREEN}{f.name}{COLOR_RESET}{detail}"
            elif status == "[!]":
                marker = f"{COLOR_RED}[!]{COLOR_RESET}"
                line = f"  {marker} {COLOR_RED}{f.name}{COLOR_RESET}{detail}"
            elif status == "[>]":
                marker = f"{COLOR_ORANGE}[>]{COLOR_RESET}"
                line = f"  {marker} {COLOR_BOLD}{f.name}{COLOR_RESET}{detail}"
            else:
                marker = f"{COLOR_DIM}[ ]{COLOR_RESET}"
                line = f"  {marker} {COLOR_DIM}{f.name}{COLOR_RESET}"
            lines.append(line)
        lines.append("")  # Blank line after file queue list

        # Move cursor up if we already rendered once
        if self._rendered:
            # We move up by the number of lines we previously printed
            # (header + empty line + N files + trailing empty line)
            num_lines_to_move = len(self.files) + 3
            sys.stdout.write(f"\033[{num_lines_to_move}A")
        else:
            # First time rendering, add a newline to separate from previous prompt
            sys.stdout.write("\n")

        # Join lines and print. We use \033[K to clear each line to avoid artifacts.
        output = ""
        for line in lines:
            output += f"\r\033[K{line}\n"

        sys.stdout.write(output)
        sys.stdout.flush()
        self._rendered = True

    def start_file(self, index: int, hint: str = "") -> None:
        self.current_idx = index
        self._progress_started_at = time.monotonic()
        self.statuses[index] = "[>]"
        self.details[index] = hint
        if self.is_tty:
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
        if self.is_tty and time.monotonic() - self._progress_started_at >= PROGRESS_DISPLAY_DELAY:
            self.render()

    def complete_file(self, index: int, success: bool, duration: str, images: int = 0, tokens: int = 0) -> None:
        if success:
            self.statuses[index] = "[x]"
            token_info = f", ~{tokens} tokens" if tokens > 0 else ""
            img_info = f", {images} images" if images > 0 else ""
            self.details[index] = f"({duration}{img_info}{token_info})"
        else:
            self.statuses[index] = "[!]"
            self.details[index] = "(failed)"
        if self.is_tty:
            self.render()
        elif not self.quiet:
            if success:
                details = [duration]
                if images > 0:
                    details.append(f"{images} images")
                if tokens > 0:
                    details.append(f"~{tokens} tokens")
                logger.info("Completed %s (%s)", self.files[index].name, ", ".join(details))
            else:
                logger.info("Failed to convert %s", self.files[index].name)


def format_progress_bar(current: int, total: int, unit: str = "pages", bar_length: int = 20) -> str:
    if total <= 0:
        return f"{current} {unit}"
    percent = min(100.0, max(0.0, (current / total) * 100))
    filled_len = int(round(bar_length * current / float(total)))
    bar = "█" * filled_len + "░" * (bar_length - filled_len)
    return f"[{bar}] {percent:.0f}% ({current}/{total} {unit})"
