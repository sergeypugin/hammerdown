import sys
from pathlib import Path

import pytest

from hammerdown.integrations import UNSUPPORTED_PLATFORM_MESSAGE, install, uninstall
from hammerdown.integrations.windows_terminal import (
    WINDOWS_TERMINAL_TITLE,
    build_context_worker_command,
    build_windows_terminal_command,
)


def test_worker_command_forwards_options():
    command = build_context_worker_command(
        ["a.pdf", "b.docx"],
        merge=None,
        merge_auto=True,
        include=["docs/.*"],
        exclude=["draft"],
        overwrite=True,
        skip_existing=True,
    )

    assert "--context-worker" in command
    assert "--right-click" in command
    assert "--merge-auto" in command
    assert command[command.index("--include") + 1] == "docs/.*"
    assert command[command.index("--exclude") + 1] == "draft"
    assert "--overwrite" in command
    assert "--skip-existing" in command
    assert command[-2:] == ["a.pdf", "b.docx"]


def test_worker_command_uses_frozen_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(Path("C:/Apps/hammerdown.exe")))

    command = build_context_worker_command(["a.pdf"])

    assert command[0] == str(Path("C:/Apps/hammerdown.exe"))
    assert "-m" not in command


def test_worker_command_uses_console_interpreter_for_pip_install(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(sys, "executable", "C:/Python/pythonw.exe")
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    command = build_context_worker_command(["a.pdf"])

    assert command[0].endswith("python.exe")
    assert not command[0].endswith("pythonw.exe")
    assert command[1:3] == ["-m", "hammerdown"]


def test_terminal_command_is_single_tab_with_title():
    command = build_windows_terminal_command(
        ["a.pdf"],
        terminal="wt.exe",
        tab_color="#feb454",
    )

    assert command[:5] == ["wt.exe", "-w", "new", "new-tab", "--title"]
    assert command[5] == WINDOWS_TERMINAL_TITLE
    assert command[command.index("--tabColor") + 1] == "#feb454"
    assert command.count("new-tab") == 1
    assert "--context-worker" in command


def test_terminal_command_omits_tab_color_when_unset():
    command = build_windows_terminal_command(["a.pdf"], terminal="wt.exe")

    assert "--tabColor" not in command


@pytest.mark.parametrize("platform", ["freebsd14", "openbsd7", "sunos5"])
def test_install_rejects_unsupported_platform(platform, monkeypatch, caplog):
    monkeypatch.setattr("hammerdown.integrations.is_windows", lambda: False)
    monkeypatch.setattr("hammerdown.integrations.is_macos", lambda: False)
    monkeypatch.setattr("hammerdown.integrations.is_linux", lambda: False)
    monkeypatch.setattr(sys, "platform", platform)

    with caplog.at_level("ERROR"):
        assert install() is False
        assert uninstall() is False

    assert "only available on Windows, macOS and Linux" in caplog.text
    assert platform in caplog.text
