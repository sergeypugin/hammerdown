from __future__ import annotations

import logging
import os
from pathlib import Path

from hammerdown.batch_ui import BatchUI, _LiveBatchRenderable
from hammerdown.formatting import format_duration, format_progress_bar
from hammerdown.path_utils import enable_vt_mode, get_images_dir_name, normalize_path
from hammerdown.ui_constants import (
    BATCH_UI_VISIBLE_FILES,
    BATCH_UI_WIDTH,
    COLOR_BOLD,
    COLOR_DIM,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_RESET,
    PROCESS_COMPLETE_COLOR,
    PROCESS_RUNNING_COLOR,
    PROGRESS_BAR_WIDTH,
    PROGRESS_DISPLAY_DELAY,
    QUEUE_FILE_WIDTH,
    QUEUE_IMAGES_WIDTH,
    QUEUE_MARKER_WIDTH,
    QUEUE_TIME_WIDTH,
    QUEUE_TOKENS_WIDTH,
    RESULTS_COLOR,
    SUMMARY_COLOR,
    SUMMARY_SEPARATOR_WIDTH,
    BATCH_UI_WIDTH,
    BATCH_UI_VISIBLE_FILES,
)

logger = logging.getLogger("hammerdown")


def get_app_description() -> str:
    """Read and return the short app description from README.md."""
    # Try to find README.md relative to this file (src/hammerdown/utils.py -> ../../README.md)
    readme_path = Path(__file__).resolve().parent.parent.parent / "README.md"
    if readme_path.is_file():
        try:
            content = readme_path.read_text(encoding="utf-8")
            # Extract first paragraph after the title (skip badges and logo)
            lines = content.splitlines()
            in_description = False
            desc_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("# hammerdown"):
                    in_description = True
                    continue
                if in_description:
                    if not stripped:
                        if desc_lines:  # stop at first blank line after we started
                            break
                        continue
                    # Skip badge lines (starting with [![), logo div, and HTML tags
                    if stripped.startswith("[!"):
                        continue
                    if stripped.startswith("<div"):
                        continue
                    if stripped.startswith("</div>"):
                        continue
                    if stripped.startswith("<img"):
                        continue
                    if stripped.startswith("## "):  # stop at first section
                        break
                    if stripped.startswith("```"):  # stop at code blocks
                        break
                    desc_lines.append(stripped)
            if desc_lines:
                base = " ".join(desc_lines)
                # Ensure first letter is lowercase
                if base:
                    base = base[0].lower() + base[1:]
                # Append supported formats with colors
                from hammerdown import SUPPORTED_EXTENSIONS
                from hammerdown.ui_constants import COLOR_GREEN, COLOR_ORANGE, COLOR_RESET, COLOR_BOLD
                formats = ", ".join(ext.lstrip('.') for ext in SUPPORTED_EXTENSIONS)
                return f"{COLOR_BOLD}\033[38;2;254;180;84mhammerdown{COLOR_RESET} {base}\n\n{COLOR_ORANGE}Supported formats:{COLOR_RESET} {formats}"
        except Exception:
            pass
    # Fallback
    from hammerdown import SUPPORTED_EXTENSIONS
    from hammerdown.ui_constants import COLOR_GREEN, COLOR_ORANGE, COLOR_RESET, COLOR_BOLD
    formats = ", ".join(ext.lstrip('.') for ext in SUPPORTED_EXTENSIONS)
    return f"{COLOR_BOLD}\033[38;2;254;180;84mhammerdown{COLOR_RESET} convert PDF and office documents to Markdown\n\n{COLOR_ORANGE}Supported formats:{COLOR_RESET} {formats}"


__all__ = [
    "BatchUI",
    "_LiveBatchRenderable",
    "enable_vt_mode",
    "format_duration",
    "format_progress_bar",
    "get_app_description",
    "get_images_dir_name",
    "normalize_path",
    "COLOR_BOLD",
    "COLOR_DIM",
    "COLOR_GREEN",
    "COLOR_ORANGE",
    "COLOR_RED",
    "COLOR_RESET",
    "PROCESS_COMPLETE_COLOR",
    "PROCESS_RUNNING_COLOR",
    "PROGRESS_BAR_WIDTH",
    "PROGRESS_DISPLAY_DELAY",
    "QUEUE_FILE_WIDTH",
    "QUEUE_IMAGES_WIDTH",
    "QUEUE_MARKER_WIDTH",
    "QUEUE_TIME_WIDTH",
    "QUEUE_TOKENS_WIDTH",
    "RESULTS_COLOR",
    "SUMMARY_COLOR",
    "SUMMARY_SEPARATOR_WIDTH",
    "BATCH_UI_WIDTH",
    "BATCH_UI_VISIBLE_FILES",
]
