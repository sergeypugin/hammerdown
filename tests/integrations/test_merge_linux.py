from __future__ import annotations

from pathlib import Path

import pytest

from hammerdown.integrations.linux import (
    _desktop_file_content,
    _find_icon_pngs,
    _install_linux,
    _kde_servicemenu_content,
    _uninstall_linux,
)

ENTRY_NAMES = (
    "Hammerdown",
    "Hammerdown and merge",
    "Hammerdown tree",
    "Hammerdown tree with all formats",
)

MERGE_SOURCE_NAMES = {"icon_merge_darkred.png", "icon_merge_orange.png", "icon.png"}

LAUNCHER_COMMAND = "python3 -m hammerdown"

SCRIPT_DIRS = {
    "nautilus": Path(".local") / "share" / "nautilus" / "scripts",
    "nemo": Path(".local") / "share" / "nemo" / "scripts",
    "caja": Path(".config") / "caja" / "scripts",
}

KDE_DESKTOP_FILES = {
    "kde6": Path(".local") / "share" / "kio" / "servicemenus" / "hammerdown.desktop",
    "kde5": Path(".local") / "share" / "kservices5" / "ServiceMenus" / "hammerdown.desktop",
}

SYSTEM_DESKTOP_FILE = Path(".local") / "share" / "applications" / "hammerdown.desktop"

ICON_DIR = Path(".local") / "share" / "icons" / "hicolor" / "256x256" / "apps"


def _parse_desktop(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        if current is None:
            continue
        key, separator, value = line.partition("=")
        if separator:
            current[key] = value
    return sections


def _action_keys(sections: dict[str, dict[str, str]]) -> list[str]:
    actions = sections["Desktop Entry"]["Actions"].rstrip(";").split(";")
    return [f"Desktop Action {action}" for action in actions]


def _entries_in_order(sections: dict[str, dict[str, str]]) -> list[str]:
    return [sections["Desktop Entry"]["Name"], *[sections[key]["Name"] for key in _action_keys(sections)]]


def _exec_command(sections: dict[str, dict[str, str]], section: str = "Desktop Entry") -> str:
    exec_line = sections[section]["Exec"]
    suffix = " %F"
    assert exec_line.endswith(suffix)
    return exec_line[: -len(suffix)]


@pytest.fixture
def installed_home(tmp_path: Path) -> Path:
    _install_linux(LAUNCHER_COMMAND, home_dir=tmp_path)
    return tmp_path


def test_desktop_entry_lists_merge_strictly_second() -> None:
    sections = _parse_desktop(_desktop_file_content('"hammerdown"'))

    assert sections["Desktop Entry"]["Actions"] == "Merge;Tree;TreeAll;"
    assert list(sections) == [
        "Desktop Entry",
        "Desktop Action Merge",
        "Desktop Action Tree",
        "Desktop Action TreeAll",
    ]
    assert _action_keys(sections) == [key for key in sections if key != "Desktop Entry"]
    assert _entries_in_order(sections) == list(ENTRY_NAMES)


def test_desktop_merge_action_uses_merge_auto_command() -> None:
    sections = _parse_desktop(_desktop_file_content('"hammerdown"'))
    merge_action = sections["Desktop Action Merge"]

    assert merge_action["Name"] == "Hammerdown and merge"
    assert merge_action["Exec"] == '"hammerdown" --coordinator --right-click --merge-auto %F'
    assert merge_action["Icon"] == "hammerdown_merge"


def test_kde_servicemenu_lists_merge_strictly_second() -> None:
    sections = _parse_desktop(_kde_servicemenu_content('"hammerdown"'))

    assert sections["Desktop Entry"]["Actions"] == (
        "HammerDown;HammerDownMerge;HammerDownTree;HammerDownTreeAll;"
    )
    assert list(sections) == [
        "Desktop Entry",
        "Desktop Action HammerDown",
        "Desktop Action HammerDownMerge",
        "Desktop Action HammerDownTree",
        "Desktop Action HammerDownTreeAll",
    ]
    assert _action_keys(sections) == [key for key in sections if key != "Desktop Entry"]
    assert [sections[key]["Name"] for key in sections if key != "Desktop Entry"] == list(ENTRY_NAMES)


def test_kde_merge_action_uses_merge_auto_command() -> None:
    sections = _parse_desktop(_kde_servicemenu_content('"hammerdown"'))
    merge_action = sections["Desktop Action HammerDownMerge"]

    assert merge_action["Name"] == "Hammerdown and merge"
    assert merge_action["Exec"] == '"hammerdown" --coordinator --right-click --merge-auto %F'
    assert merge_action["Icon"] == "hammerdown_merge"


def test_merge_icon_mapping_resolves_to_existing_fallback() -> None:
    resolved = _find_icon_pngs()

    assert set(resolved) >= {
        "hammerdown.png",
        "hammerdown_merge.png",
        "hammerdown_tree.png",
        "hammerdown_tree_all.png",
    }
    merge_source = resolved["hammerdown_merge.png"]
    assert merge_source.is_file()
    assert merge_source.name in MERGE_SOURCE_NAMES

    repo_assets = Path(__file__).resolve().parents[2] / "assets"
    assert (repo_assets / "icon.png").is_file()


def test_install_writes_merge_action_to_desktop_file(installed_home: Path) -> None:
    sections = _parse_desktop((installed_home / SYSTEM_DESKTOP_FILE).read_text(encoding="utf-8"))
    exec_cmd = _exec_command(sections)
    merge_action = sections["Desktop Action Merge"]

    assert sections["Desktop Entry"]["Actions"] == "Merge;Tree;TreeAll;"
    assert _entries_in_order(sections) == list(ENTRY_NAMES)
    assert merge_action["Exec"] == f"{exec_cmd} --coordinator --right-click --merge-auto %F"


@pytest.mark.parametrize("kde_file", KDE_DESKTOP_FILES.values(), ids=KDE_DESKTOP_FILES.keys())
def test_install_writes_merge_action_to_kde_files(installed_home: Path, kde_file: Path) -> None:
    sections = _parse_desktop((installed_home / kde_file).read_text(encoding="utf-8"))
    exec_cmd = _exec_command(sections, "Desktop Action HammerDown")

    assert sections["Desktop Entry"]["Actions"] == (
        "HammerDown;HammerDownMerge;HammerDownTree;HammerDownTreeAll;"
    )
    assert [sections[key]["Name"] for key in sections if key != "Desktop Entry"] == list(ENTRY_NAMES)
    assert sections["Desktop Action HammerDownMerge"]["Exec"] == (
        f"{exec_cmd} --coordinator --right-click --merge-auto %F"
    )


@pytest.mark.parametrize("manager", SCRIPT_DIRS, ids=SCRIPT_DIRS.keys())
def test_install_writes_merge_script_for_each_file_manager(installed_home: Path, manager: str) -> None:
    launcher = installed_home / ".local" / "bin" / "hammerdown"
    scripts_dir = installed_home / SCRIPT_DIRS[manager]

    assert {path.name for path in scripts_dir.iterdir()} == set(ENTRY_NAMES)

    merge_script = scripts_dir / "Hammerdown and merge"
    assert merge_script.read_text(encoding="utf-8") == (
        f'exec "{launcher}" --coordinator --right-click --merge-auto "$@"\n'
    )


def test_install_copies_merge_icon_from_existing_asset(installed_home: Path) -> None:
    source = _find_icon_pngs()["hammerdown_merge.png"]

    assert source.is_file()
    assert source.name in MERGE_SOURCE_NAMES
    assert (installed_home / ICON_DIR / "hammerdown_merge.png").read_bytes() == source.read_bytes()
    assert (
        installed_home / ".local" / "share" / "hammerdown" / "hammerdown_merge.png"
    ).read_bytes() == source.read_bytes()


def test_uninstall_removes_merge_scripts_and_icon(installed_home: Path) -> None:
    for relative in SCRIPT_DIRS.values():
        (installed_home / relative / "unrelated.txt").write_text("keep", encoding="utf-8")
    unrelated_icon = installed_home / ICON_DIR / "unrelated.png"
    unrelated_icon.write_text("keep", encoding="utf-8")

    _uninstall_linux(home_dir=installed_home)

    for relative in SCRIPT_DIRS.values():
        remaining = {path.name for path in (installed_home / relative).iterdir()}
        assert remaining == {"unrelated.txt"}
        assert not (installed_home / relative / "Hammerdown and merge").exists()

    assert not (installed_home / ICON_DIR / "hammerdown_merge.png").exists()
    assert not (installed_home / ICON_DIR / "hammerdown.png").exists()
    assert unrelated_icon.is_file()
    assert not (installed_home / SYSTEM_DESKTOP_FILE).exists()
    for kde_file in KDE_DESKTOP_FILES.values():
        assert not (installed_home / kde_file).exists()
    assert not (installed_home / ".local" / "share" / "hammerdown").exists()


def test_uninstall_removes_stale_merge_scripts_without_full_install(tmp_path: Path) -> None:
    for relative in SCRIPT_DIRS.values():
        scripts_dir = tmp_path / relative
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "Hammerdown and merge").write_text("stale", encoding="utf-8")

    _uninstall_linux(home_dir=tmp_path)

    for relative in SCRIPT_DIRS.values():
        assert not (tmp_path / relative / "Hammerdown and merge").exists()
