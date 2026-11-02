from __future__ import annotations

from pathlib import Path

from hammerdown.cli import main


def test_skip_existing_directory_output_collision_fails_without_touching_directory(
    tmp_path: Path,
    capsys,
    caplog,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    target = output_dir / "hm_source_txt.md"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep me\n", encoding="utf-8")

    result = main(["--skip-existing", "--output-dir", str(output_dir), str(source)])

    captured = capsys.readouterr()
    assert result == 1
    assert target.is_dir()
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert "skipped existing outputs" not in captured.out.lower()
    assert "output target is a directory" in caplog.text.lower()


def test_skip_existing_directory_merge_collision_fails_without_touching_directory(
    tmp_path: Path,
    capsys,
    caplog,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep me\n", encoding="utf-8")

    result = main(["--skip-existing", "--merge", str(target), str(source)])

    captured = capsys.readouterr()
    assert result == 1
    assert target.is_dir()
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert "skipped existing merge output" not in captured.out.lower()
    assert "output target is a directory" in caplog.text.lower()


def test_skip_existing_file_output_preserves_stale_markdown(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content\n", encoding="utf-8")
    target = tmp_path / "hm_source_txt.md"
    target.write_text("stale content\n", encoding="utf-8")

    result = main(["--skip-existing", str(source)])

    assert result == 0
    assert target.read_text(encoding="utf-8") == "stale content\n"


def test_merge_file_target_still_writes_merged_markdown(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first content\n", encoding="utf-8")
    second.write_text("second content\n", encoding="utf-8")
    target = tmp_path / "merged.md"

    result = main(["--merge", str(target), str(first), str(second)])

    assert result == 0
    content = target.read_text(encoding="utf-8")
    assert "FILE: first.txt" in content
    assert "first content" in content
    assert "FILE: second.txt" in content
    assert "second content" in content
