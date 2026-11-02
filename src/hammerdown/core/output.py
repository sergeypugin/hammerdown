from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import tempfile
import uuid


_ACTIVE_STAGING_PATHS: set[Path] = set()


class OutputStaging:
    def __init__(self, temporary_directory: tempfile.TemporaryDirectory[str]) -> None:
        self._temporary_directory = temporary_directory
        self.path = Path(temporary_directory.name).resolve()
        _ACTIVE_STAGING_PATHS.add(self.path)

    @classmethod
    def create(cls, parent: Path, prefix: str) -> OutputStaging:
        parent.mkdir(parents=True, exist_ok=True)
        temporary_directory = tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent))
        return cls(temporary_directory)

    def cleanup(self) -> None:
        _ACTIVE_STAGING_PATHS.discard(self.path)
        self._temporary_directory.cleanup()


def is_within_staging(path: Path) -> bool:
    resolved = path.resolve()
    return any(root == resolved or root in resolved.parents for root in _ACTIVE_STAGING_PATHS)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if not _path_exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def cleanup_staged_path(path: Path) -> None:
    if is_within_staging(path):
        _remove_path(path)


def _backup_path(target: Path) -> Path:
    while True:
        candidate = target.parent / f".{target.name}.hammerdown-backup-{uuid.uuid4().hex}"
        if not _path_exists(candidate):
            return candidate


def replace_staged_outputs(replacements: Sequence[tuple[Path | None, Path]]) -> None:
    """Replace related output paths and restore their backups if installation fails."""
    if not replacements:
        return

    targets = [target for _, target in replacements]
    if len(set(targets)) != len(targets):
        raise ValueError("output replacement targets must be unique")

    for staged, target in replacements:
        if staged is not None and target.suffix.lower() == ".md" and target.is_dir():
            raise IsADirectoryError(target)

    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for staged, target in replacements:
            target.parent.mkdir(parents=True, exist_ok=True)
            if _path_exists(target):
                backup = _backup_path(target)
                os.replace(target, backup)
                backups.append((target, backup))

        for staged, target in replacements:
            if staged is None:
                continue
            if not _path_exists(staged):
                raise FileNotFoundError(staged)
            os.replace(staged, target)
            installed.append(target)
    except Exception:
        for target in reversed(installed):
            try:
                _remove_path(target)
            except OSError:
                pass
        for target, backup in reversed(backups):
            if not _path_exists(backup):
                continue
            try:
                if _path_exists(target):
                    _remove_path(target)
                os.replace(backup, target)
            except OSError:
                pass
        raise
    else:
        for _, backup in backups:
            try:
                _remove_path(backup)
            except OSError:
                pass
