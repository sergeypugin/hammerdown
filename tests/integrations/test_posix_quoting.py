from __future__ import annotations

import plistlib
import shlex
import subprocess
from pathlib import Path

from hammerdown.integrations._common import _quote_if_needed
from hammerdown.integrations.linux import _install_linux
from hammerdown.integrations.macos import _create_macos_droplet, _create_macos_workflow


def test_posix_launcher_quoting_is_literal_safe(tmp_path: Path, monkeypatch):
    home = tmp_path / 'Home $`semi; slash\\space'
    launcher = home / ".local" / "bin" / "hammerdown"

    _install_linux("python3 -m hammerdown", home_dir=home)

    expected_shell_path = shlex.quote(str(launcher))
    for rel_path in (
        ".local/share/nautilus/scripts/Hammerdown",
        ".local/share/nautilus/scripts/Hammerdown and merge",
        ".local/share/nautilus/scripts/Hammerdown tree",
        ".local/share/nautilus/scripts/Hammerdown tree with all formats",
    ):
        script = (home / rel_path).read_text(encoding="utf-8")
        assert script.startswith(f"exec {expected_shell_path} ")
        assert '"$@"' in script

    desktop = (home / ".local/share/applications/hammerdown.desktop").read_text(encoding="utf-8")
    assert f'Exec="{str(launcher).replace(chr(92), chr(92) * 2).replace("$", "\\$").replace("`", "\\`").replace(chr(34), "\\\"")}" %F' in desktop
    assert "--coordinator --right-click --merge-auto %F" in desktop

    workflow = home / "Hammerdown.workflow"
    _create_macos_workflow(workflow, launcher)
    with open(workflow / "Contents/document.wflow", "rb") as fp:
        command = plistlib.load(fp)["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert expected_shell_path in command
    assert '"$@"' in command

    monkeypatch.setattr("hammerdown.integrations.macos.shutil.which", lambda _: "/usr/bin/osacompile")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["source"] = cmd[-1]
        app_contents = Path(cmd[cmd.index("-o") + 1]) / "Contents"
        app_contents.mkdir(parents=True)
        with open(app_contents / "Info.plist", "wb") as fp:
            plistlib.dump({}, fp)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("hammerdown.integrations.macos.subprocess.run", fake_run)
    assert _create_macos_droplet(home / "Applications/Hammerdown.app", launcher)
    assert f'set cmd to "{expected_shell_path.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' in captured["source"]


def test_shell_quote_helper_handles_metacharacters():
    value = r"/tmp/path $tick` semi; slash\end"
    quoted = _quote_if_needed(value)
    assert quoted == shlex.quote(value)
    assert quoted.startswith("'")
    assert "'" + value + "'" == quoted


def test_desktop_exec_path_without_spaces_is_quoted_when_unsafe(tmp_path: Path):
    home = tmp_path / "$unsafe;path"
    _install_linux("python3 -m hammerdown", home_dir=home)
    desktop = (home / ".local/share/applications/hammerdown.desktop").read_text(encoding="utf-8")
    assert "Exec=\"" in desktop
    assert "\\$unsafe;path" in desktop
    assert 'hammerdown" %F' in desktop
    assert _quote_if_needed(home / ".local/bin/hammerdown").startswith("'")


def test_macos_workflow_preserves_extra_flags(tmp_path: Path):
    _create_macos_workflow(tmp_path / "workflow", "/tmp/path with $cash", extra_flags="--tree --all-formats")
    with open(tmp_path / "workflow/Contents/document.wflow", "rb") as fp:
        command = plistlib.load(fp)["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert "--tree --all-formats" in command
    assert '"$@"' in command
    assert "'" in command


def test_linux_scripts_emit_exact_shell_quoted_launcher(tmp_path: Path):
    home = tmp_path / "contains spaces"
    _install_linux("python3 -m hammerdown", home_dir=home)
    launcher = home / ".local/bin/hammerdown"
    script = (home / ".local/share/nemo/scripts/Hammerdown").read_text(encoding="utf-8")
    assert script == f'exec {shlex.quote(str(launcher))} "$@"\n'
