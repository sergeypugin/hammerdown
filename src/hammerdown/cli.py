from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from typing import Sequence

from hammerdown import APP_DESCRIPTION, APP_NAME, SUPPORTED_EXTENSIONS, __version__
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


def normalize_filter_pattern(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def validate_filter_patterns(parser: argparse.ArgumentParser, values: Sequence[str], flag: str) -> list[str]:
    normalized: list[str] = []
    for value in values:
        pattern = normalize_filter_pattern(value)
        try:
            re.compile(pattern)
        except re.error as exc:
            parser.error(f"{flag} invalid regular expression {value!r}: {exc}")
        normalized.append(pattern)
    return normalized


def main(argv: Sequence[str] | None = None) -> int:
    actual_argv = list(argv) if argv is not None else sys.argv[1:]
    if os.name == "nt" and ("--coordinator" in actual_argv or "--right-click" in actual_argv):
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
        epilog=f"Supported formats: {', '.join(extension.lstrip('.') for extension in SUPPORTED_EXTENSIONS)}",
    )
    parser.add_argument("-v", "--version", action="version", version=f"{APP_NAME} {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    parser.add_argument("--update", action="store_true", help="Update hammerdown to the latest version")
    parser.add_argument(
        "-i",
        "--include",
        action="append",
        default=[],
        metavar="REGEX",
        help="Only process files whose normalized relative path matches REGEX; may be repeated",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        action="append",
        default=[],
        metavar="REGEX",
        help="Skip files whose normalized relative path matches REGEX; may be repeated",
    )
    parser.add_argument(
        "-w",
        "--overwrite",
        action="store_true",
        help="Overwrite plain-text source files in-place instead of creating a copy",
    )
    parser.add_argument(
        "-s",
        "--skip-existing",
        action="store_true",
        help="Skip conversion if the target Markdown file already exists",
    )
    parser.add_argument("-o", "--output-dir", action="append", metavar="DIR", help="Save Markdown and extracted images under DIR")
    parser.add_argument("-m", "--merge", metavar="OUTPUT_MD", help="Merge all converted Markdown documents into a single target Markdown file")
    parser.add_argument("--stdout", action="store_true", help="Write the merged Markdown document to stdout")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Show an approximate preflight and ask for confirmation before --stdout",
    )
    parser.add_argument("--coordinator", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--right-click", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("files", nargs="*", help="Files to convert")
    args = parser.parse_args(actual_argv)

    args.include = validate_filter_patterns(parser, args.include, "--include")
    args.exclude = validate_filter_patterns(parser, args.exclude, "--exclude")

    output_dirs = {os.path.normcase(os.path.abspath(path)) for path in args.output_dir or []}
    if len(output_dirs) > 1:
        parser.error("-o/--output-dir may be repeated only with the same directory")
    args.output_dir = next(iter(output_dirs), None)

    coordinator_mode = args.coordinator or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
    if args.output_dir and args.overwrite:
        parser.error("-w/--overwrite cannot be combined with -o/--output-dir")
    if args.overwrite and args.skip_existing:
        parser.error("-w/--overwrite cannot be combined with -s/--skip-existing")
    if args.output_dir and coordinator_mode:
        parser.error("-o/--output-dir cannot be used in coordinator mode")
    if args.confirm and not args.stdout:
        parser.error("--confirm can only be used with --stdout")
    if args.stdout and args.merge:
        parser.error("--stdout cannot be combined with --merge")
    if args.stdout and args.output_dir:
        parser.error("--stdout cannot be combined with --output-dir")
    if args.stdout and args.overwrite:
        parser.error("--stdout cannot be combined with --overwrite")
    if args.stdout and args.skip_existing:
        parser.error("--stdout cannot be combined with --skip-existing")
    if args.stdout and coordinator_mode:
        parser.error("--stdout cannot be used in coordinator mode")

    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
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
