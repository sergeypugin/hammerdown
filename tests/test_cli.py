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
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\nline two\n"


def test_convert_file_in_place(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\nline two\n", encoding="utf-8")

    assert hammerdown.core.convert_file(source, in_place=True)
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\nline two\n"

    source2 = tmp_path / "memo.txt"
    source2.write_text("memo text\n", encoding="utf-8")
    assert hammerdown.cli.main(["--in-place", str(source2)]) == 0
    assert (tmp_path / "hm_memo_txt.md").read_text(encoding="utf-8") == "memo text\n"


def test_overwrite_by_default(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\n", encoding="utf-8")
    assert hammerdown.core.convert_file(source)
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\n"

    # Modifying source and running again overwrites existing output by default
    source.write_text("updated line\n", encoding="utf-8")
    assert hammerdown.cli.main([str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "updated line\n"


def test_skip_existing_flag(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("line one\n", encoding="utf-8")
    assert hammerdown.cli.main([str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\n"

    # Modify source, but with -s / --skip-existing the output is not overwritten
    source.write_text("modified text\n", encoding="utf-8")
    assert hammerdown.cli.main(["-s", str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\n"

    assert hammerdown.cli.main(["--skip-existing", str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\n"


def test_quiet_flag_suppresses_logs(tmp_path: Path, caplog):
    import logging

    source = tmp_path / "notes.txt"
    source.write_text("quiet test\n", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert hammerdown.cli.main(["-q", str(source)]) == 0
    assert "Completed" not in caplog.text

    with caplog.at_level(logging.INFO):
        assert hammerdown.cli.main(["--quiet", str(source)]) == 0


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


def test_overwrite_flag_plain_text(tmp_path: Path):
    source_txt = tmp_path / "notes.txt"
    source_txt.write_text("initial text\n", encoding="utf-8")

    assert hammerdown.cli.main(["-w", str(source_txt)]) == 0
    assert not (tmp_path / "hm_notes_txt.md").exists()
    assert source_txt.read_text(encoding="utf-8") == "initial text\n"

    source_md = tmp_path / "doc.md"
    source_md.write_text("# Heading\n\nSome text   \n", encoding="utf-8")
    assert hammerdown.cli.main(["--overwrite", str(source_md)]) == 0
    assert not (tmp_path / "hm_doc_md.md").exists()
    assert source_md.read_text(encoding="utf-8") == "# Heading\n\nSome text\n"


def test_overwrite_flag_ignored_for_binary_format(tmp_path: Path):
    import docx

    source_docx = tmp_path / "test.docx"
    doc = docx.Document()
    doc.add_paragraph("Sample content")
    doc.save(str(source_docx))

    orig_bytes = source_docx.read_bytes()
    assert hammerdown.cli.main(["-w", str(source_docx)]) == 0

    # Binary source file must remain untouched
    assert source_docx.read_bytes() == orig_bytes
    out_md = tmp_path / "hm_test_docx.md"
    assert out_md.is_file()
    assert "Sample content" in out_md.read_text(encoding="utf-8")


def test_logging_progress_from_zero(tmp_path: Path, caplog):
    import logging
    import docx

    source_docx = tmp_path / "doc.docx"
    doc = docx.Document()
    for i in range(5):
        doc.add_paragraph(f"Paragraph {i}")
    doc.save(str(source_docx))

    with caplog.at_level(logging.INFO, logger="hammerdown"):
        assert hammerdown.core.convert_file(source_docx)

    progress_messages = [record.message for record in caplog.records if "(0%)" in record.message]
    assert len(progress_messages) > 0, "Expected a log message starting at 0%"
