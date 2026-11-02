from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from hammerdown.core.path_utils import get_images_dir_name
from .html import convert_html

ProgressCallback = Callable[[int, int, str], None]

MAX_ZIP_MEMBERS = 1000
MAX_ZIP_UNCOMPRESSED_SIZE = 100 * 1024 * 1024


def _safe_zip_member_path(member_name: str) -> PurePosixPath | None:
    """Return a normalized relative member path, or None for unsafe paths."""
    if not member_name or "\x00" in member_name:
        return None

    normalized_name = member_name.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    if path.parts and ":" in path.parts[0]:
        return None
    return path


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _validate_zip_members(
    members: list[zipfile.ZipInfo],
) -> list[tuple[zipfile.ZipInfo, PurePosixPath]] | None:
    if len(members) > MAX_ZIP_MEMBERS:
        return None

    validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total_size = 0
    for member in members:
        member_path = _safe_zip_member_path(member.filename)
        if member_path is None or _is_zip_symlink(member):
            return None
        if member.file_size < 0:
            return None
        total_size += member.file_size
        if total_size > MAX_ZIP_UNCOMPRESSED_SIZE:
            return None
        validated.append((member, member_path))
    return validated


def _extract_zip_members(
    zip_ref: zipfile.ZipFile,
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]],
    destination: Path,
) -> None:
    destination_root = destination.resolve()
    for member, member_path in members:
        target = (destination / Path(*member_path.parts)).resolve()
        if target != destination_root and destination_root not in target.parents:
            raise ValueError("unsafe ZIP member path")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zip_ref.open(member, "r") as source, target.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)


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
                members = _validate_zip_members(zip_ref.infolist())
                if members is None:
                    return None, 0
                _extract_zip_members(zip_ref, members, tmp_path)

            # Find HTML file in the root of the zip or nested
            html_files = list(tmp_path.rglob("*.html")) + list(tmp_path.rglob("*.htm"))
            if not html_files:
                return None, 0

            # Prefer HTML file at root or closest to root
            html_files.sort(key=lambda p: len(p.parts))
            target_html = html_files[0]

            # Use html converter on extracted HTML, but preserve zip's image directory name
            img_dir_name = get_images_dir_name(source_path)
            return convert_html(
                target_html,
                asset_dir,
                images_dir_name=img_dir_name,
                progress_callback=progress_callback,
            )

    except Exception:
        return None, 0


CONVERTERS = {
    ".zip": convert_zip,
}
