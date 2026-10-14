from pathlib import Path


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

    from hammerdown.integrations.windows import _install_windows

    _install_windows("hammerdown")

    sendto_cmd = sendto_dir / "Hammer down.cmd"
    assert sendto_cmd.is_file()
    assert "--coordinator %*" in sendto_cmd.read_text(encoding="utf-8")
    assert r"Software\Classes\Directory\shell\hammerdown" in recorded_keys
    assert r"Software\Classes\Directory\Background\shell\hammerdown" in recorded_keys


def test_linux_mime_types():
    from hammerdown.integrations.linux import LINUX_MIME_TYPES

    assert "application/pdf" in LINUX_MIME_TYPES
    assert "application/epub+zip" in LINUX_MIME_TYPES
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in LINUX_MIME_TYPES
    assert "application/msword" in LINUX_MIME_TYPES
    assert "text/csv" in LINUX_MIME_TYPES
    assert "text/plain" in LINUX_MIME_TYPES
    assert "text/markdown" in LINUX_MIME_TYPES
    assert "inode/directory" in LINUX_MIME_TYPES


def test_install_and_uninstall_linux(tmp_path: Path):
    from hammerdown.integrations.linux import _install_linux, _uninstall_linux

    launcher_cmd = "python3 -m hammerdown"
    _install_linux(launcher_cmd, home_dir=tmp_path)

    launcher = tmp_path / ".local" / "bin" / "hammerdown"
    assert launcher.is_file()
    assert "exec python3 -m hammerdown" in launcher.read_text(encoding="utf-8")

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

    nautilus_script = tmp_path / ".local" / "share" / "nautilus" / "scripts" / "Hammer down file"
    assert nautilus_script.is_file()
    assert f'exec "{launcher}" "$@"' in nautilus_script.read_text(encoding="utf-8")

    nemo_script = tmp_path / ".local" / "share" / "nemo" / "scripts" / "Hammer down file"
    assert nemo_script.is_file()

    caja_script = tmp_path / ".config" / "caja" / "scripts" / "Hammer down file"
    assert caja_script.is_file()

    icon_file = tmp_path / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "hammerdown.png"
    assert icon_file.is_file()

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
    from hammerdown.integrations.macos import _install_macos, _uninstall_macos

    launcher_cmd = "python3 -m hammerdown"
    _install_macos(launcher_cmd, home_dir=tmp_path)

    launcher = tmp_path / ".local" / "bin" / "hammerdown"
    assert launcher.is_file()

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

    _uninstall_macos(home_dir=tmp_path)
    assert not launcher.exists()
    assert not workflow_dir.exists()


def test_create_macos_droplet_mock(tmp_path: Path, monkeypatch):
    import subprocess

    from hammerdown.integrations.macos import _create_macos_droplet

    app_dest = tmp_path / "Applications" / "Hammer down.app"

    monkeypatch.setattr("shutil.which", lambda name: None)
    assert not _create_macos_droplet(app_dest, "hammerdown")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/osacompile" if name == "osacompile" else None)

    def dummy_run(cmd, **kwargs):
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
