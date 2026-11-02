from __future__ import annotations

from pathlib import Path

import pytest

import hammerdown.core as core
from hammerdown.batch import convert_files
from hammerdown.cli import main


@pytest.mark.parametrize("extension", [".txt", ".md", ".log", ".csv"])
def test_convert_file_overwrites_supported_text_source_in_place(
    tmp_path: Path, extension: str
) -> None:
    source = tmp_path / f"notes{extension}"
    source.write_text("first,second\nvalue,1\n", encoding="utf-8")

    result = core.convert_file(source, overwrite=True)

    assert result.success
    assert result.output_path == source
    assert not (tmp_path / f"hm_notes_{extension[1:]}_md.md").exists()
    assert source.read_text(encoding="utf-8").endswith("\n")


def test_cli_overwrite_rewrites_log_and_reports_output_path(tmp_path: Path) -> None:
    source = tmp_path / "application.log"
    source.write_text("before\n", encoding="utf-8")

    assert main(["--overwrite", str(source)]) == 0

    assert source.read_text(encoding="utf-8") == "before\n"
    assert not (tmp_path / "hm_application_log.md").exists()


def test_batch_overwrite_reports_converted_and_overwritten_counts(
    tmp_path: Path, capsys
) -> None:
    text_source = tmp_path / "notes.md"
    csv_source = tmp_path / "data.csv"
    text_source.write_text("# notes\n", encoding="utf-8")
    csv_source.write_text("name,value\nitem,1\n", encoding="utf-8")

    assert convert_files([text_source, csv_source], overwrite=True) == 0

    output = capsys.readouterr().out
    assert "Completed: 2" in output
    assert "Overwritten: 2" in output
    assert "2    converted files" in output
    assert "2    overwritten text sources" in output
    assert text_source.read_text(encoding="utf-8") == "# notes\n"
    assert csv_source.read_text(encoding="utf-8").endswith("\n")
    assert not (tmp_path / "hm_notes_md.md").exists()
    assert not (tmp_path / "hm_data_csv.md").exists()


def test_skip_existing_and_overwrite_are_a_conflict_for_batch_api(tmp_path: Path) -> None:
    source = tmp_path / "notes.log"
    source.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite cannot be combined with skip_existing"):
        convert_files([source], overwrite=True, skip_existing=True)


def test_cli_rejects_skip_existing_and_overwrite_together(tmp_path: Path, capsys) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["--overwrite", "--skip-existing", str(source)])

    assert exc.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_skip_existing_preserves_existing_text_output(tmp_path: Path, capsys) -> None:
    source = tmp_path / "notes.log"
    source.write_text("initial\n", encoding="utf-8")
    target = tmp_path / "hm_notes_log.md"
    target.write_text("existing output\n", encoding="utf-8")

    assert convert_files([source], skip_existing=True) == 0

    assert source.read_text(encoding="utf-8") == "initial\n"
    assert target.read_text(encoding="utf-8") == "existing output\n"
    output = capsys.readouterr().out
    assert "Skipped: 1" in output
    assert "1    skipped existing outputs" in output
    assert "converted files" not in output


def test_overwrite_keeps_binary_source_and_creates_markdown_output(tmp_path: Path) -> None:
    import docx

    source = tmp_path / "report.docx"
    document = docx.Document()
    document.add_paragraph("binary source")
    document.save(str(source))
    original = source.read_bytes()

    result = core.convert_file(source, overwrite=True)

    assert result.success
    assert source.read_bytes() == original
    output = tmp_path / "hm_report_docx.md"
    assert result.output_path == output
    assert output.is_file()
    assert "binary source" in output.read_text(encoding="utf-8")


def test_cli_overwrite_binary_status_is_ignored(tmp_path: Path, capsys) -> None:
    source = tmp_path / "report.docx"
    import docx

    document = docx.Document()
    document.add_paragraph("binary source")
    document.save(str(source))
    original = source.read_bytes()

    assert main(["--overwrite", str(source)]) == 0

    assert source.read_bytes() == original
    output = capsys.readouterr().out.lower()
    assert "overwritten: 0" in output
    assert "1    converted files" in output
