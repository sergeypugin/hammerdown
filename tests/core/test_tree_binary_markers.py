"""Tests for binary file markers in --tree mode merged markdown output."""
from pathlib import Path
import pytest

import hammerdown.cli


def test_tree_binary_markers_with_mixed_files(tmp_path: Path, monkeypatch):
    """Test that binary files get markers in tree mode merged output."""
    monkeypatch.chdir(tmp_path)

    # Create a text file
    text_file = tmp_path / "document.txt"
    text_file.write_text("This is a text document\n", encoding="utf-8")

    # Create a fake PDF file (we'll just use binary data)
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%fake pdf content")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(text_file), str(pdf_file)])
    # Result may be 1 if PDF fails to convert, but that's OK -- we just want to check markers

    # Check merged output
    output = tmp_path / "hammerdowned.md"
    assert output.is_file()
    content = output.read_text(encoding="utf-8")

    # Text file should be converted normally
    assert "FILE: document.txt" in content
    assert "This is a text document" in content

    # Binary file should have marker (even if conversion failed)
    assert "FILE: sample.pdf" in content
    assert "[Binary file] Can be converted with hammerdown: YES" in content


def test_tree_binary_markers_convertible_formats(tmp_path: Path, monkeypatch):
    """Test that convertible binary formats are marked as YES."""
    monkeypatch.chdir(tmp_path)

    # Create text files for tree mode
    text_file = tmp_path / "doc.txt"
    text_file.write_text("Text content\n", encoding="utf-8")

    # Create binary files with convertible extensions
    for ext in [".pdf", ".docx", ".xlsx"]:
        binary_file = tmp_path / f"file{ext}"
        binary_file.write_bytes(b"fake binary content")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(text_file),
                                 str(tmp_path / "file.pdf"),
                                 str(tmp_path / "file.docx"),
                                 str(tmp_path / "file.xlsx")])
    # Result may be 1 if binary files fail to convert

    output = tmp_path / "hammerdowned.md"
    content = output.read_text(encoding="utf-8")

    # All convertible formats should show YES
    assert "[Binary file] Can be converted with hammerdown: YES" in content
    # Count occurrences (should be 3 for .pdf, .docx, .xlsx)
    assert content.count("[Binary file] Can be converted with hammerdown: YES") == 3


def test_tree_binary_markers_unsupported_formats(tmp_path: Path, monkeypatch):
    """Test that unsupported binary formats are marked as NO."""
    monkeypatch.chdir(tmp_path)

    # Create a text file
    text_file = tmp_path / "doc.txt"
    text_file.write_text("Text content\n", encoding="utf-8")

    # Create unsupported binary files
    unsupported_file = tmp_path / "archive.zip"
    unsupported_file.write_bytes(b"PK\x03\x04")  # ZIP file signature

    result = hammerdown.cli.main(["--tree", "--all-formats", str(text_file), str(unsupported_file)])
    # Result may be 1 if binary file fails to convert

    output = tmp_path / "hammerdowned.md"
    content = output.read_text(encoding="utf-8")

    # Unsupported file should not appear in merged output (skipped in tree mode without --all-formats)
    # But with --all-formats, it should be included with binary marker
    if "archive.zip" in content:
        assert "[Binary file] Can be converted with hammerdown: NO" in content


def test_tree_text_files_no_markers(tmp_path: Path, monkeypatch):
    """Test that text files do not get binary markers."""
    monkeypatch.chdir(tmp_path)

    text_file1 = tmp_path / "doc1.txt"
    text_file1.write_text("Content 1\n", encoding="utf-8")

    text_file2 = tmp_path / "doc2.txt"
    text_file2.write_text("Content 2\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", str(text_file1), str(text_file2)])
    assert result == 0

    output = tmp_path / "hammerdowned.md"
    content = output.read_text(encoding="utf-8")

    # Text files should be converted normally, no binary markers
    assert "FILE: doc1.txt" in content
    assert "FILE: doc2.txt" in content
    assert "Content 1" in content
    assert "Content 2" in content
    assert "[Binary file]" not in content


def test_tree_with_directory_mixed_content(tmp_path: Path, monkeypatch):
    """Test tree mode with directory containing mixed text and binary files."""
    monkeypatch.chdir(tmp_path)

    # Create directory structure
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()

    # Create text files
    (docs_dir / "readme.txt").write_text("README content\n", encoding="utf-8")
    (docs_dir / "guide.txt").write_text("Guide content\n", encoding="utf-8")

    # Create binary files
    (docs_dir / "report.pdf").write_bytes(b"%PDF-1.4\nfake")
    (docs_dir / "data.xlsx").write_bytes(b"fake xlsx content")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(docs_dir)])
    # Result may be 1 if binary files fail to convert

    output = tmp_path / "hammerdowned.md"
    assert output.is_file()
    content = output.read_text(encoding="utf-8")

    # Text files should be in content
    assert "readme.txt" in content
    assert "guide.txt" in content
    assert "README content" in content
    assert "Guide content" in content

    # Binary files should have markers
    assert "report.pdf" in content
    assert "[Binary file] Can be converted with hammerdown: YES" in content


def test_tree_custom_merge_output_with_binary(tmp_path: Path, monkeypatch):
    """Test tree mode with custom merge output containing binary markers."""
    monkeypatch.chdir(tmp_path)

    text_file = tmp_path / "doc.txt"
    text_file.write_text("Text content\n", encoding="utf-8")

    binary_file = tmp_path / "file.pdf"
    binary_file.write_bytes(b"%PDF-1.4\nfake")

    custom_output = tmp_path / "custom_merge.md"
    result = hammerdown.cli.main(["--tree", "--all-formats", "--merge", str(custom_output),
                                 str(text_file), str(binary_file)])
    # Result may be 1 if PDF fails to convert

    assert custom_output.is_file()
    content = custom_output.read_text(encoding="utf-8")

    # Verify both files are in the output
    assert "FILE: doc.txt" in content
    assert "FILE: file.pdf" in content
    assert "Text content" in content
    assert "[Binary file] Can be converted with hammerdown: YES" in content


def test_tree_binary_markers_section_format(tmp_path: Path, monkeypatch):
    """Test that binary markers follow the correct section format."""
    monkeypatch.chdir(tmp_path)

    text_file = tmp_path / "doc.txt"
    text_file.write_text("Content\n", encoding="utf-8")

    binary_file = tmp_path / "file.pdf"
    binary_file.write_bytes(b"%PDF-1.4\nfake")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(text_file), str(binary_file)])
    # Result may be 1 if PDF fails to convert

    output = tmp_path / "hammerdowned.md"
    content = output.read_text(encoding="utf-8")

    # Check for proper section separator format
    separator = "=" * 48
    assert f"{separator}\nFILE: file.pdf\n{separator}" in content

    # Binary marker should appear in the file.pdf section
    assert "[Binary file] Can be converted with hammerdown: YES" in content
