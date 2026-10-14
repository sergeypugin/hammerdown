from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from hammerdown import APP_DESCRIPTION, APP_NAME, __version__
from hammerdown.batch import run_batch
from hammerdown.file_selection import _select_files
from hammerdown.integrations import install as install_integration
from hammerdown.integrations import uninstall as uninstall_integration
from hammerdown.updater import update as update_application

logger = logging.getLogger("hammerdown")


def install() -> bool:
    return install_integration()


def uninstall() -> bool:
    return uninstall_integration()


def update() -> bool:
    return update_application(install_callback=install)


def main(argv: Sequence[str] | None = None) -> int:
    if os.name == "nt" and "--coordinator" in sys.argv:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
    )
    parser.add_argument("-v", "--version", action="version", version=f"{APP_NAME} {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    parser.add_argument("--update", action="store_true", help="Update hammerdown to the latest version")
    parser.add_argument("-i", "--in-place", "--in_place", action="store_true", help="Save output Markdown and images in the same directory as the input file")
    parser.add_argument("-w", "--overwrite", action="store_true", help="Overwrite input text file in-place instead of creating a copy")
    parser.add_argument("-s", "--skip-existing", "--skip_existing", action="store_true", help="Skip conversion if target markdown file already exists")
    parser.add_argument("-m", "--merge", metavar="OUTPUT_MD", help="Merge all converted Markdown documents into a single target Markdown file")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress routine conversion messages")
    parser.add_argument("--coordinator", action="store_true", help="Enable single-instance coordinator mode for batch invocation")
    parser.add_argument("files", nargs="*", help="Files to convert")
    args = parser.parse_args(argv)

    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.quiet:
        logger.setLevel(logging.ERROR)
    if args.install:
        return 0 if install() else 1
    if args.uninstall:
        return 0 if uninstall() else 1
    if args.update:
        return 0 if update() else 1

    raw_files = args.files or _select_files()
    if not raw_files:
        return 0

    args.files = raw_files
    return run_batch(args)


if __name__ == "__main__":
    sys.exit(main())
