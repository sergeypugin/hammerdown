from __future__ import annotations

import logging
import os
import re
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
    return f"hammerdown_images_{stem}_{ext_clean}" if ext_clean else f"hammerdown_images_{stem}"


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
