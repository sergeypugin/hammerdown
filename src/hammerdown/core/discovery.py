from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Generator, Sequence

from . import SUPPORTED_EXTENSIONS
from .path_utils import normalize_path

# Directories that never contain user documents worth converting and that can
# hold a huge number of files (dependency trees, caches, system trash).
IGNORED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        "env",
        "$recycle.bin",
        "system volume information",
    }
)

# Binary document formats for tree mode with --all-formats
BINARY_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".doc", ".xlsx", ".xls",
    ".pptx", ".ppt", ".odt", ".epub", ".mobi",
})

# Text file extensions (source code)
TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".json",
    ".yaml", ".yml", ".xml", ".html", ".css", ".java",
    ".cpp", ".c", ".h", ".rs", ".go", ".rb", ".php",
    ".sh", ".bash", ".sql", ".csv",
})


def _is_ignored_directory(name: str) -> bool:
    return name.startswith(".") or name.lower() in IGNORED_DIRECTORY_NAMES


def _is_ignored_file(name: str) -> bool:
    return (
        name.startswith("~$")
        or name.startswith(".")
        or (name.startswith("hm_") and name.lower().endswith(".md"))
    )


def expand_paths(
    paths: Sequence[str],
    excluded_dir: Path | None = None,
    include_patterns: Sequence[re.Pattern[str]] = (),
    exclude_patterns: Sequence[re.Pattern[str]] = (),
) -> list[tuple[str, str | None]]:
    """Resolve CLI inputs into ordered ``(path, error)`` targets."""
    targets: list[tuple[str, str | None]] = []
    seen_paths: set[Path] = set()
    excluded_dir = excluded_dir.resolve() if excluded_dir is not None else None

    def matches(path: Path, root: Path | None) -> bool:
        if root is not None:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
        else:
            relative = path.name
        if include_patterns and not any(pattern.search(relative) for pattern in include_patterns):
            return False
        return not any(pattern.search(relative) for pattern in exclude_patterns)

    for raw in paths:
        try:
            candidate = Path(normalize_path(raw)).resolve()
        except Exception:
            targets.append((str(raw), "invalid path"))
            continue

        if not candidate.exists():
            targets.append((str(raw), "file or directory not found"))
            continue

        if candidate.is_dir():
            for root, dirnames, filenames in os.walk(candidate):
                pruned: list[str] = []
                for name in dirnames:
                    if _is_ignored_directory(name):
                        continue
                    if excluded_dir is not None and (Path(root) / name).resolve().is_relative_to(excluded_dir):
                        continue
                    pruned.append(name)
                dirnames[:] = pruned
                for name in sorted(filenames):
                    if _is_ignored_file(name):
                        continue
                    try:
                        file_path = (Path(root) / name).resolve()
                        if (
                            file_path.suffix.lower() in SUPPORTED_EXTENSIONS
                            and file_path not in seen_paths
                            and matches(file_path, candidate)
                        ):
                            seen_paths.add(file_path)
                            targets.append((str(file_path), None))
                    except OSError:
                        continue
        elif candidate.is_file():
            if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                targets.append((str(candidate), "unsupported format"))
            elif candidate not in seen_paths and matches(candidate, None):
                seen_paths.add(candidate)
                targets.append((str(candidate), None))

    return targets


def output_paths(
    raw_files: Sequence[str],
    targets: Sequence[tuple[str, str | None]],
    output_root: Path,
) -> list[Path]:
    """Compute output Markdown paths under ``output_root`` preserving layout."""
    roots: list[Path] = []
    for raw in raw_files:
        try:
            path = Path(normalize_path(raw)).resolve()
        except (OSError, ValueError):
            continue
        if path.is_dir():
            roots.append(path)

    paths: list[Path] = []
    for path, _ in targets:
        source = Path(path).resolve()
        matching_roots = [root for root in roots if source.is_relative_to(root)]
        if matching_roots:
            relative = source.relative_to(max(matching_roots, key=lambda root: len(root.parts)))
        else:
            relative = Path(source.name)
        ext_clean = source.suffix.lower().lstrip(".")
        output_name = f"hm_{source.stem}_{ext_clean}.md" if ext_clean else f"hm_{source.stem}.md"
        paths.append(output_root / relative.parent / output_name)

    collisions: dict[Path, list[Path]] = {}
    for (source, error), output in zip(targets, paths):
        if error is None:
            collisions.setdefault(output, []).append(Path(source))
    duplicates = {output: sources for output, sources in collisions.items() if len(sources) > 1}
    if duplicates:
        details = "; ".join(
            f"{output}: {', '.join(str(source) for source in sources)}"
            for output, sources in duplicates.items()
        )
        raise ValueError(f"output filename collision: {details}")
    return paths


def discover_all_files_for_tree(
    paths: Sequence[str],
    include_binary: bool = False,
    excluded_dir: Path | None = None,
    include_patterns: Sequence[re.Pattern[str]] = (),
    exclude_patterns: Sequence[re.Pattern[str]] = (),
) -> Generator[tuple[str, str], None, None]:
    """Discover all files for tree mode with category classification.

    Yields (file_path, category) tuples where category is one of:
    - "text_convertible": supported formats for conversion
    - "source_code": all text files (source code)
    - "binary_document": binary documents (pdf, docx, etc.)
    - "skip": binary non-convertible files (only when include_binary=False)
    """
    seen_paths: set[Path] = set()
    excluded_dir = excluded_dir.resolve() if excluded_dir is not None else None

    def matches(path: Path, root: Path | None) -> bool:
        if root is not None:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
        else:
            relative = path.name
        if include_patterns and not any(pattern.search(relative) for pattern in include_patterns):
            return False
        return not any(pattern.search(relative) for pattern in exclude_patterns)

    for raw in paths:
        try:
            candidate = Path(normalize_path(raw)).resolve()
        except Exception:
            continue

        if not candidate.exists():
            continue

        if candidate.is_dir():
            for root, dirnames, filenames in os.walk(candidate):
                pruned: list[str] = []
                for name in dirnames:
                    if _is_ignored_directory(name):
                        continue
                    if excluded_dir is not None and (Path(root) / name).resolve().is_relative_to(excluded_dir):
                        continue
                    pruned.append(name)
                dirnames[:] = pruned
                for name in sorted(filenames):
                    if _is_ignored_file(name):
                        continue
                    try:
                        file_path = (Path(root) / name).resolve()
                        if file_path in seen_paths or not matches(file_path, candidate):
                            continue
                        seen_paths.add(file_path)

                        ext = file_path.suffix.lower()

                        if ext in SUPPORTED_EXTENSIONS:
                            yield (str(file_path), "text_convertible")
                        elif ext in TEXT_FILE_EXTENSIONS:
                            yield (str(file_path), "source_code")
                        elif ext in BINARY_DOCUMENT_EXTENSIONS:
                            if include_binary:
                                yield (str(file_path), "binary_document")
                            else:
                                yield (str(file_path), "skip")
                    except OSError:
                        continue
        elif candidate.is_file():
            if candidate not in seen_paths and matches(candidate, None):
                seen_paths.add(candidate)
                ext = candidate.suffix.lower()

                if ext in SUPPORTED_EXTENSIONS:
                    yield (str(candidate), "text_convertible")
                elif ext in TEXT_FILE_EXTENSIONS:
                    yield (str(candidate), "source_code")
                elif ext in BINARY_DOCUMENT_EXTENSIONS:
                    if include_binary:
                        yield (str(candidate), "binary_document")
                    else:
                        yield (str(candidate), "skip")
