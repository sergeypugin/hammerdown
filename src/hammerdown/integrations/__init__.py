from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from ..core.platform_utils import is_linux, is_macos, is_windows

logger = logging.getLogger("hammerdown")

UNSUPPORTED_PLATFORM_MESSAGE = (
    "File-manager integration is only available on Windows, macOS and Linux. "
    "The command-line interface still works on {platform}: run 'hammerdown <files>' or "
    "'hammerdown -m output.md <files>'. To add support for your environment, see CONTRIBUTING.md."
)


def _platform_is_supported() -> bool:
    return is_windows() or is_macos() or is_linux()


def _report_unsupported_platform() -> None:
    import sys

    logger.error(UNSUPPORTED_PLATFORM_MESSAGE.format(platform=sys.platform))


def _installed_command(home_dir: Path | None = None) -> tuple[Path, str]:
    home = home_dir or Path.home()
    if is_windows():
        app_dir = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Programs" / "hammerdown"
    else:
        app_dir = home / ".local" / "share" / "hammerdown"
    app_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        suffix = ".exe" if is_windows() else ""
        target = app_dir / f"hammerdown{suffix}"
        if Path(sys.executable).resolve() != target.resolve():
            shutil.move(sys.executable, target)
        return app_dir, str(target)

    target = app_dir / "hammerdown_runner.py"
    target.write_text(
        "import sys\n"
        "\n"
        "from hammerdown.cli import main\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )

    interpreter = sys.executable
    if is_windows():
        windowed = Path(interpreter).with_name("pythonw.exe")
        if windowed.is_file():
            interpreter = str(windowed)
    return app_dir, f'"{interpreter}" "{target}"'


def _install_unix(command: str) -> None:
    if is_macos():
        from .macos import _install_macos

        _install_macos(command)
    else:
        from .linux import _install_linux

        _install_linux(command)


def install() -> bool:
    if not _platform_is_supported():
        _report_unsupported_platform()
        return False
    try:
        _, command = _installed_command()
        if is_windows():
            from .windows import _install_windows

            _install_windows(command)
        else:
            _install_unix(command)
        logger.info("hammerdown installed successfully.")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Installation failed: %s", exc)
        return False


def uninstall() -> bool:
    if not _platform_is_supported():
        _report_unsupported_platform()
        return False
    try:
        if is_windows():
            from .windows import _uninstall_windows

            _uninstall_windows()
        elif is_macos():
            from .macos import _uninstall_macos

            _uninstall_macos()
        else:
            from .linux import _uninstall_linux

            _uninstall_linux()
        logger.info("hammerdown integration uninstalled")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Uninstallation failed: %s", exc)
        return False


__all__ = ["UNSUPPORTED_PLATFORM_MESSAGE", "install", "uninstall"]
