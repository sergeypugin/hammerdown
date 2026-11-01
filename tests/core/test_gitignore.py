from __future__ import annotations

from pathlib import Path

from hammerdown.core.discovery import discover_paths


def _target_names(result) -> set[str]:
    return {Path(target.path).name for target in result.targets}


def test_nested_gitignore_and_gitingestignore_negation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".gitignore").write_text("*.txt\n", encoding="utf-8")
    (nested / ".gitingestignore").write_text("!keep.txt\n", encoding="utf-8")
    (nested / "keep.txt").write_text("keep", encoding="utf-8")
    (nested / "hidden.txt").write_text("hide", encoding="utf-8")

    result = discover_paths([str(root)])

    assert _target_names(result) == {"keep.txt"}
    assert result.ignore_files == [str(root / ".gitignore"), str(nested / ".gitingestignore")]


def test_both_ignore_filenames_apply_at_same_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("from-git.txt\n", encoding="utf-8")
    (tmp_path / ".gitingestignore").write_text("from-gitingest.txt\n", encoding="utf-8")
    (tmp_path / "from-git.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "from-gitingest.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")

    result = discover_paths([str(tmp_path)])

    assert _target_names(result) == {"visible.txt"}
    assert result.ignore_files == [str(tmp_path / ".gitignore"), str(tmp_path / ".gitingestignore")]


def test_git_file_metadata_marks_nearest_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    selected = repository / "nested"
    selected.mkdir(parents=True)
    (repository / ".git").write_text("gitdir: C:/worktrees/repo\n", encoding="utf-8")
    (repository / ".gitignore").write_text("hidden.txt\n", encoding="utf-8")
    (selected / "hidden.txt").write_text("hidden", encoding="utf-8")
    (selected / "visible.txt").write_text("visible", encoding="utf-8")

    result = discover_paths([str(selected)])

    assert _target_names(result) == {"visible.txt"}
    assert result.ignore_files == [str(repository / ".gitignore")]


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


def test_without_git_root_directory_is_ignore_boundary(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    selected = parent / "selected"
    selected.mkdir(parents=True)
    (parent / ".gitignore").write_text("parent-only.txt\n", encoding="utf-8")
    (selected / "parent-only.txt").write_text("not ignored by ancestor", encoding="utf-8")

    result = discover_paths([str(selected)])

    assert _target_names(result) == {"parent-only.txt"}
    assert result.ignore_files == []


def test_without_git_root_standalone_file_uses_its_parent_as_boundary(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / ".gitingestignore").write_text("ignored.txt\n", encoding="utf-8")
    ignored = selected / "ignored.txt"
    ignored.write_text("ignored", encoding="utf-8")

    result = discover_paths([str(ignored)])

    assert result.targets == []
    assert result.ignore_files == [str(selected / ".gitingestignore")]


def test_include_gitignored_does_not_prune_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "keep.txt").write_text("keep", encoding="utf-8")

    result = discover_paths([str(tmp_path)], include_gitignored=True)

    assert _target_names(result) == {"keep.txt"}
    assert result.ignore_files == [str(tmp_path / ".gitignore")]
