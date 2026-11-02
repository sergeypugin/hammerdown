from __future__ import annotations

import plistlib
import shlex
from pathlib import Path
from typing import Any

import pytest

from hammerdown.integrations.macos import _install_macos, _uninstall_macos

SERVICES_RELATIVE = Path("Library") / "Services"

WORKFLOWS = (
    ("Hammerdown", "Hammerdown", "com.hammerdown.quickaction.hammerdown", ()),
    (
        "Hammerdown and merge",
        "Hammerdown and merge",
        "com.hammerdown.quickaction.hammerdown_and_merge",
        ("--merge-auto",),
    ),
    ("Hammerdown tree", "Hammerdown tree", "com.hammerdown.quickaction.hammerdown_tree", ("--tree",)),
    (
        "Hammerdown tree with all formats",
        "Hammerdown tree with all formats",
        "com.hammerdown.quickaction.hammerdown_tree_with_all_formats",
        ("--tree", "--all-formats"),
    ),
)


def _load_plist(path: Path) -> dict[str, Any]:
    with open(path, "rb") as fp:
        data = plistlib.load(fp)
    assert isinstance(data, dict)
    return data


def _workflow_command(workflow_dir: Path) -> str:
    document = _load_plist(workflow_dir / "Contents" / "document.wflow")
    action = document["actions"][0]["action"]
    command = action["ActionParameters"]["COMMAND_STRING"]
    assert isinstance(command, str)
    return command


def _expected_command(launcher: Path, flags: tuple[str, ...]) -> str:
    target = shlex.quote(str(launcher))
    suffix = f" {' '.join(flags)}" if flags else ""
    return f'exec {target}{suffix} "$@"'


@pytest.fixture
def macos_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_install_creates_four_workflows_with_expected_names(macos_home: Path) -> None:
    _install_macos("python3 -m hammerdown", home_dir=macos_home)

    services_dir = macos_home / SERVICES_RELATIVE
    assert sorted(path.name for path in services_dir.glob("*.workflow")) == sorted(
        f"{name}.workflow" for name, _, _, _ in WORKFLOWS
    )


def test_install_sets_menu_titles_and_identifiers(macos_home: Path) -> None:
    _install_macos("python3 -m hammerdown", home_dir=macos_home)

    services_dir = macos_home / SERVICES_RELATIVE
    launcher = macos_home / ".local" / "bin" / "hammerdown"
    for name, menu_title, identifier, flags in WORKFLOWS:
        workflow_dir = services_dir / f"{name}.workflow"
        info = _load_plist(workflow_dir / "Contents" / "Info.plist")
        assert info["CFBundleName"] == menu_title
        assert info["CFBundleIdentifier"] == identifier

        services = info["NSServices"]
        assert len(services) == 1
        service = services[0]
        assert service["NSMenuItem"]["default"] == menu_title
        assert service["NSMessage"] == "runWorkflowAsService"
        assert service["NSRequiredContext"]["NSApplicationIdentifier"] == "com.apple.finder"
        assert "public.item" in service["NSSendFileTypes"]

        assert _workflow_command(workflow_dir) == _expected_command(launcher, flags)


def test_merge_workflow_runs_merge_auto_for_all_selected_files(macos_home: Path) -> None:
    _install_macos("python3 -m hammerdown", home_dir=macos_home)

    workflow_dir = macos_home / SERVICES_RELATIVE / "Hammerdown and merge.workflow"
    command = _workflow_command(workflow_dir)

    launcher = macos_home / ".local" / "bin" / "hammerdown"
    assert command == _expected_command(launcher, ("--merge-auto",))
    assert command.endswith('--merge-auto "$@"')
    assert '--tree' not in command
    assert '--all-formats' not in command
    assert '--coordinator' not in command
    assert '--right-click' not in command


def test_install_replaces_stale_merge_workflow(macos_home: Path) -> None:
    workflow_dir = macos_home / SERVICES_RELATIVE / "Hammerdown and merge.workflow"
    contents_dir = workflow_dir / "Contents"
    contents_dir.mkdir(parents=True)
    with open(contents_dir / "Info.plist", "wb") as fp:
        plistlib.dump({"CFBundleName": "Hammer down and merge", "NSServices": []}, fp, fmt=plistlib.FMT_XML)
    with open(contents_dir / "document.wflow", "wb") as fp:
        plistlib.dump({"actions": []}, fp, fmt=plistlib.FMT_XML)

    _install_macos("python3 -m hammerdown", home_dir=macos_home)

    info = _load_plist(contents_dir / "Info.plist")
    assert info["CFBundleName"] == "Hammerdown and merge"
    assert info["CFBundleIdentifier"] == "com.hammerdown.quickaction.hammerdown_and_merge"
    assert info["NSServices"][0]["NSMenuItem"]["default"] == "Hammerdown and merge"
    assert _workflow_command(workflow_dir).endswith('--merge-auto "$@"')


def test_merge_workflow_quotes_launcher_with_spaces(tmp_path: Path) -> None:
    home = tmp_path / "Home Folder"
    home.mkdir()

    _install_macos("python3 -m hammerdown", home_dir=home)

    launcher = home / ".local" / "bin" / "hammerdown"
    command = _workflow_command(home / SERVICES_RELATIVE / "Hammerdown and merge.workflow")
    assert command == f'exec {shlex.quote(str(launcher))} --merge-auto "$@"'


def test_uninstall_removes_all_workflows_including_merge(macos_home: Path) -> None:
    _install_macos("python3 -m hammerdown", home_dir=macos_home)

    services_dir = macos_home / SERVICES_RELATIVE
    for name, _, _, _ in WORKFLOWS:
        assert (services_dir / f"{name}.workflow").is_dir()
    assert (services_dir / "Hammerdown and merge.workflow").is_dir()

    _uninstall_macos(home_dir=macos_home)

    assert not (services_dir / "Hammerdown and merge.workflow").exists()
    assert not any(services_dir.glob("*.workflow"))
    assert not (macos_home / ".local" / "bin" / "hammerdown").exists()


def test_uninstall_is_idempotent(macos_home: Path) -> None:
    _uninstall_macos(home_dir=macos_home)

    assert not (macos_home / SERVICES_RELATIVE / "Hammerdown and merge.workflow").exists()
