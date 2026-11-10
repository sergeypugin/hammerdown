from __future__ import annotations

import contextlib
import os
import threading

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


from .output import OutputStaging, cleanup_staged_path, replace_staged_outputs
from .path_utils import get_images_dir_name, normalize_path
from ..parsers import CONVERTERS

TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_PIPE = "│   "
TREE_SPACE = "    "
SECTION_SEPARATOR = "=" * 48


@dataclass(frozen=True)
class SourceTextConversion:
    """Result of reading a tree-mode source file as Markdown content."""

    success: bool
    markdown: str | None = None
    error: str | None = None

    def __bool__(self) -> bool:
        return self.success and self.markdown is not None


def convert_source_text(file_path: str | Path) -> SourceTextConversion:
    """Read a UTF-8 source file for tree-mode merging without parser conversion."""
    source = Path(file_path)
    try:
        if not source.is_file():
            return SourceTextConversion(False, error=f"file not found: {source}")
        data = source.read_bytes()
        if b"\x00" in data:
            return SourceTextConversion(False, error=f"binary content in source file: {source.name}")
        return SourceTextConversion(True, markdown=data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
    except (OSError, UnicodeError) as exc:
        return SourceTextConversion(False, error=f"could not read source file {source.name}: {exc}")


# Convertible binary formats that hammerdown supports
CONVERTIBLE_BINARY_FORMATS = {".pdf", ".docx", ".xlsx", ".doc", ".xls", ".pptx", ".ppt", ".odt"}

# All binary formats (convertible and non-convertible)
BINARY_FORMATS = {
    ".pdf", ".docx", ".xlsx", ".doc", ".xls", ".pptx", ".ppt", ".odt", ".epub", ".mobi",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff",
    ".mp3", ".mp4", ".wav", ".flac", ".m4a", ".aac", ".wma", ".avi", ".mov", ".mkv",
    ".exe", ".dll", ".so", ".dylib", ".app", ".apk",
    ".bin", ".dat", ".db", ".sqlite",
}


def _is_convertible_binary(file_path: str | Path) -> bool:
    """Check if a file is a binary format that hammerdown can convert."""
    extension = Path(file_path).suffix.lower()
    return extension in CONVERTIBLE_BINARY_FORMATS


def _is_binary_file(file_path: str | Path) -> bool:
    """Check if a file is a binary format (not plain text)."""
    extension = Path(file_path).suffix.lower()
    return extension in BINARY_FORMATS


def _is_supported_format(file_path: str | Path) -> bool:
    """Check if a file format is supported by hammerdown."""
    extension = Path(file_path).suffix.lower()
    return extension in CONVERTERS


def merge_root_for_inputs(raw_inputs: Sequence[str], source_files: Sequence[Path]) -> Path:
    roots: list[Path] = []
    for raw in raw_inputs:
        path = Path(normalize_path(raw)).resolve()
        roots.append(path if path.is_dir() else path.parent)
    if roots:
        try:
            return Path(os.path.commonpath([str(path) for path in roots]))
        except ValueError:
            return Path.cwd()
    if source_files:
        try:
            return Path(os.path.commonpath([str(path.resolve().parent) for path in source_files]))
        except ValueError:
            return Path.cwd()
    return Path.cwd()


def _tree_for_paths(relative_paths: Sequence[Path]) -> dict[str, dict | None]:
    root: dict[str, dict | None] = {}
    for relative in sorted(relative_paths, key=lambda path: path.as_posix().lower()):
        node = root
        parts = relative.parts
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        if parts:
            node[parts[-1]] = None
    return root


def _render_tree_children(node: dict[str, dict | None], prefix: str = "") -> list[str]:
    lines: list[str] = []
    items = sorted(node.items(), key=lambda item: item[0].lower())
    for index, (name, child) in enumerate(items):
        is_last = index == len(items) - 1
        connector = TREE_LAST if is_last else TREE_BRANCH
        if child is None:
            lines.append(f"{prefix}{connector}{name}")
        else:
            lines.append(f"{prefix}{connector}{name}/")
            lines.extend(_render_tree_children(child, prefix + (TREE_SPACE if is_last else TREE_PIPE)))
    return lines


def _render_directory_structure(root_name: str, relative_paths: Sequence[Path]) -> str:
    tree = _tree_for_paths(relative_paths)
    lines = ["Directory structure:", f"└── {root_name}/"]
    lines.extend(_render_tree_children(tree, TREE_SPACE))
    return "\n".join(lines)


def relative_path_for_source(source: str | Path, root: Path) -> Path:
    source_path = Path(source).resolve()
    try:
        return source_path.relative_to(root.resolve())
    except ValueError:
        anchor = source_path.anchor.replace(":", "").replace("\\", "").replace("/", "") or "root"
        return Path(anchor, *source_path.parts[1:])


def _relative_paths(sources: Sequence[str | Path], root: Path) -> list[Path]:
    return [relative_path_for_source(source, root) for source in sources]


@dataclass(frozen=True)
class OutputMetadata:
    """Provenance recorded in the YAML frontmatter of merge and tree outputs."""

    mode: str
    inputs: tuple[str, ...] = ()


def _yaml_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _package_version() -> str:
    # Imported lazily: the package sets __version__ after importing this module.
    from .. import __version__

    return __version__


def render_output_frontmatter(
    metadata: OutputMetadata,
    sources: Sequence[str | Path],
    merge_root: Path,
) -> str:
    from . import APP_NAME
    from .preflight import estimate_source_tokens

    lines = [
        "---",
        f"tool: {_yaml_string(APP_NAME)}",
        f"version: {_yaml_string(_package_version())}",
        f"date: {_yaml_string(datetime.now().astimezone().isoformat(timespec='seconds'))}",
        f"mode: {_yaml_string(metadata.mode)}",
        f"source: {_yaml_string(merge_root.resolve().as_posix())}",
    ]
    if metadata.inputs:
        lines.append("inputs:")
        lines.extend(f"  - {_yaml_string(str(raw_input))}" for raw_input in metadata.inputs)
    else:
        lines.append("inputs: []")
    lines.append(f"files: {len(sources)}")
    lines.append(f"tokens_estimate: {estimate_source_tokens(sources)}")
    lines.append("---")
    return "\n".join(lines)


def render_merge_header(
    sources: Sequence[str | Path],
    merge_root: Path,
    metadata: OutputMetadata | None = None,
) -> str:
    relative_paths = _relative_paths(sources, merge_root.resolve())
    structure = _render_directory_structure(merge_root.name or "root", relative_paths)
    if metadata is None:
        return structure
    return render_output_frontmatter(metadata, sources, merge_root) + "\n\n" + structure



@dataclass
class _MergeState:
    target: Path
    staging: OutputStaging
    asset_root_name: str
    target_existed: bool
    sources: tuple[str | Path, ...] = ()
    initialized: bool = False
    appended: int = 0
    had_error: bool = False
    pending_source: Path | None = None
    metadata: OutputMetadata | None = None

    @property
    def staged_target(self) -> Path:
        return self.staging.path / self.target.name

    @property
    def staged_asset_root(self) -> Path:
        return self.staging.path / self.asset_root_name

    @property
    def asset_target(self) -> Path:
        return self.target.parent / self.asset_root_name


class MergeSession:
    """Owns the staging and commit lifecycle for one batch merge."""

    def __init__(self, target: str | Path, metadata: OutputMetadata | None = None) -> None:
        resolved_target = Path(target).resolve()
        self._lock_handle, self._lock_path, self._lock_key = _acquire_target_lock(resolved_target)
        asset_root_name = f"hm_merged_into_{resolved_target.stem}_images"
        try:
            self._state = _MergeState(
                target=resolved_target,
                staging=OutputStaging.create(resolved_target.parent, prefix=".hammerdown-merge-"),
                asset_root_name=asset_root_name,
                target_existed=resolved_target.exists(),
                metadata=metadata,
            )
        except Exception:
            _release_target_lock(self._lock_handle, self._lock_path, self._lock_key)
            raise
        self._closed = False

    @property
    def target(self) -> Path:
        return self._state.target

    def finish(self) -> None:
        if self._closed:
            return
        state = self._state
        try:
            if state.sources and state.appended >= len(state.sources):
                if state.had_error and state.target_existed:
                    state.staging.cleanup()
                    return
                _commit_merge_session(state)
            else:
                state.staging.cleanup()
        finally:
            self._closed = True
            _release_target_lock(self._lock_handle, self._lock_path, self._lock_key)

    def validate_asset_directory(self, path: str | Path) -> Path:
        if self._closed:
            raise RuntimeError("merge session is already closed")
        asset_directory = Path(path).resolve()
        if self._state.staging.path not in asset_directory.parents:
            raise ValueError("merge asset directory must be inside this session's staging directory")
        return asset_directory

    def staging_asset_directory(self, source: str | Path, merge_root: Path) -> Path:
        """Return where one source's assets belong in session staging.

        Unlike merge_asset_paths this performs no append-order bookkeeping, so
        concurrent workers may compute their destinations ahead of the ordered
        append pass.
        """
        if self._closed:
            raise RuntimeError("merge session is already closed")
        state = self._state
        relative = relative_path_for_source(Path(source).resolve(), merge_root)
        return state.staging.path / Path(state.asset_root_name) / relative.parent

    def abort(self) -> None:
        if not self._closed:
            try:
                self._state.staging.cleanup()
            finally:
                self._closed = True
                _release_target_lock(self._lock_handle, self._lock_path, self._lock_key)


def _target_lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.hammerdown-merge.lock"


_PROCESS_LOCKS: dict[str, int] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _acquire_target_lock(target: Path) -> tuple[Any, Path | None, str | None]:
    """Take an advisory OS lock so two processes cannot merge into one target.

    Within a single process the lock is reference-counted so isolated sessions
    for the same target remain possible. Returns (handle, path); (None, None)
    when the path is already held by this process, and (None, None) with no
    protection only when the lock file cannot even be created.
    """
    key = str(target).lower()
    with _PROCESS_LOCKS_GUARD:
        if _PROCESS_LOCKS.get(key):
            _PROCESS_LOCKS[key] += 1
            return None, None, key
    lock_path = _target_lock_path(target)
    try:
        handle = open(lock_path, "w", encoding="utf-8")
    except OSError:
        return None, None, None
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise OSError(f"another hammerdown process is writing to {target}") from exc
    with _PROCESS_LOCKS_GUARD:
        _PROCESS_LOCKS[key] = 1
    return handle, lock_path, key


def _release_target_lock(handle: Any, lock_path: Path | None, key: str | None) -> None:
    if handle is None:
        if key is not None:
            with _PROCESS_LOCKS_GUARD:
                count = _PROCESS_LOCKS.get(key, 0)
                if count > 1:
                    _PROCESS_LOCKS[key] = count - 1
                else:
                    _PROCESS_LOCKS.pop(key, None)
        return
    if key is not None:
        with _PROCESS_LOCKS_GUARD:
            _PROCESS_LOCKS.pop(key, None)
    if lock_path is None:
        return
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass
    with contextlib.suppress(OSError):
        lock_path.unlink()


def _require_session(merge_target: Path, session: MergeSession | None) -> _MergeState:
    if session is None:
        raise ValueError("an explicit MergeSession is required for merge operations")
    state = session._state
    if session._closed:
        raise RuntimeError("merge session is already closed")
    if state.target != Path(merge_target).resolve():
        raise ValueError("merge session target does not match merge target")
    return state


def _commit_merge_session(state: _MergeState) -> None:
    try:
        replace_staged_outputs(
            [
                (state.staged_target, state.target),
                (state.staged_asset_root if state.staged_asset_root.is_dir() else None, state.asset_target),
            ]
        )
    finally:
        state.staging.cleanup()


def merge_asset_paths(
    source: str | Path,
    merge_root: Path,
    merge_target: Path,
    session: MergeSession | None = None,
) -> tuple[Path, Path]:
    state = _require_session(merge_target, session)
    source_path = Path(source).resolve()
    if state.initialized:
        expected = Path(state.sources[state.appended]).resolve() if state.appended < len(state.sources) else None
        if expected != source_path:
            raise ValueError(f"merge sources must be appended in order; expected {expected}, got {source_path}")
    if state.pending_source is not None and state.pending_source != source_path:
        raise ValueError(f"merge source {state.pending_source} has not been appended")
    state.pending_source = source_path
    relative = relative_path_for_source(source_path, merge_root)
    asset_prefix = Path(state.asset_root_name) / relative.parent
    return state.staging.path / asset_prefix, asset_prefix


def render_merged_document(
    source: str | Path,
    content: str,
    merge_root: Path,
    asset_prefix: Path | None = None,
    error: str | None = None,
    is_binary: bool = False,
) -> str:
    source_path = Path(source).resolve()
    relative = relative_path_for_source(source_path, merge_root)
    if error:
        cleaned = f"[!] File conversion failed: {error}"
    else:
        image_prefix = asset_prefix if asset_prefix is not None else relative.parent
        image_dir = get_images_dir_name(source_path)
        if image_prefix != Path("."):
            prefix = image_prefix.as_posix().rstrip("/")
            content = content.replace(f"{image_dir}/", f"{prefix}/{image_dir}/")
            content = content.replace(f"{image_dir}\\", f"{prefix}/{image_dir}/")
        cleaned = content.strip()

    section = f"{SECTION_SEPARATOR}\nFILE: {relative.as_posix()}\n{SECTION_SEPARATOR}"
    if cleaned:
        section = f"{section}\n{cleaned}"
    if is_binary:
        conversion_status = "YES" if _is_convertible_binary(source_path) else "NO"
        section = f"{section}\n[Binary file] Can be converted with hammerdown: {conversion_status}"
    return section


def render_merged_markdown(
    converted: Sequence[tuple[str, str, str | None]],
    merge_root: Path,
    binary_flags: Sequence[bool] | None = None,
) -> str:
    sources = [source for source, _, _ in converted]
    sections = [render_merge_header(sources, merge_root)]
    if binary_flags is None:
        binary_flags = [False] * len(converted)
    sections.extend(
        render_merged_document(source, content, merge_root, error=err, is_binary=is_binary)
        for (source, content, err), is_binary in zip(converted, binary_flags)
    )
    return "\n\n".join(sections) + "\n"


def initialize_merge_file(
    merge_target: Path,
    sources: Sequence[str | Path],
    merge_root: Path,
    session: MergeSession | None = None,
) -> None:
    state = _require_session(merge_target, session)
    expected_sources = tuple(sources)
    if state.initialized:
        if state.sources == expected_sources:
            return
        raise ValueError("merge session was initialized with different sources")

    state.sources = expected_sources
    state.staged_target.parent.mkdir(parents=True, exist_ok=True)
    state.staged_target.write_text(
        render_merge_header(expected_sources, merge_root, state.metadata) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    state.initialized = True


def append_merged_document(
    merge_target: Path,
    source: str | Path,
    content: str,
    merge_root: Path,
    asset_prefix: Path,
    error: str | None = None,
    is_binary: bool = False,
    session: MergeSession | None = None,
) -> None:
    state = _require_session(merge_target, session)
    source_path = Path(source).resolve()
    if not state.initialized:
        initialize_merge_file(merge_target, [source], merge_root, session)
    expected = Path(state.sources[state.appended]).resolve() if state.appended < len(state.sources) else None
    if expected != source_path:
        raise ValueError(f"merge sources must be appended in order; expected {expected}, got {source_path}")
    if state.pending_source is not None and state.pending_source != source_path:
        raise ValueError(f"merge source {state.pending_source} has not been appended")

    if error:
        state.had_error = True
    try:
        rendered = render_merged_document(
            source,
            content,
            merge_root,
            asset_prefix,
            error=error,
            is_binary=is_binary,
        )
        with state.staged_target.open("a", encoding="utf-8", newline="\n") as output:
            output.write("\n" + rendered + "\n")
    except Exception:
        state.had_error = True
        cleanup_staged_path(state.staging.path / asset_prefix)
        state.pending_source = None
        state.appended += 1
        raise

    state.pending_source = None
    state.appended += 1
