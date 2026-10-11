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


def test_recursive_directory_traversal(tmp_path: Path):
    root_dir = tmp_path / "documents"
    sub_dir = root_dir / "nested" / "deep"
    sub_dir.mkdir(parents=True)

    file1 = root_dir / "doc1.txt"
    file1.write_text("content 1\n", encoding="utf-8")

    file2 = sub_dir / "doc2.txt"
    file2.write_text("content 2\n", encoding="utf-8")

    ignored_temp = root_dir / "~$temp.docx"
    ignored_temp.write_bytes(b"temp")

    ignored_hidden = sub_dir / ".hidden.txt"
    ignored_hidden.write_text("secret\n", encoding="utf-8")

    assert hammerdown.cli.main([str(root_dir)]) == 0

    assert (root_dir / "hm_doc1_txt.md").is_file()
    assert (root_dir / "hm_doc1_txt.md").read_text(encoding="utf-8") == "content 1\n"
    assert (sub_dir / "hm_doc2_txt.md").is_file()
    assert (sub_dir / "hm_doc2_txt.md").read_text(encoding="utf-8") == "content 2\n"

    assert not (root_dir / "hm_~$temp_docx.md").exists()
    assert not (sub_dir / "hm_.hidden_txt.md").exists()


def test_recursive_directory_empty_or_no_supported_files(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert hammerdown.cli.main([str(empty_dir)]) == 0

    unsupported_dir = tmp_path / "unsupported"
    unsupported_dir.mkdir()
    (unsupported_dir / "data.bin").write_bytes(b"12345")
    assert hammerdown.cli.main([str(unsupported_dir)]) == 0


def test_merge_converted_files(tmp_path: Path):
    file1 = tmp_path / "doc1.txt"
    file1.write_text("Hello from file 1\n", encoding="utf-8")
    file2 = tmp_path / "doc2.txt"
    file2.write_text("Hello from file 2\n", encoding="utf-8")

    merged_file = tmp_path / "summary.md"
    assert hammerdown.cli.main(["--merge", str(merged_file), str(file1), str(file2)]) == 0

    assert merged_file.is_file()
    content = merged_file.read_text(encoding="utf-8")
    assert "# doc1.txt" in content
    assert "Hello from file 1" in content
    assert "# doc2.txt" in content
    assert "Hello from file 2" in content


def test_merge_with_short_flag_and_skipped_failure(tmp_path: Path):
    file1 = tmp_path / "doc1.txt"
    file1.write_text("Hello from file 1\n", encoding="utf-8")
    bad_file = tmp_path / "missing.docx"

    merged_file = tmp_path / "partial.md"
    assert hammerdown.cli.main(["-m", str(merged_file), str(file1), str(bad_file)]) == 1

    assert merged_file.is_file()
    content = merged_file.read_text(encoding="utf-8")
    assert "# doc1.txt" in content
    assert "missing.docx" not in content


def test_install_windows_creates_sendto_shortcut(tmp_path: Path, monkeypatch):
    sendto_dir = tmp_path / "Microsoft" / "Windows" / "SendTo"
    sendto_dir.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    recorded_keys = []

    class DummyKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def dummy_create_key(root, subkey):
        recorded_keys.append(subkey)
        return DummyKey()

    def dummy_set_value(key, value_name, reserved, type_, value):
        pass

    import sys
    import types

    fake_winreg = types.ModuleType("winreg")
    setattr(fake_winreg, "HKEY_CURRENT_USER", "HKEY_CURRENT_USER")
    setattr(fake_winreg, "REG_SZ", 1)
    setattr(fake_winreg, "CreateKey", dummy_create_key)
    setattr(fake_winreg, "SetValueEx", dummy_set_value)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    hammerdown.cli._install_windows("hammerdown")

    sendto_cmd = sendto_dir / "Hammer down.cmd"
    assert sendto_cmd.is_file()
    cmd_content = sendto_cmd.read_text(encoding="utf-8")
    assert "--coordinator %*" in cmd_content

    assert r"Software\Classes\Directory\shell\hammerdown" in recorded_keys
    assert r"Software\Classes\Directory\Background\shell\hammerdown" in recorded_keys
