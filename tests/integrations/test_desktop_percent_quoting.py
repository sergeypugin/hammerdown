from __future__ import annotations

import plistlib
import shlex
from pathlib import Path

from hammerdown.integrations._common import _quote_desktop_exec, _quote_if_needed
from hammerdown.integrations.linux import _install_linux
from hammerdown.integrations.macos import _create_macos_workflow


def test_desktop_exec_escapes_percent_field_codes_in_launcher_path(tmp_path: Path):
    home = tmp_path / "Home %F %U"
    launcher = home / ".local" / "bin" / "hammerdown"

    _install_linux("python3 -m hammerdown", home_dir=home)

    desktop_path = home / ".local/share/applications/hammerdown.desktop"
    kde_path = home / ".local/share/kio/servicemenus/hammerdown.desktop"
    expected_exec = _quote_desktop_exec(launcher)
    for path in (desktop_path, kde_path):
        desktop = path.read_text(encoding="utf-8")
        assert f"Exec={expected_exec} %F" in desktop
        assert "%%F %%U" in expected_exec


def test_percent_launcher_path_keeps_shell_and_applescript_quoting_contracts(tmp_path: Path):
    home = tmp_path / "Home %F %U"
    launcher = home / ".local" / "bin" / "hammerdown"

    _install_linux("python3 -m hammerdown", home_dir=home)

    script = (home / ".local/share/nautilus/scripts/Hammerdown").read_text(encoding="utf-8")
    assert script == f'exec {shlex.quote(str(launcher))} "$@"\n'

    workflow_dir = home / "Hammerdown.workflow"
    _create_macos_workflow(workflow_dir, launcher)
    with open(workflow_dir / "Contents/document.wflow", "rb") as fp:
        command = plistlib.load(fp)["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert _quote_if_needed(launcher) in command
    assert "%%F" not in command
    assert '"$@"' in command


def test_desktop_exec_doubles_percent_without_otherwise_changing_plain_paths():
    assert _quote_desktop_exec("/tmp/hammerdown") == "/tmp/hammerdown"
    assert _quote_desktop_exec("/tmp/percent%path") == "/tmp/percent%%path"
    assert _quote_if_needed("/tmp/percent%path") == "/tmp/percent%path"


__all__ = []
