from __future__ import annotations

import logging

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
)

logger = logging.getLogger("hammerdown")

__all__ = [
    "BatchUI",
    "_LiveBatchRenderable",
    "enable_vt_mode",
    "format_duration",
    "format_progress_bar",
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
