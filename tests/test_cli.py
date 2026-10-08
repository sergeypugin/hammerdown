from pathlib import Path

import converter


def test_normalize_wsl_windows_path():
    normalized = converter.normalize_path(r"C:\Users\someone\document.pdf")
    if converter.os.name == "nt":
        assert normalized.endswith(r"C:\Users\someone\document.pdf")
    else:
        assert normalized.endswith("/mnt/c/Users/someone/document.pdf")


def test_convert_plain_text_creates_markdown_output(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\nline two\n", encoding="utf-8")

    assert converter.convert_file(source)
    assert (tmp_path / "MD_notes" / "notes.md").read_text(encoding="utf-8") == "line one\nline two\n"


def test_unsupported_file_returns_failure(tmp_path: Path):
    source = tmp_path / "image.png"
    source.write_bytes(b"image")

    assert converter.main([str(source)]) == 1


def test_missing_file_returns_failure(tmp_path: Path):
    assert converter.main([str(tmp_path / "missing.pdf")]) == 1


def test_version_option(capsys):
    try:
        converter.main(["--version"])
    except SystemExit as error:
        assert error.code == 0
    assert f"md-maker {converter.__version__}" in capsys.readouterr().out
