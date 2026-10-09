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
