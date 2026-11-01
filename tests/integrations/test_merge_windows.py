from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from hammerdown.integrations.windows import _install_windows, _uninstall_windows

MERGE_ICON_NAMES = {"icon_merge_darkred.ico", "icon_merge_orange.ico"}

VERBS = (
    ("hammerdown", "Hammerdown"),
    ("hammerdown_merge", "Hammerdown and merge"),
    ("hammerdown_tree", "Hammerdown tree"),
    ("hammerdown_tree_all", "Hammerdown tree with all formats"),
)

ALL_OBJECTS_ROOT = r"Software\Classes\AllFilesystemObjects\shell"
DIRECTORY_ROOT = r"Software\Classes\Directory\shell"
BACKGROUND_ROOT = r"Software\Classes\Directory\Background\shell"
SHELL_ROOTS = (ALL_OBJECTS_ROOT, DIRECTORY_ROOT, BACKGROUND_ROOT)

PYTHONW_COMMAND = '"C:/Python/pythonw.exe" "C:/Users/me/AppData/Local/Programs/hammerdown/hammerdown_runner.py"'


class _KeyHandle:
    def __init__(self, registry: "FakeRegistry", path: str) -> None:
        self.registry = registry
        self.path = path

    def __enter__(self) -> "_KeyHandle":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}
        self.created: list[str] = []
        self.deleted: list[str] = []

    def seed(self, path: str, values: dict[str, str]) -> None:
        self.values[path] = dict(values)

    def create_key(self, root: object, subkey: str) -> _KeyHandle:
        self.created.append(subkey)
        self.values.setdefault(subkey, {})
        return _KeyHandle(self, subkey)

    def set_value(self, key: _KeyHandle, value_name: str, reserved: int, type_: int, value: str) -> None:
        self.values[key.path][value_name] = value

    def delete_value(self, key: _KeyHandle, value_name: str) -> None:
        self.values[key.path].pop(value_name, None)

    def open_key(self, root: object, subkey: str, *args: object) -> _KeyHandle:
        if subkey not in self.values:
            raise FileNotFoundError(subkey)
        return _KeyHandle(self, subkey)

    def enum_key(self, key: _KeyHandle, index: int) -> str:
        prefix = key.path + "\\"
        children = sorted(
            path[len(prefix):]
            for path in self.values
            if path.startswith(prefix) and "\\" not in path[len(prefix):]
        )
        if index >= len(children):
            raise OSError("no more subkeys")
        return children[index]

    def delete_key(self, root: object, path: str) -> None:
        if path not in self.values:
            raise FileNotFoundError(path)
        del self.values[path]
        self.deleted.append(path)


def _direct_children(paths: list[str], root: str) -> list[str]:
    prefix = root + "\\"
    return [path for path in paths if path.startswith(prefix) and "\\" not in path[len(prefix):]]


@pytest.fixture
def windows_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeRegistry, Path, Path]:
    registry = FakeRegistry()
    fake_winreg = types.ModuleType("winreg")
    setattr(fake_winreg, "HKEY_CURRENT_USER", "HKEY_CURRENT_USER")
    setattr(fake_winreg, "REG_SZ", 1)
    setattr(fake_winreg, "KEY_READ", 1)
    setattr(fake_winreg, "KEY_WRITE", 2)
    setattr(fake_winreg, "CreateKey", registry.create_key)
    setattr(fake_winreg, "SetValueEx", registry.set_value)
    setattr(fake_winreg, "DeleteValue", registry.delete_value)
    setattr(fake_winreg, "OpenKey", registry.open_key)
    setattr(fake_winreg, "EnumKey", registry.enum_key)
    setattr(fake_winreg, "DeleteKey", registry.delete_key)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    monkeypatch.setattr(sys, "frozen", False, raising=False)

    roaming = tmp_path / "AppData" / "Roaming"
    local = tmp_path / "AppData" / "Local"
    sendto = roaming / "Microsoft" / "Windows" / "SendTo"
    sendto.mkdir(parents=True)
    (local / "Programs" / "hammerdown").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    return registry, sendto, local


def test_install_registers_four_verbs_in_order(windows_install) -> None:
    registry, _, _ = windows_install

    _install_windows("hammerdown")

    for root in (ALL_OBJECTS_ROOT, BACKGROUND_ROOT):
        created = _direct_children(registry.created, root)
        expected = [f"{root}\\{verb}" for verb, _ in VERBS]
        assert created == expected
        assert created == sorted(created)
        assert [registry.values[path][""] for path in created] == [label for _, label in VERBS]


def test_install_registers_merge_command_for_files_and_folders(windows_install) -> None:
    registry, _, _ = windows_install

    _install_windows(PYTHONW_COMMAND)

    for root in (ALL_OBJECTS_ROOT, DIRECTORY_ROOT):
        key_path = f"{root}\\hammerdown_merge"
        values = registry.values[key_path]
        assert values[""] == "Hammerdown and merge"
        assert values["MultiSelectModel"] == "Player"
        assert Path(values["Icon"]).name in MERGE_ICON_NAMES
        assert Path(values["Icon"]).is_file()
        assert registry.values[key_path + r"\command"][""] == (
            f'{PYTHONW_COMMAND} --coordinator --right-click --merge-auto "%1"'
        )


def test_install_registers_merge_command_for_directory_background(windows_install) -> None:
    registry, _, _ = windows_install

    _install_windows("hammerdown")

    key_path = f"{BACKGROUND_ROOT}\\hammerdown_merge"
    values = registry.values[key_path]
    assert values[""] == "Hammerdown and merge"
    assert Path(values["Icon"]).name in MERGE_ICON_NAMES
    assert registry.values[key_path + r"\command"][""] == (
        'hammerdown --coordinator --right-click --merge-auto "%V"'
    )


def test_install_creates_merge_sendto_shortcut(windows_install) -> None:
    registry, sendto, _ = windows_install
    (sendto / "Hammer down and merge.cmd").write_text("legacy", encoding="utf-8")

    _install_windows("hammerdown")

    merge_script = sendto / "Hammerdown and merge.cmd"
    assert merge_script.is_file()
    assert merge_script.read_text(encoding="utf-8") == (
        "@echo off\nchcp 65001 >nul\nhammerdown --coordinator --right-click --merge-auto %*\n"
    )
    assert not (sendto / "Hammer down and merge.cmd").exists()
    assert {path.name for path in sendto.iterdir()} == {
        "Hammerdown.cmd",
        "Hammerdown and merge.cmd",
        "Hammerdown tree.cmd",
        "Hammerdown tree with all formats.cmd",
    }


@pytest.mark.parametrize("root", SHELL_ROOTS)
def test_install_replaces_stale_merge_entries(windows_install, root: str) -> None:
    registry, _, _ = windows_install
    key_path = f"{root}\\hammerdown_merge"
    registry.seed(key_path, {"": "Old merge", "Icon": "old.ico", "MultiSelectModel": "Document"})
    registry.seed(key_path + r"\command", {"": "old-command"})

    _install_windows("hammerdown")

    values = registry.values[key_path]
    assert values[""] == "Hammerdown and merge"
    assert Path(values["Icon"]).name in MERGE_ICON_NAMES
    if root == BACKGROUND_ROOT:
        assert "MultiSelectModel" not in values
        expected_command = 'hammerdown --coordinator --right-click --merge-auto "%V"'
    else:
        assert values["MultiSelectModel"] == "Player"
        expected_command = 'hammerdown --coordinator --right-click --merge-auto "%1"'
    assert registry.values[key_path + r"\command"][""] == expected_command


def test_uninstall_removes_merge_entries_and_sendto(windows_install) -> None:
    registry, sendto, _ = windows_install

    _install_windows("hammerdown")
    _uninstall_windows()

    for root in SHELL_ROOTS:
        for verb, _ in VERBS:
            key_path = f"{root}\\{verb}"
            assert key_path not in registry.values
            assert key_path + r"\command" not in registry.values
            assert key_path in registry.deleted
    assert not (sendto / "Hammerdown and merge.cmd").exists()
    assert not any(sendto.iterdir())
