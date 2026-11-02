from __future__ import annotations

import codecs
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Pattern, Sequence

from pathspec import PathSpec

from . import SUPPORTED_EXTENSIONS, get_output_path, is_generated_output
from .ignore import IgnoreFile, ignore_files_for, ignore_scope_for, is_ignored, read_ignore_file
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

# Text-like formats useful in tree mode, whether or not Hammerdown converts them.
TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt", ".md", ".rst", ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs",
        ".ts", ".tsx", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".xml",
        ".html", ".htm", ".css", ".scss", ".less", ".java", ".kt", ".kts",
        ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".rs", ".go", ".rb",
        ".php", ".sh", ".bash", ".zsh", ".sql", ".csv", ".tsv", ".log",
        ".ini", ".cfg", ".conf", ".properties", ".gradle", ".dockerfile",
        ".makefile", ".graphql", ".proto", ".swift", ".scala", ".vue", ".svelte",
    }
)
TEXT_CONVERTIBLE_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".csv", ".html", ".htm"})
TEXT_FILE_NAMES: frozenset[str] = frozenset(
    {"dockerfile", "makefile", "gnumakefile", "justfile", "license", "readme", "changelog", "gemfile", "rakefile", "procfile"}
)

FilterPattern = Pattern[str] | PathSpec
FilterPatternInput = FilterPattern | Sequence[FilterPattern]


@dataclass(frozen=True)
class DiscoveredTarget:
    path: str
    category: str | None = None


@dataclass(frozen=True)
class DiscoverySkip:
    path: str
    reason: str


@dataclass
class DiscoveryResult:
    targets: list[DiscoveredTarget] = field(default_factory=list)
    skipped: list[DiscoverySkip] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    ignore_files: list[str] = field(default_factory=list)
    generated_outputs: list[str] = field(default_factory=list)
    _legacy_items: list[tuple[str, str | None]] = field(default_factory=list, repr=False)


def _is_ignored_directory(name: str) -> bool:
    return name.startswith(".") or name.lower() in IGNORED_DIRECTORY_NAMES


def _is_ignored_file(name: str) -> bool:
    return name.startswith("~$") or name.startswith(".")


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _iter_filter_patterns(patterns: FilterPatternInput) -> Generator[FilterPattern, None, None]:
    if isinstance(patterns, (re.Pattern, PathSpec)):
        yield patterns
        return
    yield from patterns


def _has_filter_patterns(patterns: FilterPatternInput) -> bool:
    if isinstance(patterns, re.Pattern):
        return True
    if isinstance(patterns, PathSpec):
        return bool(patterns.patterns)
    return any(_has_filter_patterns(pattern) for pattern in patterns)


def _matches_pattern(pattern: FilterPattern, relative: str) -> bool:
    if isinstance(pattern, re.Pattern):
        return pattern.search(relative) is not None
    return pattern.match_file(relative)


def _passes_cli_filters(
    path: Path,
    root: Path,
    include_patterns: FilterPatternInput,
    exclude_patterns: FilterPatternInput,
) -> tuple[bool, str | None]:
    relative = _relative_path(path, root).replace("\\", "/")
    while relative.startswith("./"):
        relative = relative[2:]
    if any(_matches_pattern(pattern, relative) for pattern in _iter_filter_patterns(exclude_patterns)):
        return False, "cli exclude filter"
    if _has_filter_patterns(include_patterns) and not any(
        _matches_pattern(pattern, relative) for pattern in _iter_filter_patterns(include_patterns)
    ):
        return False, "cli include filter"
    return True, None


def _is_text_file(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            sample = stream.read(8192)
            if b"\x00" in sample:
                return False

            decoder = codecs.getincrementaldecoder("utf-8")()
            decoder.decode(sample, final=False)
            pending, _ = decoder.getstate()
            while pending:
                continuation = stream.read(1)
                if not continuation:
                    decoder.decode(b"", final=True)
                    break
                if b"\x00" in continuation:
                    return False
                decoder.decode(continuation, final=False)
                pending, _ = decoder.getstate()
            decoder.decode(b"", final=True)
        return True
    except (OSError, UnicodeError):
        return False


def _tree_category(path: Path, all_formats: bool) -> str | None:
    extension = path.suffix.lower()
    supported = extension in SUPPORTED_EXTENSIONS
    if extension in TEXT_CONVERTIBLE_EXTENSIONS and supported:
        return "text_convertible" if _is_text_file(path) else None
    if extension in TEXT_FILE_EXTENSIONS or path.name.lower() in TEXT_FILE_NAMES:
        return "source_code" if _is_text_file(path) else None
    if all_formats and supported:
        return "binary_document"
    return None


def discover_paths(
    paths: Sequence[str],
    excluded_dir: Path | None = None,
    include_patterns: FilterPatternInput = (),
    exclude_patterns: FilterPatternInput = (),
    include_gitignored: bool = False,
    excluded_file: Path | None = None,
) -> DiscoveryResult:
    """Discover Hammerdown-convertible files with structured skip and error details."""
    return _discover(
        paths,
        tree_mode=False,
        all_formats=False,
        excluded_dir=excluded_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        include_gitignored=include_gitignored,
        excluded_file=excluded_file,
    )


def discover_tree(
    paths: Sequence[str],
    all_formats: bool = False,
    excluded_dir: Path | None = None,
    include_patterns: FilterPatternInput = (),
    exclude_patterns: FilterPatternInput = (),
    include_gitignored: bool = False,
    excluded_file: Path | None = None,
) -> DiscoveryResult:
    """Discover tree-mode files, distinguishing convertibles from source text."""
    return _discover(
        paths,
        tree_mode=True,
        all_formats=all_formats,
        excluded_dir=excluded_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        include_gitignored=include_gitignored,
        excluded_file=excluded_file,
    )


def _discover(
    paths: Sequence[str],
    tree_mode: bool,
    all_formats: bool,
    excluded_dir: Path | None,
    include_patterns: FilterPatternInput,
    exclude_patterns: FilterPatternInput,
    include_gitignored: bool,
    excluded_file: Path | None,
) -> DiscoveryResult:
    result = DiscoveryResult()
    seen_targets: set[Path] = set()
    seen_generated_outputs: set[Path] = set()
    seen_skips: set[tuple[Path, str]] = set()
    ignore_cache: dict[Path, IgnoreFile | None] = {}
    ignore_paths: set[Path] = set()
    excluded_dir = excluded_dir.resolve() if excluded_dir is not None else None
    excluded_file = excluded_file.resolve() if excluded_file is not None else None

    resolved_inputs: list[tuple[str, Path | None, str | None]] = []
    for raw in paths:
        raw_path = str(raw)
        try:
            candidate = Path(normalize_path(raw)).resolve()
        except Exception:
            resolved_inputs.append((raw_path, None, "invalid path"))
            continue
        if not candidate.exists():
            resolved_inputs.append((raw_path, None, "file or directory not found"))
            continue
        resolved_inputs.append((raw_path, candidate, None))

    filter_roots = sorted(
        {
            candidate if candidate.is_dir() else candidate.parent
            for _, candidate, error in resolved_inputs
            if candidate is not None and error is None
        },
        key=lambda root: (len(root.parts), root.as_posix()),
    )

    def filter_context_for(path: Path, fallback: Path) -> Path:
        for root in filter_roots:
            if path.is_relative_to(root):
                return root
        return fallback

    def add_skip(path: Path, reason: str) -> None:
        identity = (path.resolve(), reason)
        if identity not in seen_skips:
            seen_skips.add(identity)
            result.skipped.append(DiscoverySkip(str(path.resolve()), reason))

    def add_error(path: str, reason: str) -> None:
        result.errors.append((path, reason))
        result._legacy_items.append((path, reason))

    def clear_skips(path: Path) -> None:
        result.skipped[:] = [skip for skip in result.skipped if Path(skip.path) != path]
        seen_skips.difference_update({identity for identity in seen_skips if identity[0] == path})

    def rules_for(path: Path, scope: Path) -> list[IgnoreFile]:
        rules: list[IgnoreFile] = []
        for ignore_path in ignore_files_for(path, scope):
            resolved = ignore_path.resolve()
            ignore_paths.add(resolved)
            if resolved not in ignore_cache:
                try:
                    ignore_cache[resolved] = read_ignore_file(resolved)
                except (OSError, UnicodeError, ValueError):
                    ignore_cache[resolved] = None
                    add_error(str(resolved), "could not read ignore file")
            rule_file = ignore_cache[resolved]
            if rule_file is not None:
                rules.append(rule_file)
        return rules

    def handle_file(file_path: Path, filter_root: Path, scope: Path, explicitly_selected: bool) -> None:
        try:
            canonical = file_path.resolve()
        except OSError:
            add_error(str(file_path), "could not resolve path")
            return

        if is_generated_output(canonical):
            if canonical not in seen_generated_outputs:
                seen_generated_outputs.add(canonical)
                result.generated_outputs.append(str(canonical))
            return

        if not explicitly_selected and excluded_file is not None and canonical == excluded_file:
            return

        rules = rules_for(canonical, scope)
        if not include_gitignored and is_ignored(canonical, rules):
            return
        if _is_ignored_file(canonical.name):
            add_skip(canonical, "safety filter")
            return
        if canonical in seen_targets:
            return

        filter_context = filter_context_for(file_path, filter_root)
        allowed, reason = _passes_cli_filters(canonical, filter_context, include_patterns, exclude_patterns)
        if not allowed:
            add_skip(canonical, reason or "cli filter")
            return

        category: str | None = None
        if tree_mode:
            category = _tree_category(canonical, all_formats)
            if category is None:
                add_skip(canonical, "unsupported format")
                return
        elif canonical.suffix.lower() not in SUPPORTED_EXTENSIONS:
            add_skip(canonical, "unsupported format")
            if explicitly_selected:
                result._legacy_items.append((str(canonical), "unsupported format"))
            return

        seen_targets.add(canonical)
        clear_skips(canonical)
        target = DiscoveredTarget(str(canonical), category)
        result.targets.append(target)
        result._legacy_items.append((target.path, None))

    for raw, candidate, error in resolved_inputs:
        if candidate is None:
            add_error(raw, error or "invalid path")
            continue

        filter_root = candidate if candidate.is_dir() else candidate.parent
        scope = ignore_scope_for(filter_root)
        if candidate.is_file():
            handle_file(candidate, filter_root, scope, explicitly_selected=True)
            continue

        for root, dirnames, filenames in os.walk(candidate):
            root_path = Path(root).resolve()
            rules_for(root_path / "__hammerdown_discovery_placeholder__", scope)
            kept_directories: list[str] = []
            for name in sorted(dirnames):
                directory = (root_path / name).resolve()
                directory_rules = rules_for(directory, scope)
                if not include_gitignored and is_ignored(directory, directory_rules, is_directory=True):
                    continue
                if _is_ignored_directory(name):
                    add_skip(directory, "safety filter")
                    continue
                if excluded_dir is not None and directory.is_relative_to(excluded_dir):
                    add_skip(directory, "safety filter")
                    continue
                kept_directories.append(name)
            dirnames[:] = kept_directories

            for name in sorted(filenames):
                file_path = root_path / name
                handle_file(file_path, candidate, scope, explicitly_selected=False)

    result.ignore_files = [str(path) for path in sorted(ignore_paths)]
    return result


def expand_paths(
    paths: Sequence[str],
    excluded_dir: Path | None = None,
    include_patterns: FilterPatternInput = (),
    exclude_patterns: FilterPatternInput = (),
    include_gitignored: bool = False,
) -> list[tuple[str, str | None]]:
    """Compatibility adapter returning ordered ``(path, error)`` pairs."""
    result = discover_paths(
        paths,
        excluded_dir=excluded_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        include_gitignored=include_gitignored,
    )
    return result._legacy_items


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
        relative = source.relative_to(max(matching_roots, key=lambda root: len(root.parts))) if matching_roots else Path(source.name)
        paths.append(get_output_path(source, output_root / relative.parent))

    collisions: dict[Path, list[Path]] = {}
    for (source, error), output in zip(targets, paths):
        if error is None:
            collisions.setdefault(output, []).append(Path(source))
    duplicates = {output: sources for output, sources in collisions.items() if len(sources) > 1}
    if duplicates:
        details = "; ".join(f"{output}: {', '.join(str(source) for source in sources)}" for output, sources in duplicates.items())
        raise ValueError(f"output filename collision: {details}")
    return paths


def discover_all_files_for_tree(
    paths: Sequence[str],
    include_binary: bool = False,
    excluded_dir: Path | None = None,
    include_patterns: FilterPatternInput = (),
    exclude_patterns: FilterPatternInput = (),
    include_gitignored: bool = False,
) -> Generator[tuple[str, str], None, None]:
    """Compatibility adapter yielding tree targets as ``(path, category)``."""
    result = discover_tree(
        paths,
        all_formats=include_binary,
        excluded_dir=excluded_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        include_gitignored=include_gitignored,
    )
    for target in result.targets:
        yield target.path, target.category or "text_convertible"
