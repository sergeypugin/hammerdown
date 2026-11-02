from __future__ import annotations

import re
from pathlib import Path

from pathspec import GitIgnoreSpec

from hammerdown.core.discovery import discover_paths, discover_tree, expand_paths
from hammerdown.core.filters import compile_cli_filters


def _target_names(result) -> set[str]:
    return {Path(target.path).name for target in result.targets}


def test_git_root_ignore_chain_applies_above_selected_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    selected = repository / "docs" / "nested"
    selected.mkdir(parents=True)
    (repository / ".git").mkdir()
    (repository / ".gitignore").write_text("root-hidden.txt\n", encoding="utf-8")
    (repository / "docs" / ".gitingestignore").write_text("nested-hidden.txt\n", encoding="utf-8")
    (selected / "root-hidden.txt").write_text("ignored", encoding="utf-8")
    (selected / "nested-hidden.txt").write_text("ignored", encoding="utf-8")
    (selected / "visible.txt").write_text("visible", encoding="utf-8")

    result = discover_paths([str(selected)])

    assert _target_names(result) == {"visible.txt"}
    assert set(result.ignore_files) == {
        str(repository / ".gitignore"),
        str(repository / "docs" / ".gitingestignore"),
    }


def test_cli_exclude_has_priority_and_skips_are_user_visible(tmp_path: Path) -> None:
    (tmp_path / "include.txt").write_text("x", encoding="utf-8")
    (tmp_path / "exclude.txt").write_text("x", encoding="utf-8")

    result = discover_paths(
        [str(tmp_path)],
        include_patterns=[re.compile(r".*\.txt")],
        exclude_patterns=[re.compile(r"exclude\.txt")],
    )

    assert _target_names(result) == {"include.txt"}
    assert [(Path(skip.path).name, skip.reason) for skip in result.skipped] == [
        ("exclude.txt", "cli exclude filter")
    ]


def test_pathspec_filter_can_be_used_alongside_regex_patterns(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    (tmp_path / "drop.txt").write_text("x", encoding="utf-8")
    spec = GitIgnoreSpec.from_lines(["drop.txt"])

    result = discover_paths([str(tmp_path)], include_patterns=[re.compile(r".*\.txt")], exclude_patterns=[spec])

    assert _target_names(result) == {"keep.txt"}


def test_logs_are_discovered_and_unrecognized_binary_is_never_convertible(tmp_path: Path) -> None:
    (tmp_path / "application.log").write_text("log line\n", encoding="utf-8")
    (tmp_path / "unknown.bin").write_bytes(b"PK\x03\x04")

    result = discover_tree([str(tmp_path)], all_formats=True)

    assert _target_names(result) == {"application.log"}
    assert [(Path(skip.path).name, skip.reason) for skip in result.skipped] == [
        ("unknown.bin", "unsupported format")
    ]


def test_text_extension_with_nul_is_skipped_as_unsupported(tmp_path: Path) -> None:
    (tmp_path / "binary.txt").write_bytes(b"text\x00binary")

    result = discover_tree([str(tmp_path)])

    assert result.targets == []
    assert [(Path(skip.path).name, skip.reason) for skip in result.skipped] == [
        ("binary.txt", "unsupported format")
    ]


def test_tree_default_is_text_only_and_all_formats_adds_supported_documents(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3\n", encoding="utf-8")
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "unknown.bin").write_bytes(b"\x00\xff")

    default_result = discover_tree([str(tmp_path)])
    all_result = discover_tree([str(tmp_path)], all_formats=True)

    assert _target_names(default_result) == {"source.py", "Dockerfile"}
    assert {Path(target.path).name: target.category for target in all_result.targets} == {
        "Dockerfile": "source_code",
        "report.pdf": "binary_document",
        "source.py": "source_code",
    }


def test_gitignored_files_are_omitted_from_skipped_and_can_be_included(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")

    normal = discover_paths([str(tmp_path)])
    included = discover_paths([str(tmp_path)], include_gitignored=True)

    assert _target_names(normal) == {"visible.txt"}
    assert all(Path(skip.path).name != "ignored.txt" for skip in normal.skipped)
    assert _target_names(included) == {"ignored.txt", "visible.txt"}
    assert included.ignore_files == [str(tmp_path / ".gitignore")]


def test_ignored_directory_is_pruned_and_nested_negation_cannot_resurrect_it(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / ".gitingestignore").write_text("!keep.txt\n", encoding="utf-8")
    (ignored / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")

    result = discover_paths([str(tmp_path)])

    assert _target_names(result) == {"visible.txt"}
    assert all(Path(skip.path).name not in {"ignored", "keep.txt"} for skip in result.skipped)
    assert result.ignore_files == [str(tmp_path / ".gitignore")]


def test_include_gitignored_does_not_prune_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "keep.txt").write_text("keep", encoding="utf-8")

    result = discover_paths([str(tmp_path)], include_gitignored=True)

    assert _target_names(result) == {"keep.txt"}
    assert result.ignore_files == [str(tmp_path / ".gitignore")]


def test_include_gitignored_keeps_cli_and_safety_filters(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "excluded.txt").write_text("excluded", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("hidden", encoding="utf-8")

    result = discover_paths(
        [str(tmp_path)],
        exclude_patterns=[re.compile("excluded")],
        include_gitignored=True,
    )

    assert _target_names(result) == {"ignored.txt"}
    assert {skip.reason for skip in result.skipped} == {"cli exclude filter", "safety filter"}


def test_parent_child_roots_deduplicate_by_resolved_path(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    file_path = child / "document.txt"
    file_path.write_text("content", encoding="utf-8")

    result = discover_paths([str(tmp_path), str(child)])
    legacy = expand_paths([str(tmp_path), str(child)])

    assert len(result.targets) == 1
    assert len(legacy) == 1


def test_compiled_identical_include_and_exclude_patterns_keep_exclude_state(tmp_path: Path) -> None:
    document = tmp_path / "document.txt"
    document.write_text("content", encoding="utf-8")
    include, exclude = compile_cli_filters(["document.txt"], ["document.txt"])

    result = discover_paths(
        [str(tmp_path)],
        include_patterns=include,
        exclude_patterns=exclude,
    )

    assert result.targets == []
    assert [(Path(skip.path).name, skip.reason) for skip in result.skipped] == [
        ("document.txt", "cli exclude filter")
    ]


def test_compiled_repeated_patterns_are_ordered_and_deduplicated(tmp_path: Path) -> None:
    document = tmp_path / "document.txt"
    document.write_text("content", encoding="utf-8")
    include, exclude = compile_cli_filters(
        ["other.txt", "document.txt", "document.txt"],
        ["document.txt", "document.txt"],
    )

    result = discover_paths(
        [str(tmp_path)],
        include_patterns=include,
        exclude_patterns=exclude,
    )

    assert result.targets == []
    assert [(Path(skip.path).name, skip.reason) for skip in result.skipped] == [
        ("document.txt", "cli exclude filter")
    ]


def test_reserved_generated_outputs_are_protected_before_cli_filters(tmp_path: Path) -> None:
    generated_names = ["hm_document.md", "HM_OTHER.MD", "hammerdowned.md"]
    for name in generated_names:
        (tmp_path / name).write_text("generated", encoding="utf-8")

    result = discover_paths(
        [str(tmp_path)],
        include_patterns=[GitIgnoreSpec.from_lines(["*.md"])],
    )

    assert result.targets == []
    assert {Path(path).name for path in result.generated_outputs} == set(generated_names)
    assert result.skipped == []
