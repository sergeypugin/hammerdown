from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from .core.windows_console import attach_parent_console

attach_parent_console()


def _prepare_console_window() -> None:
    if os.name != "nt":
        return
    coordinator_present = False
    for token in sys.argv[1:]:
        if token == "--":
            break
        if token.casefold() == "--coordinator":
            coordinator_present = True
            break
    if not coordinator_present:
        return

    import ctypes

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)


_prepare_console_window()

from . import APP_NAME, __version__
from .batch import run_batch
from .core.file_selection import _select_files
from .core.filters import OrderedFilterValues
from .integrations import install as install_integration
from .integrations import uninstall as uninstall_integration
from .core.updater import update as update_application
from .utils import get_app_description

logger = logging.getLogger("hammerdown")


APP_DESCRIPTION = get_app_description()


class _FilterAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        value = str(values)
        current = getattr(namespace, self.dest, None)
        if not isinstance(current, OrderedFilterValues):
            current = OrderedFilterValues(current or ())
            setattr(namespace, self.dest, current)
        current.append(value)
        if current.filter_queue is None:
            current.filter_queue = []
        kind = "include" if self.dest == "include" else "exclude"
        current.filter_queue.append((kind, value))
        queue = getattr(namespace, "_filter_queue", None)
        if queue is None:
            queue = []
            setattr(namespace, "_filter_queue", queue)
        queue.append((kind, value))




def install() -> bool:
    return install_integration()


def uninstall() -> bool:
    return uninstall_integration()


def update() -> bool:
    return update_application(install_callback=install)


def validate_filter_patterns(parser: argparse.ArgumentParser, values: Sequence[str], flag: str) -> Sequence[str]:
    from .core.filters import compile_cli_filters

    try:
        if flag == "--include":
            compile_cli_filters(values, ())
        else:
            compile_cli_filters((), values)
    except (TypeError, ValueError) as exc:
        parser.error(f"{flag} invalid filter pattern: {exc}")
    return values


def _long_options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }


def _normalize_option_tokens(parser: argparse.ArgumentParser, argv: Sequence[str]) -> list[str]:
    option_aliases = {
        option.casefold(): option
        for action in parser._actions
        for option in action.option_strings
    }
    option_actions = {
        option.casefold(): action
        for action in parser._actions
        for option in action.option_strings
    }
    normalized_argv: list[str] = []
    options_ended = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if options_ended:
            normalized_argv.append(token)
            index += 1
            continue
        if token == "--":
            options_ended = True
            normalized_argv.append(token)
            index += 1
            continue

        option, separator, value = token.partition("=")
        option_key = option.casefold()
        canonical = option_aliases.get(option_key)
        compact = False
        if canonical is None and token.startswith("-") and not token.startswith("--") and len(token) > 2:
            short_option_key = token[:2].casefold()
            short_action = option_actions.get(short_option_key)
            if short_action is not None and short_action.nargs != 0:
                canonical = option_aliases[short_option_key] + token[2:]
                option_key = short_option_key
                compact = True
        if canonical is None:
            normalized_argv.append(token)
            index += 1
            continue

        if compact:
            normalized_argv.append(canonical)
        else:
            normalized_argv.append(f"{canonical}={value}" if separator else canonical)
        action = option_actions[option_key]
        if not separator and action.nargs != 0 and index + 1 < len(argv):
            next_token = argv[index + 1]
            if parser._parse_optional(next_token) is None:
                normalized_argv.append(next_token)
                index += 2
                continue
        index += 1
    return normalized_argv


def reject_single_dash_long_options(parser: argparse.ArgumentParser, argv: Sequence[str]) -> None:
    long_names = {
        option[2:].casefold(): option[2:]
        for option in _long_options(parser)
    }
    for token in argv:
        if token == "--":
            break
        if not token.startswith("-") or token.startswith("--") or token == "-":
            continue
        name = token[1:].split("=", 1)[0]
        if name.casefold() == "t":
            parser.error(f"unrecognized option {token!r}; did you mean '--tree'?")
        canonical_name = long_names.get(name.casefold())
        if canonical_name is not None:
            parser.error(f"unrecognized option {token!r}; did you mean '--{canonical_name}'?")


def reject_abbreviated_long_options(parser: argparse.ArgumentParser, argv: Sequence[str]) -> None:
    long_options = _long_options(parser)
    long_options_by_casefold = {option.casefold(): option for option in long_options}
    for token in argv:
        if token == "--":
            break
        if not token.startswith("--") or token == "--":
            continue
        option = token.split("=", 1)[0]
        option_key = option.casefold()
        if option_key in long_options_by_casefold:
            continue
        matches = sorted(candidate for candidate in long_options if candidate.casefold().startswith(option_key))
        if not matches:
            continue
        if len(matches) == 1:
            parser.error(f"unrecognized option {token!r}; did you mean '{matches[0]}'?")
        formatted = ", ".join(repr(candidate) for candidate in matches)
        parser.error(f"unrecognized option {token!r}; possible matches: {formatted}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


def _main(argv: Sequence[str] | None = None) -> int:
    actual_argv = list(argv) if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
        allow_abbrev=False,
    )
    parser.add_argument("-v", "--version", action="version", version=f"{APP_NAME} {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    parser.add_argument(
        "--update",
        "--upgrade",
        dest="update",
        action="store_true",
        help="Update hammerdown to the latest version",
    )
    parser.add_argument(
        "-i",
        "--include",
        action=_FilterAction,
        default=OrderedFilterValues(),
        metavar="PATTERN",
        help="Include files matching this GitWildMatch/pathspec pattern; may be repeated",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        action=_FilterAction,
        default=OrderedFilterValues(),
        metavar="PATTERN",
        help="Exclude files matching this GitWildMatch/pathspec pattern; may be repeated",
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
    parser.add_argument(
        "--include-gitignored",
        action="store_true",
        help="Include files ignored by Git when traversing directories",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Gather selected files into one Markdown tree document; may appear before, between, or after resources",
    )
    parser.add_argument(
        "--all-formats",
        action="store_true",
        help="In --tree mode, include supported binary documents such as PDF and DOCX",
    )
    parser.add_argument(
        "-m",
        "--merge",
        nargs="?",
        const="hammerdowned.md",
        metavar="OUTPUT_MD",
        help="Merge converted Markdown into OUTPUT_MD (default: hammerdowned.md); the argument after -m is always OUTPUT_MD, never an input resource",
    )
    parser.add_argument("--merge-auto", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stdout", action="store_true", help="Write the merged Markdown document to stdout")
    parser.add_argument("--tokens", action="store_true", help="Report source and estimated token counts without converting")
    parser.add_argument("--time", dest="report_time", action="store_true", help="Report conversion time estimates without converting")
    parser.add_argument("--dir-struct", action="store_true", help="Report the selected directory structure without converting")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Show a preflight estimate and ask for confirmation before --stdout",
    )
    parser.add_argument("--coordinator", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--context-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--right-click", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("files", nargs="*", help="Files to convert")
    normalized_argv = _normalize_option_tokens(parser, actual_argv)
    reject_single_dash_long_options(parser, normalized_argv)
    reject_abbreviated_long_options(parser, normalized_argv)
    args = parser.parse_intermixed_args(normalized_argv)
    filter_queue = getattr(args, "_filter_queue", None)
    if filter_queue:
        args.include.filter_queue = filter_queue
        args.exclude.filter_queue = filter_queue

    conversion_options_present = any(
        (
            args.include,
            args.exclude,
            args.overwrite,
            args.skip_existing,
            args.output_dir,
            args.tree,
            args.all_formats,
            args.merge,
            args.merge_auto,
            args.stdout,
            args.confirm,
            args.tokens,
            args.report_time,
            args.dir_struct,
            args.include_gitignored,
        )
    )
    if not args.files and actual_argv and (
        conversion_options_present or not (args.install or args.uninstall or args.update)
    ):
        parser.error("no input resources were provided")

    output_dir_values = args.output_dir or []
    output_dirs = {os.path.normcase(os.path.abspath(path)) for path in output_dir_values}
    if len(output_dirs) > 1:
        parser.error("-o/--output-dir may be repeated only with the same directory")
    args.output_dir = output_dir_values[0] if output_dir_values else None

    coordinator_mode = (
        (args.coordinator or os.environ.get("HAMMERDOWN_COORDINATOR") == "1")
        and not args.context_worker
    )

    tree_mode = getattr(args, "tree", False)
    if tree_mode:
        if args.output_dir:
            parser.error("--tree cannot be combined with -o/--output-dir")
        if args.overwrite:
            parser.error("--tree cannot be combined with -w/--overwrite")

    all_formats = getattr(args, "all_formats", False)
    if all_formats and not tree_mode and not args.dir_struct:
        parser.error("--all-formats can only be used with --tree or --dir-struct")

    if args.output_dir and args.overwrite:
        parser.error("-w/--overwrite cannot be combined with -o/--output-dir")
    if args.overwrite and args.skip_existing:
        parser.error("-w/--overwrite cannot be combined with -s/--skip-existing")
    if args.output_dir and coordinator_mode:
        parser.error("-o/--output-dir cannot be used in coordinator mode")
    if args.confirm and not args.stdout:
        parser.error("--confirm can only be used with --stdout")
    report_mode = args.tokens or args.report_time or args.dir_struct
    if args.tree and args.dir_struct:
        parser.error("--tree cannot be combined with --dir-struct")
    if report_mode and args.merge:
        parser.error("report modes cannot be combined with --merge")
    if report_mode and args.merge_auto:
        parser.error("report modes cannot be combined with --merge-auto")
    if report_mode and args.stdout:
        parser.error("report modes cannot be combined with --stdout")
    if report_mode and args.output_dir:
        parser.error("report modes cannot be combined with --output-dir")
    if report_mode and args.overwrite:
        parser.error("report modes cannot be combined with --overwrite")
    if report_mode and args.skip_existing:
        parser.error("report modes cannot be combined with --skip-existing")
    # --merge-auto mutual exclusions
    if args.merge_auto and args.merge:
        parser.error("--merge-auto cannot be combined with --merge")
    if args.merge_auto and args.output_dir:
        parser.error("--merge-auto cannot be combined with --output-dir")
    if args.merge_auto and args.overwrite:
        parser.error("--merge-auto cannot be combined with --overwrite")
    if args.merge_auto and args.skip_existing:
        parser.error("--merge-auto cannot be combined with --skip-existing")
    if args.merge_auto and args.stdout:
        parser.error("--merge-auto cannot be combined with --stdout")

    if args.merge and args.overwrite:
        parser.error("--merge cannot be combined with --overwrite")
    if args.merge and args.output_dir:
        parser.error("--merge cannot be combined with --output-dir")
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

    # All flag conflicts are settled before validating paths/patterns or starting acquisition.
    args.include = validate_filter_patterns(parser, args.include, "--include")
    args.exclude = validate_filter_patterns(parser, args.exclude, "--exclude")

    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.install:
        return 0 if install() else 1
    if args.uninstall:
        return 0 if uninstall() else 1
    if args.update:
        return 0 if update() else 1

    if not actual_argv:
        # APP_DESCRIPTION contains description + supported formats + help hint (no 'hammerdown' prefix)
        # Print 'hammerdown version' in yellow, then description
        from .ui.ui_constants import COLOR_BOLD, COLOR_RESET
        name_version_colored = f"{COLOR_BOLD}\033[38;2;254;180;84mhammerdown {__version__}{COLOR_RESET}"
        print(f"{name_version_colored} is {APP_DESCRIPTION}", file=sys.stderr)
        return 0

    raw_files = args.files
    args.files = raw_files
    return run_batch(args)


if __name__ == "__main__":
    sys.exit(main())
