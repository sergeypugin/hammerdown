from __future__ import annotations

import logging

from .ui.batch_ui import BatchUI, _LiveBatchRenderable
from .core.description import APP_DESCRIPTION
from .core.formatting import format_duration, format_progress_bar
from .core.path_utils import enable_vt_mode, get_images_dir_name, normalize_path
from .ui.ui_constants import (
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
from .ui import ui_constants
from . import SUPPORTED_EXTENSIONS

logger = logging.getLogger("hammerdown")


def get_app_description() -> str:
    from .ui import ui_constants
    from . import SUPPORTED_EXTENSIONS

    formats = ", ".join(ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS)
    return (
        f"{APP_DESCRIPTION}\n\n"
        f"{ui_constants.COLOR_ORANGE}Supported formats:{ui_constants.COLOR_RESET} {formats}\n\n"
        f"Run {ui_constants.COLOR_CYAN}'hammerdown --help'{ui_constants.COLOR_RESET} for usage."
    )


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