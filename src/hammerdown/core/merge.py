from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .path_utils import get_images_dir_name, normalize_path
from ..parsers import CONVERTERS

TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_PIPE = "│   "
TREE_SPACE = "    "
SECTION_SEPARATOR = "=" * 48

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


def merge_asset_paths(source: str | Path, merge_root: Path, merge_target: Path) -> tuple[Path, Path]:
    relative = relative_path_for_source(source, merge_root)
    asset_root_name = f"hm_merged_into_{merge_target.stem}_images"
    asset_prefix = Path(asset_root_name) / relative.parent
    return merge_target.parent / asset_prefix, asset_prefix


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
    merge_target.parent.mkdir(parents=True, exist_ok=True)
    merge_target.write_text(render_merge_header(sources, merge_root) + "\n", encoding="utf-8", newline="\n")


def append_merged_document(
    merge_target: Path,
    source: str | Path,
    content: str,
    merge_root: Path,
    asset_prefix: Path,
    error: str | None = None,
    is_binary: bool = False,
) -> None:
    with merge_target.open("a", encoding="utf-8", newline="\n") as output:
        output.write("\n" + render_merged_document(source, content, merge_root, asset_prefix, error=error, is_binary=is_binary) + "\n")
