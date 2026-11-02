from __future__ import annotations

from pathlib import Path

from hammerdown.core.discovery import discover_paths, discover_tree
from hammerdown.core.filters import compile_cli_filters


def _result_signature(result) -> tuple[set[str], set[tuple[str, str]]]:
    return (
        {target.path for target in result.targets},
        {(skip.path, skip.reason) for skip in result.skipped},
    )


def test_overlapping_roots_include_filter_is_order_independent(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    document = child / "document.txt"
    document.write_text("content", encoding="utf-8")
    include, exclude = compile_cli_filters(["child/document.txt"], ())

    parent_first = discover_paths(
        [str(tmp_path), str(child)],
        include_patterns=include,
        exclude_patterns=exclude,
    )
    child_first = discover_paths(
        [str(child), str(tmp_path)],
        include_patterns=include,
        exclude_patterns=exclude,
    )

    assert _result_signature(parent_first) == _result_signature(child_first)
    assert _result_signature(parent_first) == ({str(document.resolve())}, set())


def test_overlapping_roots_exclude_filter_is_order_independent(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    document = child / "document.txt"
    document.write_text("content", encoding="utf-8")
    include, exclude = compile_cli_filters((), ["child/document.txt"])

    parent_first = discover_paths(
        [str(tmp_path), str(child)],
        include_patterns=include,
        exclude_patterns=exclude,
    )
    child_first = discover_paths(
        [str(child), str(tmp_path)],
        include_patterns=include,
        exclude_patterns=exclude,
    )

    assert _result_signature(parent_first) == _result_signature(child_first)
    assert _result_signature(parent_first) == (
        set(),
        {(str(document.resolve()), "cli exclude filter")},
    )


def test_utf8_character_starting_at_sample_boundary_is_text(tmp_path: Path) -> None:
    document = tmp_path / "boundary.txt"
    document.write_bytes(b"a" * 8191 + "€".encode("utf-8") + b"\n")

    result = discover_tree([str(tmp_path)])

    assert {target.path for target in result.targets} == {str(document.resolve())}
    assert result.skipped == []


def test_nul_byte_still_marks_text_extension_as_unsupported(tmp_path: Path) -> None:
    document = tmp_path / "binary.txt"
    document.write_bytes(b"a" * 8191 + b"\x00text")

    result = discover_tree([str(tmp_path)])

    assert result.targets == []
    assert [(skip.path, skip.reason) for skip in result.skipped] == [
        (str(document.resolve()), "unsupported format")
    ]
