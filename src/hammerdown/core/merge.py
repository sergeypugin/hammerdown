from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import weakref

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


def render_merge_header(sources: Sequence[str | Path], merge_root: Path) -> str:
    relative_paths = _relative_paths(sources, merge_root.resolve())
    return _render_directory_structure(merge_root.name or "root", relative_paths)


_PathBase = type(Path())


@dataclass
class _MergeSession:
    target: Path
    staging: OutputStaging
    asset_root_name: str
    target_existed: bool
    sources: tuple[str | Path, ...] = ()
    initialized: bool = False
    appended: int = 0
    had_error: bool = False
    pending_source: Path | None = None
    active_handle_ref: weakref.ReferenceType[_MergeAssetPath] | None = None
    active_token: object | None = None

    @property
    def staged_target(self) -> Path:
        return self.staging.path / self.target.name

    @property
    def staged_asset_root(self) -> Path:
        return self.staging.path / self.asset_root_name

    @property
    def asset_target(self) -> Path:
        return self.target.parent / self.asset_root_name


_MERGE_SESSIONS: dict[Path, _MergeSession] = {}


class _MergeAssetPath(_PathBase):
    """A staged asset path that can abandon its merge session."""

    __slots__ = (
        "_session_ref",
        "_source",
        "_finalizer",
        "_consumed",
        "_lease_token",
        "__weakref__",
    )

    def __new__(
        cls,
        *pathsegments: str | os.PathLike[str],
        session: _MergeSession | None = None,
        source: str | os.PathLike[str] | None = None,
    ) -> _MergeAssetPath:
        # pathlib constructs derived paths by calling the concrete path type
        # with ordinary path segments.  The lease is only attached when the
        # explicit session and source keywords are supplied.
        asset_path = super().__new__(cls, *pathsegments)
        if session is None:
            asset_path._session_ref = None
            asset_path._source = None
            asset_path._finalizer = None
            asset_path._consumed = True
            asset_path._lease_token = None
        else:
            if source is None:
                raise TypeError("source is required for a merge asset path")
            asset_path._session_ref = weakref.ref(session)
            asset_path._source = Path(source).resolve()
            asset_path._consumed = False
            asset_path._lease_token = object()
            session.active_token = asset_path._lease_token
            asset_path._finalizer = weakref.finalize(
                asset_path,
                _abandon_merge_session,
                weakref.ref(session),
                asset_path._lease_token,
            )
        return asset_path

    def __init__(
        self,
        *pathsegments: str | os.PathLike[str],
        session: _MergeSession | None = None,
        source: str | os.PathLike[str] | None = None,
    ) -> None:
        # pathlib needs its own internal path cache initialized as well.
        super().__init__(*pathsegments)

    def with_segments(self, *pathsegments: str | os.PathLike[str]) -> Path:
        """Return ordinary paths for pathlib-derived values, not merge leases."""
        return Path(*pathsegments)

    @property
    def _merge_handle(self) -> _MergeAssetPath | None:
        return self if self._session_ref is not None else None

    def _session(self) -> _MergeSession | None:
        return self._session_ref() if self._session_ref is not None else None

    def _detach_finalizer(self) -> None:
        if self._finalizer is not None:
            self._finalizer.detach()

    def abandon_if_idle(self) -> None:
        if self._consumed:
            return
        session = self._session()
        self._detach_finalizer()
        self._consumed = True
        if session is not None and session.active_token is self._lease_token:
            _abandon_active_lease(session, self._lease_token)

    def consume(self) -> None:
        if self._consumed:
            return
        session = self._session()
        self._detach_finalizer()
        self._consumed = True
        if session is None or _MERGE_SESSIONS.get(session.target) is not session:
            return
        if session.active_handle_ref is not None and session.active_handle_ref() is self:
            session.active_handle_ref = None
        if session.active_token is self._lease_token:
            session.active_token = None
        if session.pending_source == self._source:
            session.pending_source = None


def _abandon_merge_session(
    session_ref: weakref.ReferenceType[_MergeSession],
    token: object,
) -> None:
    try:
        session = session_ref()
        if session is not None and session.active_token is token:
            _abandon_active_lease(session, token)
    except Exception:
        # Finalizers can run during interpreter shutdown.
        pass


def _merge_session(merge_target: Path) -> _MergeSession:
    target = merge_target.resolve()
    session = _MERGE_SESSIONS.get(target)
    if session is not None:
        return session

    asset_root_name = f"hm_merged_into_{target.stem}_images"
    staging = OutputStaging.create(target.parent, prefix=".hammerdown-merge-")
    session = _MergeSession(
        target=target,
        staging=staging,
        asset_root_name=asset_root_name,
        target_existed=target.exists(),
    )
    _MERGE_SESSIONS[target] = session
    return session


def _discard_merge_session(session: _MergeSession) -> None:
    if _MERGE_SESSIONS.get(session.target) is session:
        _MERGE_SESSIONS.pop(session.target, None)
        session.active_handle_ref = None
        session.active_token = None
        session.pending_source = None
    session.staging.cleanup()


def _abandon_active_lease(session: _MergeSession, token: object) -> None:
    if session.active_token is not token:
        return
    if not session.initialized or session.appended == 0:
        _discard_merge_session(session)
        return

    # The batch owns an initialized session until all expected sources append.
    # A converter wrapper may drop the lease before the batch can append it.
    session.active_handle_ref = None
    session.active_token = None
    session.pending_source = None


def _commit_merge_session(session: _MergeSession) -> None:
    try:
        replace_staged_outputs(
            [
                (session.staged_target, session.target),
                (
                    session.staged_asset_root if session.staged_asset_root.is_dir() else None,
                    session.asset_target,
                ),
            ]
        )
    finally:
        _discard_merge_session(session)


def _finish_merge_session(session: _MergeSession) -> None:
    if not session.sources or session.appended < len(session.sources):
        return

    if session.had_error and session.target_existed:
        _discard_merge_session(session)
        return

    _commit_merge_session(session)


def merge_asset_paths(
    source: str | Path,
    merge_root: Path,
    merge_target: Path,
) -> tuple[Path, Path]:
    session = _merge_session(merge_target)
    try:
        source_path = Path(source).resolve()
        active_handle = session.active_handle_ref() if session.active_handle_ref is not None else None

        if session.pending_source is not None:
            if session.pending_source != source_path or active_handle is None:
                _discard_merge_session(session)
                session = _merge_session(merge_target)
                active_handle = None
        elif session.initialized:
            expected = (
                Path(session.sources[session.appended]).resolve()
                if session.appended < len(session.sources)
                else None
            )
            if expected != source_path:
                _discard_merge_session(session)
                session = _merge_session(merge_target)
                active_handle = None

        relative = relative_path_for_source(source_path, merge_root)
        asset_prefix = Path(session.asset_root_name) / relative.parent
        if active_handle is None:
            session.pending_source = source_path
            active_handle = _MergeAssetPath(
                session.staging.path / asset_prefix,
                session=session,
                source=source_path,
            )
            session.active_handle_ref = weakref.ref(active_handle)
        return active_handle, asset_prefix
    except Exception:
        _discard_merge_session(session)
        raise


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


def initialize_merge_file(merge_target: Path, sources: Sequence[str | Path], merge_root: Path) -> None:
    session = _merge_session(merge_target)
    expected_sources = tuple(sources)
    if session.initialized:
        if session.sources == expected_sources:
            return
        _discard_merge_session(session)
        session = _merge_session(merge_target)

    try:
        session.sources = expected_sources
        session.staged_target.parent.mkdir(parents=True, exist_ok=True)
        session.staged_target.write_text(
            render_merge_header(expected_sources, merge_root) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        session.initialized = True
    except Exception:
        _discard_merge_session(session)
        raise


def append_merged_document(
    merge_target: Path,
    source: str | Path,
    content: str,
    merge_root: Path,
    asset_prefix: Path,
    error: str | None = None,
    is_binary: bool = False,
) -> None:
    session = _merge_session(merge_target)
    try:
        if not session.initialized:
            initialize_merge_file(merge_target, [source], merge_root)

        if error:
            session.had_error = True
        rendered = render_merged_document(
            source,
            content,
            merge_root,
            asset_prefix,
            error=error,
            is_binary=is_binary,
        )
        with session.staged_target.open("a", encoding="utf-8", newline="\n") as output:
            output.write("\n" + rendered + "\n")
    except Exception:
        session.had_error = True
        cleanup_staged_path(session.staging.path / asset_prefix)
        active_handle = session.active_handle_ref() if session.active_handle_ref is not None else None
        if active_handle is not None:
            active_handle.consume()
        session.active_handle_ref = None
        session.active_token = None
        session.pending_source = None
        session.appended += 1
        _finish_merge_session(session)
        raise

    active_handle = session.active_handle_ref() if session.active_handle_ref is not None else None
    if active_handle is not None:
        active_handle.consume()
    session.pending_source = None
    session.appended += 1
    _finish_merge_session(session)
