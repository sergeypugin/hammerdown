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


def test_install_registers_hammerdown_submenus(windows_install) -> None:
    registry, _, _ = windows_install

    _install_windows(PYTHONW_COMMAND)

    expected = (
        ("convert", "Convert to Markdown", ""),
        ("merge", "Merge", " --merge-auto"),
        ("tree", "Tree", " --tree"),
        ("tree_all", "Tree with all formats", " --tree --all-formats"),
    )
    for root, argument in ((ALL_OBJECTS_ROOT, "%1"), (BACKGROUND_ROOT, "%V")):
        parent = root + r"\Hammerdown"
        assert parent in registry.values, sorted(registry.values)
        assert registry.values[parent]["MUIVerb"] == "Hammerdown"
        assert registry.values[parent]["Icon"].endswith("icon.ico")
        assert registry.values[parent]["Icon"].endswith("icon.ico")
        assert _direct_children(registry.created, parent + r"\shell") == [
            parent + chr(92) + "shell" + chr(92) + name for name, _, _ in expected
        ]
        for name, label, options in expected:
            item = parent + chr(92) + "shell" + chr(92) + name
            assert registry.values[item]["MUIVerb"] == label
            if root == ALL_OBJECTS_ROOT:
                assert registry.values[item]["MultiSelectModel"] == "Player"
            assert registry.values[item + r"\command"][""] == (
                f'{PYTHONW_COMMAND} --coordinator --right-click{options} "{argument}"'
            )

    assert not any(
        path.startswith(root + "\\") and path.rsplit("\\", 1)[-1] in {verb for verb, _ in VERBS}
        for path in registry.values
        for root in SHELL_ROOTS
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
    assert (sendto / "Hammerdown tree.cmd").read_text(encoding="utf-8") == (
        "@echo off\nchcp 65001 >nul\nhammerdown --coordinator --right-click --tree %*\n"
    )
    assert (sendto / "Hammerdown tree with all formats.cmd").read_text(encoding="utf-8") == (
        "@echo off\nchcp 65001 >nul\nhammerdown --coordinator --right-click --tree --all-formats %*\n"
    )
    assert {path.name for path in sendto.iterdir()} == {
        "Hammerdown.cmd",
        "Hammerdown and merge.cmd",
        "Hammerdown tree.cmd",
        "Hammerdown tree with all formats.cmd",
    }

def test_install_removes_stale_flat_entries_and_avoids_duplicate_submenus(windows_install) -> None:
    registry, _, _ = windows_install
    stale_names = tuple(verb for verb, _ in VERBS) + ("Convert to Markdown",)
    for root in SHELL_ROOTS:
        for name in stale_names:
            path = root + "\\" + name
            registry.seed(path, {"": "stale"})
            registry.seed(path + r"\command", {"": "stale-command"})
    registry.seed(r"Software\Classes\SystemFileAssociations\.pdf\shell\hammerdown", {"": "stale"})
    registry.seed(r"Software\Classes\.pdf\shell\hammerdown", {"": "stale"})

    _install_windows("hammerdown")
    first_submenus = {path for path in registry.values if "Hammerdown" in path and "shell" in path}
    _install_windows("hammerdown")
    second_submenus = {path for path in registry.values if "Hammerdown" in path and "shell" in path}

    action_keys = {path for path in second_submenus if "Hammerdown" + chr(92) + "shell" + chr(92) in path}
    assert len(action_keys) == 16
    for root in (ALL_OBJECTS_ROOT, BACKGROUND_ROOT):
        assert registry.values[root + r"\Hammerdown"]["MUIVerb"] == "Hammerdown"
    for root in SHELL_ROOTS:
        for name in stale_names:
            path = root + "\\" + name
            assert path not in registry.values
            assert path + r"\command" not in registry.values
    assert r"Software\Classes\SystemFileAssociations\.pdf\shell\hammerdown" not in registry.values
    assert r"Software\Classes\.pdf\shell\hammerdown" not in registry.values


def test_uninstall_removes_merge_entries_and_sendto(windows_install) -> None:
    registry, sendto, _ = windows_install

    _install_windows("hammerdown")
    legacy_paths = (
        DIRECTORY_ROOT + r"\hammerdown",
        DIRECTORY_ROOT + r"\hammerdown_merge",
        r"Software\Classes\SystemFileAssociations\.pdf\shell\hammerdown",
    )
    for path in legacy_paths:
        registry.seed(path, {"": "legacy"})
        registry.seed(path + r"\command", {"": "legacy-command"})

    _uninstall_windows()

    for path in legacy_paths:
        assert path not in registry.values
        assert path + r"\command" not in registry.values
        assert path in registry.deleted
    for root in (ALL_OBJECTS_ROOT, BACKGROUND_ROOT):
        key_path = root + r"\Hammerdown"
        assert key_path not in registry.values
        assert key_path in registry.deleted
    assert not (sendto / "Hammerdown and merge.cmd").exists()
    assert not any(sendto.iterdir())
