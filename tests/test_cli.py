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

    source3 = tmp_path / "draft.txt"
    source3.write_text("draft text\n", encoding="utf-8")
    assert hammerdown.cli.main(["--in_place", str(source3)]) == 0
    assert (tmp_path / "hm_draft_txt.md").read_text(encoding="utf-8") == "draft text\n"


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

    assert hammerdown.cli.main(["--skip_existing", str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").read_text(encoding="utf-8") == "line one\n"


def test_skip_existing_and_overwrite_statuses(tmp_path: Path, caplog):
    import logging

    source = tmp_path / "notes.txt"
    source.write_text("initial\n", encoding="utf-8")
    assert hammerdown.cli.main([str(source)]) == 0
    source.write_text("updated\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="hammerdown"):
        assert hammerdown.cli.main(["--skip-existing", str(source)]) == 0
    assert "skipped" in caplog.text.lower()

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="hammerdown"):
        assert hammerdown.cli.main(["--overwrite", str(source)]) == 0
    assert "overwritten" in caplog.text.lower()


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


def test_mixed_existing_and_missing_files_continue(tmp_path: Path, caplog):
    import logging

    source = tmp_path / "valid.txt"
    source.write_text("valid content\n", encoding="utf-8")
    missing = tmp_path / "missing.txt"

    with caplog.at_level(logging.INFO, logger="hammerdown"):
        assert hammerdown.cli.main([str(missing), str(source)]) == 1

    assert (tmp_path / "hm_valid_txt.md").is_file()
    assert "missing.txt" in caplog.text
    assert "file or directory not found" in caplog.text


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


def test_linux_mime_types():
    from hammerdown.cli import LINUX_MIME_TYPES

    assert "application/pdf" in LINUX_MIME_TYPES
    assert "application/epub+zip" in LINUX_MIME_TYPES
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in LINUX_MIME_TYPES
    assert "application/msword" in LINUX_MIME_TYPES
    assert "text/csv" in LINUX_MIME_TYPES
    assert "text/plain" in LINUX_MIME_TYPES
    assert "text/markdown" in LINUX_MIME_TYPES
    assert "inode/directory" in LINUX_MIME_TYPES


def test_install_and_uninstall_linux(tmp_path: Path):
    from hammerdown.cli import _install_linux, _uninstall_linux

    launcher_cmd = "python3 -m hammerdown"
    _install_linux(launcher_cmd, home_dir=tmp_path)

    # 1. Launcher script
    launcher = tmp_path / ".local" / "bin" / "hammerdown"
    assert launcher.is_file()
    assert "exec python3 -m hammerdown" in launcher.read_text(encoding="utf-8")

    # 2. FreeDesktop .desktop file
    desktop_file = tmp_path / ".local" / "share" / "applications" / "hammerdown.desktop"
    assert desktop_file.is_file()
    desktop_text = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in desktop_text
    assert "Type=Application" in desktop_text
    assert "Name=Hammer down" in desktop_text
    assert "Exec=" in desktop_text
    assert "%F" in desktop_text
    assert "application/pdf;" in desktop_text
    assert "inode/directory;" in desktop_text

    # 3. KDE Dolphin ServiceMenus (KDE 6 and KDE 5)
    kde6_file = tmp_path / ".local" / "share" / "kio" / "servicemenus" / "hammerdown.desktop"
    assert kde6_file.is_file()
    kde6_text = kde6_file.read_text(encoding="utf-8")
    assert "Type=Service" in kde6_text
    assert "ServiceTypes=KonqPopupMenu/Plugin" in kde6_text
    assert "Actions=HammerDown;" in kde6_text
    assert "X-KDE-Priority=TopLevel" in kde6_text
    assert "[Desktop Action HammerDown]" in kde6_text
    assert "Name=Hammer down file" in kde6_text
    assert "%F" in kde6_text

    kde5_file = tmp_path / ".local" / "share" / "kservices5" / "ServiceMenus" / "hammerdown.desktop"
    assert kde5_file.is_file()
    assert kde5_file.read_text(encoding="utf-8") == kde6_text

    # 4. File manager scripts
    nautilus_script = tmp_path / ".local" / "share" / "nautilus" / "scripts" / "Hammer down file"
    assert nautilus_script.is_file()
    assert f'exec "{launcher}" "$@"' in nautilus_script.read_text(encoding="utf-8")

    nemo_script = tmp_path / ".local" / "share" / "nemo" / "scripts" / "Hammer down file"
    assert nemo_script.is_file()

    caja_script = tmp_path / ".config" / "caja" / "scripts" / "Hammer down file"
    assert caja_script.is_file()

    # 5. Icon file
    icon_file = tmp_path / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "hammerdown.png"
    assert icon_file.is_file()

    # 6. Uninstall
    _uninstall_linux(home_dir=tmp_path)
    assert not launcher.exists()
    assert not desktop_file.exists()
    assert not kde6_file.exists()
    assert not kde5_file.exists()
    assert not nautilus_script.exists()
    assert not nemo_script.exists()
    assert not caja_script.exists()
    assert not icon_file.exists()


def test_install_and_uninstall_macos(tmp_path: Path):
    import plistlib
    from hammerdown.cli import _install_macos, _uninstall_macos

    launcher_cmd = "python3 -m hammerdown"
    _install_macos(launcher_cmd, home_dir=tmp_path)

    # 1. Launcher script
    launcher = tmp_path / ".local" / "bin" / "hammerdown"
    assert launcher.is_file()

    # 2. Quick Action / Service workflow
    workflow_dir = tmp_path / "Library" / "Services" / "Hammer down.workflow"
    assert workflow_dir.is_dir()

    info_plist_path = workflow_dir / "Contents" / "Info.plist"
    assert info_plist_path.is_file()
    with open(info_plist_path, "rb") as fp:
        info_data = plistlib.load(fp)
    assert info_data["CFBundleIdentifier"] == "com.hammerdown.quickaction"
    assert info_data["CFBundleName"] == "Hammer down"
    assert len(info_data["NSServices"]) == 1
    service = info_data["NSServices"][0]
    assert service["NSMenuItem"]["default"] == "Hammer down"
    assert service["NSMessage"] == "runWorkflowAsService"
    assert service["NSRequiredContext"]["NSApplicationIdentifier"] == "com.apple.finder"
    assert "public.item" in service["NSSendFileTypes"]

    wflow_path = workflow_dir / "Contents" / "document.wflow"
    assert wflow_path.is_file()
    with open(wflow_path, "rb") as fp:
        wflow_data = plistlib.load(fp)
    assert wflow_data["workflowMetaData"]["workflowTypeIdentifier"] == "com.apple.Automator.servicesMenu"
    assert wflow_data["workflowMetaData"]["serviceApplicationBundleID"] == "com.apple.finder"
    action = wflow_data["actions"][0]["action"]
    assert action["BundleIdentifier"] == "com.apple.RunShellScript"
    assert action["ActionParameters"]["inputMethod"] == 1
    assert action["ActionParameters"]["shell"] == "/bin/sh"
    assert "exec " in action["ActionParameters"]["COMMAND_STRING"]
    assert str(launcher) in action["ActionParameters"]["COMMAND_STRING"]
    assert '"$@"' in action["ActionParameters"]["COMMAND_STRING"]

    # 3. Uninstall
    _uninstall_macos(home_dir=tmp_path)
    assert not launcher.exists()
    assert not workflow_dir.exists()


def test_create_macos_droplet_mock(tmp_path: Path, monkeypatch):
    import subprocess
    from hammerdown.cli import _create_macos_droplet

    app_dest = tmp_path / "Applications" / "Hammer down.app"

    # When osacompile is not found:
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert not _create_macos_droplet(app_dest, "hammerdown")

    # When osacompile is found and mocked:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/osacompile" if name == "osacompile" else None)

    def dummy_run(cmd, **kwargs):
        # Create minimal Info.plist as osacompile would
        info_dir = app_dest / "Contents"
        info_dir.mkdir(parents=True, exist_ok=True)
        import plistlib
        with open(info_dir / "Info.plist", "wb") as fp:
            plistlib.dump({"CFBundleName": "Hammer down"}, fp, fmt=plistlib.FMT_XML)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", dummy_run)
    assert _create_macos_droplet(app_dest, "hammerdown")

    import plistlib
    with open(app_dest / "Contents" / "Info.plist", "rb") as fp:
        info_data = plistlib.load(fp)
    assert "CFBundleDocumentTypes" in info_data
    assert info_data["CFBundleDocumentTypes"][0]["CFBundleTypeName"] == "Supported Documents"
