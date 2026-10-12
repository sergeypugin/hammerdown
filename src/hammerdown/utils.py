from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("hammerdown")


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


class TerminalUI:
    """Helper for managing persistent batch progress display in the terminal."""
    def __init__(self, total_files: int, quiet: bool = False):
        self.total_files = total_files
        self.quiet = quiet
        self.completed_files = 0
        self.is_tty = sys.stdout.isatty() and not quiet
        self._last_len = 0

    def print_queue(self, files: list[Path]):
        if self.quiet:
            return
        print(f"\nQueueing {len(files)} files for conversion:")
        for f in files:
            print(f" [ ] {f.name}")
        print()

    def start_file(self, filename: str, est_hint: str):
        if self.quiet:
            return
        if self.is_tty:
            # Add an empty line before processing to separate from previous/list
            print(f"\nProcessing \"{filename}\"{est_hint}\n")
        else:
            logger.info("Processing %s%s...", filename, est_hint)

    def update_progress(self, current: int, total: int, unit: str, filename: str):
        if self.quiet or not self.is_tty:
            return
        bar_str = format_progress_bar(current, total, unit=unit)
        line = f"\r{bar_str}"
        sys.stdout.write(line.ljust(self._last_len))
        sys.stdout.flush()
        self._last_len = max(self._last_len, len(line))

    def complete_file(self, filename: str, duration_str: str, images: int, success: bool):
        if self.quiet:
            return
        self.completed_files += 1
        if self.is_tty:
            # Clear the progress bar line
            sys.stdout.write(f"\r{' ' * self._last_len}\r")
            # Move cursor up to the "Processing" line to mark it as completed
            # ESC[2A moves up 2 lines (one for the empty line, one for the processing line)
            # Actually, the layout is:
            # Processing "file" (hint)
            # <empty line>
            # [progress bar]
            # So we are on the progress bar line. We want to overwrite the "Processing" line.
            # But let's keep it simple and just print the completion status.
            status = "v" if success else "x"
            print(f"[{status}] Completed {filename} in {duration_str} ({images} images)")
            self._last_len = 0
        else:
            logger.info("Completed %s in %s (%d images)", filename, duration_str, images)

    def print_summary(self):
        if self.quiet:
            return
        print(f"\nSuccessfully converted {self.completed_files} of {self.total_files} files.")
        if os.name == "nt":
            input("\nPress Enter to close...")
        else:
            print("Done.")


def format_progress_bar(current: int, total: int, unit: str = "pages", bar_length: int = 20) -> str:
    if total <= 0:
        return f"{current} {unit}"
    percent = min(100.0, max(0.0, (current / total) * 100))
    filled_len = int(round(bar_length * current / float(total)))
    bar = "█" * filled_len + "░" * (bar_length - filled_len)
    return f"[{bar}] {percent:.0f}% ({current}/{total} {unit})"
