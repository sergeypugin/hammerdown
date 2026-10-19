from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from hammerdown.core import (
    TEXT_EXTENSIONS,
    convert_file,
    get_conversion_estimate_seconds,
)
from hammerdown.discovery import expand_paths, output_paths as compute_output_paths
from hammerdown.ipc import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.merge import (
    append_merged_document,
    initialize_merge_file,
    merge_asset_paths,
    merge_root_for_inputs,
    render_merged_markdown,
)
from hammerdown.batch_ui import BatchUI
from hammerdown.stdout_mode import confirm_stdout, run_stdout_conversion
from hammerdown.utils import format_duration, normalize_path

logger = logging.getLogger("hammerdown")


def _ensure_console_window() -> None:
    """Show the current console or allocate one for a windowed launcher."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    hwnd = kernel32.GetConsoleWindow()
    if not hwnd:
        if not kernel32.AllocConsole():
            return
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
        for name in ("", "hammerdown"):
            for handler in logging.getLogger(name).handlers:
                if isinstance(handler, logging.StreamHandler) and getattr(handler, "stream", None) is None:
                    handler.setStream(sys.stderr)
        hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 5)
        user32.SetForegroundWindow(hwnd)


def run_batch(args: argparse.Namespace) -> int:
    raw_files = args.files
    merge_requested = getattr(args, "merge", None)
    if merge_requested and getattr(args, "overwrite", False):
        logger.error("--merge cannot be combined with --overwrite")
        return 1
    if merge_requested and getattr(args, "output_dir", None):
        logger.error("--merge cannot be combined with --output-dir")
        return 1
    if not raw_files:
        logger.info("No supported documents found to convert")
        return 0

    output_dir = getattr(args, "output_dir", None)
    output_root = Path(output_dir).resolve() if output_dir else None
    if output_root is not None and output_root.exists() and not output_root.is_dir():
        logger.error("output directory path is not a directory: %s", output_root)
        return 1

    include_patterns = [re.compile(pattern) for pattern in getattr(args, "include", [])]
    exclude_patterns = [re.compile(pattern) for pattern in getattr(args, "exclude", [])]
    targets = expand_paths(
        raw_files,
        excluded_dir=output_root,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )
    if not targets:
        logger.info("No supported documents found to convert")
        return 0

    targets.sort(key=lambda item: item[0].lower())
    files = [path for path, error in targets if error is None]
    ui_files = [path for path, _ in targets]
    estimates = [
        get_conversion_estimate_seconds(Path(path)) if error is None else None
        for path, error in targets
    ]

    if getattr(args, "stdout", False):
        initial_errors = [(path, error) for path, error in targets if error is not None]
        for path, error in initial_errors:
            print(f"[!] {Path(path).name}: {error}", file=sys.stderr)
        file_estimates = [estimate for (_, error), estimate in zip(targets, estimates) if error is None]
        if getattr(args, "confirm", False) and files and not confirm_stdout(files, file_estimates):
            return 1
        if not files:
            return 1 if initial_errors else 0
        conversion_status = run_stdout_conversion(files, raw_files)
        return 1 if initial_errors or conversion_status else 0

    use_ipc = getattr(args, "coordinator", False) or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
    options = {
        "overwrite": getattr(args, "overwrite", False),
        "skip_existing": getattr(args, "skip_existing", False),
    }

    if use_ipc and files and not any(error for _, error in targets) and try_delegate_to_coordinator(files, options):
        logger.info("Delegated %d files to active hammerdown coordinator", len(files))
        return 0

    coordinator = IPCCoordinator() if use_ipc else None
    if coordinator and coordinator.start():
        if os.name == "nt":
            _ensure_console_window()

        initial_errors = [target for target in targets if target[1] is not None]
        collected_files = coordinator.collect_files(files, assembly_timeout=0.35)
        targets = expand_paths(
            [*raw_files, *collected_files],
            excluded_dir=output_root,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        targets.extend(
            target for target in initial_errors if target not in targets
        )
        targets.sort(key=lambda item: item[0].lower())
        files = [path for path, error in targets if error is None]
        ui_files = [path for path, _ in targets]
        estimates = [
            get_conversion_estimate_seconds(Path(path)) if error is None else None
            for path, error in targets
        ]
        output_path_inputs = [*raw_files, *collected_files]
    elif use_ipc:
        return 0
    else:
        output_path_inputs = raw_files

    merge_target = Path(normalize_path(merge_requested)) if merge_requested else None
    merge_sources = [path for path, error in targets if error is None]
    if merge_target is not None and any(Path(path).resolve() == merge_target.resolve() for path in merge_sources):
        logger.error("merge target cannot be one of the source files: %s", merge_target)
        if coordinator:
            coordinator.stop()
        return 1

    merge_root = (
        merge_root_for_inputs(output_path_inputs, [Path(path) for path in merge_sources])
        if merge_target is not None
        else None
    )
    merge_skipped = bool(merge_target is not None and args.skip_existing and merge_target.exists())

    try:
        if merge_target is not None:
            target_paths = [merge_target] * len(targets)
        elif output_root is not None:
            target_paths = compute_output_paths(output_path_inputs, targets, output_root)
        else:
            target_paths = [
                Path(path).parent / f"hm_{Path(path).stem}_{Path(path).suffix.lower().lstrip('.')}.md"
                for path, _ in targets
            ]
    except ValueError as exc:
        logger.error("%s", exc)
        if coordinator:
            coordinator.stop()
        return 1

    results: list[bool] = []
    merged_count = 0
    merge_initialized = False
    batch_ui = BatchUI(ui_files, estimates=estimates)

    if batch_ui.can_redraw:
        batch_ui.start()

    conversion_finished = False
    try:
        for idx, (f, error) in enumerate(targets):
            f_path = Path(f)
            if error:
                batch_ui.fail_file(idx, error)
                results.append(False)
                continue

            estimate = estimates[idx]
            hint = f"~{format_duration(estimate)}" if estimate is not None else ""
            batch_ui.start_file(idx, hint=hint)
            extension = f_path.suffix.lower()
            output_path = target_paths[idx]
            status_info = ""
            if merge_target is not None:
                if merge_skipped:
                    status_info = f"skipped, existing merge output: {merge_target.name}"
            elif args.skip_existing and output_path.exists() and output_path != f_path:
                status_info = f"skipped, existing output: {output_path.name}"
            elif args.overwrite and extension in TEXT_EXTENSIONS:
                status_info = "overwritten"
            elif args.overwrite:
                status_info = "overwrite ignored (binary file)"

            if merge_skipped:
                batch_ui.complete_file(idx, True, 0.0, info=status_info)
                results.append(True)
                continue

            def on_progress(current: int, total: int, unit: str = "pages") -> None:
                batch_ui.update_progress(idx, current, total, unit)

            def on_complete(success: bool, dur: float, imgs: int, tokens: int) -> None:
                batch_ui.complete_file(idx, success, dur, imgs, tokens, status_info)

            error_count_before = len(batch_ui.errors)
            logger_was_disabled = logger.disabled
            logger.disabled = True
            try:
                res = convert_file(
                    f_path,
                    overwrite=args.overwrite,
                    skip_existing=args.skip_existing if merge_target is None else False,
                    progress_callback=on_progress,
                    completion_callback=on_complete,
                    batch_mode=True,
                    target_dir=output_path.parent if output_root is not None and merge_target is None else None,
                    asset_dir=(
                        merge_asset_paths(f_path, merge_root, merge_target)[0]
                        if merge_target is not None and merge_root is not None
                        else None
                    ),
                    write_markdown=merge_target is None,
                )
            finally:
                logger.disabled = logger_was_disabled
            succeeded = bool(res)
            if not succeeded:
                reason = getattr(res, "error", None)
                if len(batch_ui.errors) > error_count_before:
                    name, previous_reason = batch_ui.errors[-1]
                    batch_ui.errors[-1] = (name, reason or previous_reason)
                else:
                    batch_ui.errors.append((f_path.name, reason or "conversion failed"))
            if succeeded and merge_target is not None and merge_root is not None:
                if res.markdown is None:
                    succeeded = False
                    batch_ui.converted_count -= 1
                    batch_ui.statuses[idx] = "[!]"
                    batch_ui.details[idx] = "-"
                    batch_ui.errors.append((f_path.name, "conversion returned no Markdown for merge"))
                else:
                    try:
                        if not merge_initialized:
                            initialize_merge_file(merge_target, merge_sources, merge_root)
                            merge_initialized = True
                        _, asset_prefix = merge_asset_paths(f_path, merge_root, merge_target)
                        append_merged_document(
                            merge_target,
                            f_path,
                            res.markdown,
                            merge_root,
                            asset_prefix,
                        )
                        merged_count += 1
                    except OSError as exc:
                        succeeded = False
                        batch_ui.converted_count -= 1
                        batch_ui.statuses[idx] = "[!]"
                        batch_ui.details[idx] = "-"
                        batch_ui.errors.append((f_path.name, f"could not append to merge output: {exc}"))
            results.append(succeeded)
        conversion_finished = True
    finally:
        if not conversion_finished:
            batch_ui.stop()
        if coordinator:
            coordinator.stop()

    failed_count = sum(not result for result in results)
    merge_failed = False
    if merge_target is not None and any(results) and not merge_skipped:
        if merge_initialized and merged_count > 0 and merge_target.is_file():
            batch_ui.add_result("Merged documents", merged_count)
        else:
            merge_failed = True
            batch_ui.errors.append((merge_target.name, "merge did not produce an output file"))

    batch_ui.finish()
    batch_ui.add_result("Converted files", batch_ui.converted_count)
    batch_ui.add_result("Extracted images", batch_ui.image_count)
    batch_ui.add_result("Skipped existing outputs", batch_ui.skipped_count)
    batch_ui.add_result("Overwritten text sources", batch_ui.overwritten_count)

    if not batch_ui.can_redraw:
        batch_ui.print_summary()
    if batch_ui.errors:
        batch_ui.print_error_list()
    batch_ui.print_results()

    if (
        getattr(args, "right_click", False)
        or getattr(args, "coordinator", False)
        or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
    ):
        from rich.console import Console
        from rich.text import Text

        try:
            follow_up = Text("\nPress ")
            follow_up.append("Enter", style="orange1")
            follow_up.append(" to exit... ")
            Console().print(follow_up, end="")
            input()
        except (EOFError, KeyboardInterrupt):
            pass

    return 1 if failed_count or merge_failed else 0


def convert_files(
    files: Sequence[str | os.PathLike[str]],
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    overwrite: bool = False,
    skip_existing: bool = False,
    output_dir: str | os.PathLike[str] | None = None,
    merge: str | os.PathLike[str] | None = None,
    stdout: bool = False,
    confirm: bool = False,
) -> int:
    """Convert selected files using the same public options as the CLI."""
    if confirm and not stdout:
        raise ValueError("confirm can only be used with stdout")
    if stdout and (merge is not None or output_dir is not None or overwrite or skip_existing):
        raise ValueError("stdout cannot be combined with merge, output_dir, overwrite, or skip_existing")
    if merge is not None and overwrite:
        raise ValueError("merge cannot be combined with overwrite")
    if merge is not None and output_dir is not None:
        raise ValueError("merge cannot be combined with output_dir")
    if overwrite and skip_existing:
        raise ValueError("overwrite cannot be combined with skip_existing")
    if overwrite and output_dir is not None:
        raise ValueError("overwrite cannot be combined with output_dir")
    include_patterns = _normalize_patterns(include, "include")
    exclude_patterns = _normalize_patterns(exclude, "exclude")
    namespace = argparse.Namespace(
        files=[os.fspath(path) for path in files],
        include=include_patterns,
        exclude=exclude_patterns,
        overwrite=overwrite,
        skip_existing=skip_existing,
        output_dir=os.fspath(output_dir) if output_dir is not None else None,
        merge=os.fspath(merge) if merge is not None else None,
        stdout=stdout,
        confirm=confirm,
        coordinator=False,
        right_click=False,
    )
    return run_batch(namespace)


def _normalize_patterns(patterns: Sequence[str], flag: str) -> list[str]:
    normalized_patterns: list[str] = []
    for pattern in patterns:
        normalized = pattern.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        try:
            re.compile(normalized)
        except re.error as exc:
            raise ValueError(f"{flag} invalid regular expression {pattern!r}: {exc}") from exc
        normalized_patterns.append(normalized)
    return normalized_patterns
