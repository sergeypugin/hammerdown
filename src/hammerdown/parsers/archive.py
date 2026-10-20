from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from .html import convert_html

ProgressCallback = Callable[[int, int, str], None]


def convert_zip(
    file_path: str | os.PathLike[str],
    asset_dir: str | os.PathLike[str],
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    source_path = Path(file_path)
    if not source_path.is_file():
        return None, 0

    try:
        with tempfile.TemporaryDirectory(prefix="hammerdown-zip-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            
            with zipfile.ZipFile(source_path, "r") as zip_ref:
                zip_ref.extractall(tmp_path)

            # Find HTML file in the root of the zip or nested
            html_files = list(tmp_path.rglob("*.html")) + list(tmp_path.rglob("*.htm"))
            if not html_files:
                return None, 0

            # Prefer HTML file at root or closest to root
            html_files.sort(key=lambda p: len(p.parts))
            target_html = html_files[0]

            # Use html converter on extracted HTML
            return convert_html(target_html, asset_dir, progress_callback=progress_callback)

    except Exception:
        return None, 0


CONVERTERS = {
    ".zip": convert_zip,
}
