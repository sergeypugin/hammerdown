from pathlib import Path

from hammerdown.core import ConversionResult
from hammerdown.core import stdout_mode


def test_single_file_conversion_failure_writes_only_to_stderr(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "broken.docx"
    error = "failed to convert broken.docx"

    monkeypatch.setattr(
        stdout_mode,
        "convert_file",
        lambda *args, **kwargs: ConversionResult(False, error=error),
    )

    assert stdout_mode.run_stdout_conversion([str(source)], [str(source)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"[!] {source.name}: {error}" in captured.err


def test_single_file_success_writes_raw_markdown_to_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "document.docx"
    markdown = "# Document\n\nRaw Markdown\n"

    monkeypatch.setattr(
        stdout_mode,
        "convert_file",
        lambda *args, **kwargs: ConversionResult(True, markdown=markdown),
    )

    assert stdout_mode.run_stdout_conversion([str(source)], [str(source)]) == 0

    captured = capsys.readouterr()
    assert captured.out == markdown
    assert captured.err == ""


def test_multi_file_stdout_has_sections_and_no_binary_markers(tmp_path, monkeypatch, capsys) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("Alpha\n", encoding="utf-8")
    second.write_text("Beta\n", encoding="utf-8")

    monkeypatch.setattr(
        stdout_mode,
        "convert_file",
        lambda path, **kwargs: ConversionResult(True, markdown=f"Content of {Path(path).name}\n"),
    )

    assert stdout_mode.run_stdout_conversion([str(first), str(second)], [str(first), str(second)]) == 0

    captured = capsys.readouterr()
    assert "FILE: a.txt" in captured.out
    assert "FILE: b.txt" in captured.out
    assert "[Binary file]" not in captured.out
