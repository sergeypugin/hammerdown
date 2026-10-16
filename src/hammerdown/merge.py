from __future__ import annotations

from pathlib import Path
import os
from typing import Sequence

from hammerdown.path_utils import normalize_path

TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_PIPE = "│   "
TREE_SPACE = "    "
SECTION_SEPARATOR = "=" * 48


def merge_root_for_inputs(raw_inputs: Sequence[str], source_files: Sequence[Path]) -> Path:
    roots: list[Path] = []
    for raw in raw_inputs:
        path = Path(normalize_path(raw)).resolve()
        roots.append(path if path.is_dir() else path.parent)
    if roots:
        common = Path(os.path.commonpath([str(path) for path in roots]))
        if common.is_file():
            return common.parent
        return common
    if source_files:
        return Path(os.path.commonpath([str(path.resolve().parent) for path in source_files]))
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


def merge_converted_files(
    files: Sequence[str],
    results: Sequence[bool],
    merge_target: str,
    overwrite_sources: bool = False,
    output_paths: Sequence[Path] | None = None,
    skip_existing: bool = False,
    merge_root: Path | None = None,
) -> bool:
    successful: list[tuple[Path, Path]] = []
    for index, (file_path, succeeded) in enumerate(zip(files, results)):
        if not succeeded:
            continue
        source = Path(file_path).resolve()
        stem = source.stem
        ext_clean = source.suffix.lower().lstrip(".")
        out_md_name = f"hm_{stem}_{ext_clean}.md" if ext_clean else f"hm_{stem}.md"
        out_md = output_paths[index] if output_paths is not None else source.parent / out_md_name
        if overwrite_sources and source.suffix.lower() in {".txt", ".md"}:
            out_md = source
        if out_md.is_file():
            successful.append((source, out_md))

    if not successful:
        return False

    dest = Path(normalize_path(merge_target))
    if skip_existing and dest.exists():
        return True

    root = merge_root.resolve() if merge_root is not None else merge_root_for_inputs([], [source for source, _ in successful])
    relative_paths: list[Path] = []
    for source, _ in successful:
        try:
            relative_paths.append(source.relative_to(root))
        except ValueError:
            relative_paths.append(Path(source.name))

    sections: list[str] = [_render_directory_structure(root.name or "root", relative_paths)]
    for (source, out_md), relative in zip(successful, relative_paths):
        content = out_md.read_text(encoding="utf-8").strip()
        section = f"{SECTION_SEPARATOR}\nFILE: {relative.as_posix()}\n{SECTION_SEPARATOR}"
        if content:
            section = f"{section}\n{content}"
        sections.append(section)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n\n".join(sections) + "\n", encoding="utf-8", newline="\n")
    return True
