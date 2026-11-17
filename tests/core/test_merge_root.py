from pathlib import Path

from hammerdown.core.merge import merge_root_for_inputs


def test_merge_root_for_single_directory_is_its_parent(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()

    assert merge_root_for_inputs([str(folder)], []) == tmp_path


def test_merge_root_for_single_file_is_its_directory(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text\n", encoding="utf-8")

    assert merge_root_for_inputs([str(source)], []) == tmp_path


def test_merge_root_for_sibling_directories_is_common_parent(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert merge_root_for_inputs([str(first), str(second)], []) == tmp_path


def test_merge_root_for_nested_directories_is_outer_parent(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)

    assert merge_root_for_inputs([str(outer), str(inner)], []) == tmp_path


def test_merge_root_for_files_in_different_directories_is_common_parent(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.txt").write_text("a\n", encoding="utf-8")
    (second / "b.txt").write_text("b\n", encoding="utf-8")

    assert merge_root_for_inputs([str(first / "a.txt"), str(second / "b.txt")], []) == tmp_path
