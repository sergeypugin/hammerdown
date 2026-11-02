from __future__ import annotations

from pathlib import Path

from hammerdown.integrations.linux import _find_icon_pngs, _install_linux, _uninstall_linux


HICOLOR_ICON_NAMES = (
    "hammerdown.png",
    "hammerdown_merge.png",
    "hammerdown_tree.png",
    "hammerdown_tree_all.png",
)
ICON_DIRECTORY = Path(".local") / "share" / "icons" / "hicolor" / "256x256" / "apps"


def test_linux_install_uninstall_cleans_all_hicolor_icons_and_keeps_unrelated_file(
    tmp_path: Path,
) -> None:
    icon_directory = tmp_path / ICON_DIRECTORY
    icon_directory.mkdir(parents=True)
    unrelated_icon = icon_directory / "unrelated.png"
    unrelated_icon.write_bytes(b"user icon")

    _install_linux("python3 -m hammerdown", home_dir=tmp_path)

    installed_icons = [icon_directory / name for name in HICOLOR_ICON_NAMES]
    assert all(path.is_file() for path in installed_icons)
    resolved_sources = _find_icon_pngs()
    assert all(
        installed.read_bytes() == resolved_sources[name].read_bytes()
        for name, installed in zip(HICOLOR_ICON_NAMES, installed_icons)
    )

    _uninstall_linux(home_dir=tmp_path)

    assert all(not path.exists() for path in installed_icons)
    assert unrelated_icon.read_bytes() == b"user icon"
    assert not (tmp_path / ".local" / "bin" / "hammerdown").exists()
    assert not (tmp_path / ".local" / "share" / "applications" / "hammerdown.desktop").exists()
