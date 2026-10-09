from pathlib import Path

import hammerdown.cli
import hammerdown.core
import hammerdown.utils
import os

def test_normalize_wsl_windows_path():
    normalized = hammerdown.utils.normalize_path(r"C:\Users\someone\document.pdf")
    if os.name == "nt":
        assert normalized.endswith(r"C:\Users\someone\document.pdf")
    else:
        assert normalized.endswith("/mnt/c/Users/someone/document.pdf")


def test_convert_plain_text_creates_markdown_output(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\nline two\n", encoding="utf-8")

    assert hammerdown.core.convert_file(source)
    assert (tmp_path / "MD_notes_txt" / "notes.md").read_text(encoding="utf-8") == "line one\nline two\n"


def test_convert_file_in_place(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\nline two\n", encoding="utf-8")

    assert hammerdown.core.convert_file(source, in_place=True)
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "line one\nline two\n"

    source2 = tmp_path / "memo.txt"
    source2.write_text("memo text\n", encoding="utf-8")
    assert hammerdown.cli.main(["--in-place", str(source2)]) == 0
    assert (tmp_path / "memo.md").read_text(encoding="utf-8") == "memo text\n"


def test_convert_file_existing_output_without_force(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\n", encoding="utf-8")
    assert hammerdown.core.convert_file(source)

    # Calling again without force should fail
    assert not hammerdown.core.convert_file(source)
    assert hammerdown.cli.main([str(source)]) == 1

    # Calling with force should succeed
    assert hammerdown.core.convert_file(source, force=True)
    assert hammerdown.cli.main(["--force", str(source)]) == 0


def test_unsupported_file_returns_failure(tmp_path: Path):
    source = tmp_path / "image.png"
    source.write_bytes(b"image")

    assert hammerdown.cli.main([str(source)]) == 1


def test_missing_file_returns_failure(tmp_path: Path):
    assert hammerdown.cli.main([str(tmp_path / "missing.pdf")]) == 1


def test_version_option(capsys):
    try:
        hammerdown.cli.main(["--version"])
    except SystemExit as error:
        assert error.code == 0
    assert f"hammerdown {hammerdown.__version__}" in capsys.readouterr().out
