from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pathspec import GitIgnoreSpec

IGNORE_FILENAMES = (".gitignore", ".gitingestignore")


@dataclass(frozen=True)
class IgnoreFile:
    path: Path
    directory: Path
    spec: GitIgnoreSpec


def git_root_for(path: Path) -> Path | None:
    """Find the nearest ancestor containing a Git metadata entry."""
    current = path if path.is_dir() else path.parent
    for directory in (current, *current.parents):
        git_metadata = directory / ".git"
        if git_metadata.is_dir() or git_metadata.is_file():
            return directory
    return None


def ignore_scope_for(selected_root: Path) -> Path:
    """Use Git root when present, otherwise stop at the selected resource root."""
    return git_root_for(selected_root) or selected_root


def ignore_files_for(path: Path, scope_root: Path) -> Iterable[Path]:
    """Yield existing ignore files from the scope root through path's parent."""
    try:
        relative_parent = path.parent.relative_to(scope_root)
    except ValueError:
        relative_parent = Path()

    directories = [scope_root]
    current = scope_root
    for part in relative_parent.parts:
        current = current / part
        directories.append(current)

    for directory in directories:
        for name in IGNORE_FILENAMES:
            ignore_path = directory / name
            if ignore_path.is_file():
                yield ignore_path


def read_ignore_file(path: Path) -> IgnoreFile:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return IgnoreFile(path=path.resolve(), directory=path.parent.resolve(), spec=GitIgnoreSpec.from_lines(lines))


def is_ignored(path: Path, rules: Iterable[IgnoreFile], is_directory: bool = False) -> bool:
    """Apply ignore files from outermost to innermost; the last matching rule wins."""
    ignored = False
    for rule_file in rules:
        try:
            relative = path.relative_to(rule_file.directory).as_posix()
        except ValueError:
            continue
        if is_directory:
            relative += "/"
        result = rule_file.spec.check_file(relative)
        if result.include is not None:
            ignored = result.include
    return ignored
