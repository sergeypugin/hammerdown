"""NUL-bearing text files are binary junk in every mode, not mojibake Markdown."""
from pathlib import Path

import pytest

import hammerdown.cli
from hammerdown.core import to_markdown


BROKEN_BYTES = b"alpha\r\nbeta\t  \r\n\x00tail\xff\n"


def _write_broken(path: Path) -> Path:
    path.write_bytes(BROKEN_BYTES)
    return path


def _write_good(tmp_path: Path) -> Path:
    good = tmp_path / "clean.txt"
    good.write_text("clean content\n", encoding="utf-8")
    return good


def test_merge_skips_nul_text_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = _write_broken(tmp_path / "strange.txt")
    good = _write_good(tmp_path)
    target = tmp_path / "merged.md"
    monkeypatch.chdir(tmp_path)

    # An explicitly selected NUL file is an unsupported-format error, the same
    # as any other unconvertible format named on the command line.
    assert hammerdown.cli.main(["-m", str(target), str(good), str(broken)]) == 1

    content = target.read_text(encoding="utf-8")
    assert "FILE: clean.txt" in content
    assert "FILE: strange.txt" not in content
    assert "\x00" not in content


def test_tree_skips_nul_text_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = _write_broken(tmp_path / "strange.txt")
    good = _write_good(tmp_path)
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)

    assert hammerdown.cli.main(["--tree", str(good), str(broken)]) == 0

    content = target.read_text(encoding="utf-8")
    assert "FILE: clean.txt" in content
    assert "FILE: strange.txt" not in content
    assert "\x00" not in content


def test_to_markdown_rejects_nul_text(tmp_path: Path) -> None:
    broken = _write_broken(tmp_path / "strange.txt")

    with pytest.raises(ValueError, match="binary content in text file"):
        to_markdown(broken)


def test_to_markdown_rejects_nul_csv(tmp_path: Path) -> None:
    broken = tmp_path / "broken.csv"
    broken.write_bytes(b"a,b\r\n1,\x002\n")

    with pytest.raises(ValueError, match="binary content in CSV file"):
        to_markdown(broken)


def test_cli_merge_fails_gracefully_on_nul_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # CSV keeps zip-detection precedence, so the NUL guard fires at conversion
    # time and the merge records a failed-conversion block instead of NUL bytes.
    broken_csv = tmp_path / "broken.csv"
    broken_csv.write_bytes(b"a,b\r\n1,\x002\n")
    good = _write_good(tmp_path)
    target = tmp_path / "merged.md"
    monkeypatch.chdir(tmp_path)

    assert hammerdown.cli.main(["-m", str(target), str(good), str(broken_csv)]) == 1

    content = target.read_text(encoding="utf-8")
    assert "[!] File conversion failed" in content
    assert "\x00" not in content
