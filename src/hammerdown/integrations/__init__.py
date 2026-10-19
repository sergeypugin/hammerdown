from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from hammerdown.platform_utils import is_macos, is_windows

logger = logging.getLogger("hammerdown")


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
        "import os\n"
        "import sys\n"
        "\n"
        "if os.name == 'nt' and ('--coordinator' in sys.argv[1:] or '--right-click' in sys.argv[1:]):\n"
        "    import ctypes\n"
        "    hwnd = ctypes.windll.kernel32.GetConsoleWindow()\n"
        "    if hwnd:\n"
        "        if '--coordinator' in sys.argv[1:]:\n"
        "            ctypes.windll.user32.ShowWindow(hwnd, 0)\n"
        "        else:\n"
        "            ctypes.windll.user32.ShowWindow(hwnd, 5)\n"
        "            ctypes.windll.user32.SetForegroundWindow(hwnd)\n"
        "\n"
        "from hammerdown.cli import main\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )

    interpreter = sys.executable
    if is_windows() and interpreter:
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


__all__ = ["install", "uninstall"]
