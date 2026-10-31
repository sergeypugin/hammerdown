from pathlib import Path
import pytest
import sys

import hammerdown.cli


def test_tree_flag_enables_tree_mode(tmp_path: Path, monkeypatch):
    """Test that --tree flag enables tree mode and creates default output"""
    # Change to tmp_path so output goes there
    monkeypatch.chdir(tmp_path)

    file1 = tmp_path / "doc1.txt"
    file1.write_text("Hello from file 1\n", encoding="utf-8")
    file2 = tmp_path / "doc2.txt"
    file2.write_text("Hello from file 2\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", str(file1), str(file2)])
    assert result == 0

    expected_output = tmp_path / "hammerdowned.md"
    assert expected_output.is_file()
    content = expected_output.read_text(encoding="utf-8")
    assert "FILE: doc1.txt" in content
    assert "FILE: doc2.txt" in content
    assert "Hello from file 1" in content
    assert "Hello from file 2" in content


def test_tree_with_custom_output(tmp_path: Path, monkeypatch):
    """Test that --tree with --merge specifies custom output filename"""
    monkeypatch.chdir(tmp_path)

    file1 = tmp_path / "doc1.txt"
    file1.write_text("Content 1\n", encoding="utf-8")

    custom_output = tmp_path / "custom_tree.md"
    result = hammerdown.cli.main(["--tree", "--merge", str(custom_output), str(file1)])
    assert result == 0

    assert custom_output.is_file()
    content = custom_output.read_text(encoding="utf-8")
    assert "FILE: doc1.txt" in content
    assert "Content 1" in content


def test_tree_incompatible_with_output_dir(tmp_path: Path):
    """Test that --tree cannot be combined with --output-dir"""
    file1 = tmp_path / "doc1.txt"
    file1.write_text("test\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        hammerdown.cli.main(["--tree", "--output-dir", str(output_dir), str(file1)])
    assert exc_info.value.code == 2  # argparse error


def test_tree_incompatible_with_overwrite(tmp_path: Path):
    """Test that --tree cannot be combined with --overwrite"""
    file1 = tmp_path / "doc1.txt"
    file1.write_text("test\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        hammerdown.cli.main(["--tree", "--overwrite", str(file1)])
    assert exc_info.value.code == 2  # argparse error


def test_all_formats_requires_tree(tmp_path: Path):
    """Test that --all-formats can only be used with --tree"""
    file1 = tmp_path / "doc1.txt"
    file1.write_text("test\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        hammerdown.cli.main(["--all-formats", str(file1)])
    assert exc_info.value.code == 2  # argparse error


def test_tree_with_text_files_only(tmp_path: Path, monkeypatch):
    """Test that tree mode handles multiple text files correctly"""
    monkeypatch.chdir(tmp_path)

    text_file1 = tmp_path / "document1.txt"
    text_file1.write_text("Text content 1\n", encoding="utf-8")

    text_file2 = tmp_path / "document2.txt"
    text_file2.write_text("Text content 2\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", str(text_file1), str(text_file2)])
    assert result == 0

    output = tmp_path / "hammerdowned.md"
    assert output.is_file()
    content = output.read_text(encoding="utf-8")
    assert "FILE: document1.txt" in content
    assert "FILE: document2.txt" in content
    assert "Text content 1" in content
    assert "Text content 2" in content


def test_tree_all_formats_with_text_only(tmp_path: Path, monkeypatch):
    """Test that --all-formats works with text files"""
    monkeypatch.chdir(tmp_path)

    text_file = tmp_path / "doc.txt"
    text_file.write_text("Text\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(text_file)])
    assert result == 0

    output = tmp_path / "hammerdounded.md"
    # Just verify the command runs successfully with --all-formats
    assert result == 0


def test_tree_mode_with_directory(tmp_path: Path, monkeypatch):
    """Test that tree mode discovers files in a directory"""
    monkeypatch.chdir(tmp_path)

    subdir = tmp_path / "docs"
    subdir.mkdir()

    file1 = subdir / "file1.txt"
    file1.write_text("File 1\n", encoding="utf-8")

    file2 = subdir / "file2.txt"
    file2.write_text("File 2\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", str(subdir)])
    assert result == 0

    output = tmp_path / "hammerdowned.md"
    assert output.is_file()
    content = output.read_text(encoding="utf-8")
    assert "file1.txt" in content
    assert "file2.txt" in content


def test_tree_flag_short_form(tmp_path: Path, monkeypatch):
    """Test that -t flag (short form of --tree) works"""
    monkeypatch.chdir(tmp_path)

    file1 = tmp_path / "doc.txt"
    file1.write_text("Hello\n", encoding="utf-8")

    result = hammerdown.cli.main(["-t", str(file1)])
    assert result == 0

    expected_output = tmp_path / "hammerdowned.md"
    assert expected_output.is_file()
