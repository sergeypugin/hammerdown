from __future__ import annotations

import shlex
import sys
from pathlib import Path


def test_installed_command_quotes_posix_metacharacters(tmp_path: Path, monkeypatch):
    from hammerdown.integrations import _installed_command

    home = tmp_path / "home;$(touch hacked)"
    interpreter = tmp_path / "python $HOME;$(touch hacked)"
    monkeypatch.setattr("hammerdown.integrations.is_windows", lambda: False)
    monkeypatch.setattr(sys, "executable", str(interpreter))

    _, command = _installed_command(home_dir=home)

    runner = home / ".local" / "share" / "hammerdown" / "hammerdown_runner.py"
    assert command == f"{shlex.quote(str(interpreter))} {shlex.quote(str(runner))}"


def test_installed_command_preserves_windows_double_quote_contract(tmp_path: Path, monkeypatch):
    from hammerdown.integrations import _installed_command

    monkeypatch.setattr("hammerdown.integrations.is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local AppData"))
    interpreter = tmp_path / "Python Directory" / "python.exe"
    monkeypatch.setattr(sys, "executable", str(interpreter))

    _, command = _installed_command(home_dir=tmp_path / "Home Directory")

    runner = tmp_path / "Local AppData" / "Programs" / "hammerdown" / "hammerdown_runner.py"
    assert command == f'"{interpreter}" "{runner}"'


def test_installed_command_uses_windowed_python_with_windows_contract(tmp_path: Path, monkeypatch):
    from hammerdown.integrations import _installed_command

    monkeypatch.setattr("hammerdown.integrations.is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    interpreter = tmp_path / "python.exe"
    windowed = tmp_path / "pythonw.exe"
    interpreter.write_text("", encoding="utf-8")
    windowed.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(interpreter))

    _, command = _installed_command(home_dir=tmp_path)

    runner = tmp_path / "Programs" / "hammerdown" / "hammerdown_runner.py"
    assert command == f'"{windowed}" "{runner}"'
