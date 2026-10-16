from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from hammerdown.core import (
    ConversionResult,
    SUPPORTED_EXTENSIONS,
    TEXT_EXTENSIONS,
    convert_file,
    get_conversion_estimate_seconds,
)
from hammerdown.ipc import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.merge import (
    append_merged_document,
    initialize_merge_file,
    merge_asset_paths,
    merge_root_for_inputs,
    render_merged_markdown,
)
from hammerdown.batch_ui import BatchUI
from hammerdown.utils import format_duration, normalize_path

logger = logging.getLogger("hammerdown")


def _expand_paths(
    paths: Sequence[str],
    excluded_dir: Path | None = None,
    include_patterns: Sequence[re.Pattern[str]] = (),
    exclude_patterns: Sequence[re.Pattern[str]] = (),
) -> list[tuple[str, str | None]]:
    targets: list[tuple[str, str | None]] = []
    seen_paths: set[Path] = set()
    excluded_dir = excluded_dir.resolve() if excluded_dir is not None else None

    def matches(path: Path, root: Path | None) -> bool:
        if root is not None:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
        else:
            relative = path.name
        if include_patterns and not any(pattern.search(relative) for pattern in include_patterns):
            return False
        return not any(pattern.search(relative) for pattern in exclude_patterns)

    for raw in paths:
        try:
            p = Path(normalize_path(raw)).resolve()
        except Exception:
            targets.append((str(raw), "invalid path"))
            continue

        if not p.exists():
            targets.append((str(raw), "file or directory not found"))
            continue

        if p.is_dir():
            for root, dirnames, filenames in os.walk(p):
                if excluded_dir is not None:
                    dirnames[:] = [
                        name for name in dirnames
                        if not (Path(root) / name).resolve().is_relative_to(excluded_dir)
                    ]
                for f in sorted(filenames):
                    if (
                        f.startswith("~$")
                        or f.startswith(".")
                        or (f.startswith("hm_") and f.lower().endswith(".md"))
                    ):
                        continue
                    try:
                        file_path = (Path(root) / f).resolve()
                        if (
                            file_path.suffix.lower() in SUPPORTED_EXTENSIONS
                            and file_path not in seen_paths
                            and matches(file_path, p)
                        ):
                            seen_paths.add(file_path)
                            targets.append((str(file_path), None))
                    except OSError:
                        continue
        elif p.is_file():
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                targets.append((str(p), "unsupported format"))
            elif p not in seen_paths and matches(p, None):
                seen_paths.add(p)
                targets.append((str(p), None))

    return targets



def _process_single_file(args_tuple: tuple[str, bool, bool]) -> ConversionResult:
    file_path, overwrite, skip_existing = args_tuple
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    return convert_file(
        file_path,
        overwrite=overwrite,
        skip_existing=skip_existing,
    )


def _output_paths(
    raw_files: Sequence[str],
    targets: Sequence[tuple[str, str | None]],
    output_root: Path,
) -> list[Path]:
    roots: list[Path] = []
    for raw in raw_files:
        try:
            path = Path(normalize_path(raw)).resolve()
        except (OSError, ValueError):
            continue
        if path.is_dir():
            roots.append(path)

    output_paths: list[Path] = []
    for path, _ in targets:
        source = Path(path).resolve()
        matching_roots = [root for root in roots if source.is_relative_to(root)]
        if matching_roots:
            relative = source.relative_to(max(matching_roots, key=lambda root: len(root.parts)))
        else:
            relative = Path(source.name)
        ext_clean = source.suffix.lower().lstrip(".")
        output_name = f"hm_{source.stem}_{ext_clean}.md" if ext_clean else f"hm_{source.stem}.md"
        output_paths.append(output_root / relative.parent / output_name)

    collisions: dict[Path, list[Path]] = {}
    for (source, error), output in zip(targets, output_paths):
        if error is None:
            collisions.setdefault(output, []).append(Path(source))
    duplicates = {output: sources for output, sources in collisions.items() if len(sources) > 1}
    if duplicates:
        details = "; ".join(
            f"{output}: {', '.join(str(source) for source in sources)}"
            for output, sources in duplicates.items()
        )
        raise ValueError(f"output filename collision: {details}")
    return output_paths


def _approximate_tokens(paths: Sequence[str]) -> int | None:
    total_bytes = 0
    try:
        for path in paths:
            total_bytes += Path(path).stat().st_size
    except OSError:
        return None
    return max(1, total_bytes // 4) if paths else 0


def _confirm_stdout(paths: Sequence[str], estimates: Sequence[float | None]) -> bool:
    token_estimate = _approximate_tokens(paths)
    known_estimates = [value for value in estimates if value is not None]
    seconds = sum(known_estimates) if len(known_estimates) == len(paths) and paths else (0.0 if not paths else None)
    token_text = f"~{token_estimate:_}" if token_estimate is not None else "unknown"
    duration_text = f"~{format_duration(seconds)}" if seconds is not None else "unknown"
    print(
        f"Preflight: {len(paths)} files, approximately {token_text} tokens, estimated time {duration_text}.",
        file=sys.stderr,
    )
    if not sys.stdin.isatty():
        print("Confirmation requires interactive stdin; cancelled.", file=sys.stderr)
        return False
    try:
        print("Continue and write Markdown to stdout? [y/N] ", end="", file=sys.stderr, flush=True)
        answer = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.", file=sys.stderr)
        return False
    if answer != "y":
        print("Cancelled.", file=sys.stderr)
        return False
    return True


def _run_stdout_conversion(files: Sequence[str], raw_inputs: Sequence[str]) -> int:
    if not files:
        return 0
    converted: list[tuple[str, str]] = []
    failed = False
    for file_path in files:
        logger_was_disabled = logger.disabled
        logger.disabled = True
        try:
            result = convert_file(
                file_path,
                batch_mode=True,
                target_dir=None,
                stdout=True,
            )
        finally:
            logger.disabled = logger_was_disabled
        if result.success and result.markdown is not None:
            converted.append((file_path, result.markdown))
        else:
            failed = True
            print(f"[!] {Path(file_path).name}: {result.error or 'conversion failed'}", file=sys.stderr)
    if converted:
        root = merge_root_for_inputs(raw_inputs, [Path(path) for path, _ in converted])
        sys.stdout.write(render_merged_markdown(converted, root))
    return 1 if failed else 0


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
    targets = _expand_paths(
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
        if getattr(args, "confirm", False) and files and not _confirm_stdout(files, file_estimates):
            return 1
        if not files:
            return 1 if initial_errors else 0
        conversion_status = _run_stdout_conversion(files, raw_files)
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
            import ctypes

            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5)
                ctypes.windll.user32.SetForegroundWindow(hwnd)

        initial_errors = [target for target in targets if target[1] is not None]
        collected_files = coordinator.collect_files(files, assembly_timeout=0.35)
        targets = _expand_paths(
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
            output_paths = [merge_target] * len(targets)
        elif output_root is not None:
            output_paths = _output_paths(output_path_inputs, targets, output_root)
        else:
            output_paths = [
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
            output_path = output_paths[idx]
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

    if getattr(args, "right_click", False):
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
    include_patterns = []
    for pattern in include:
        normalized = pattern.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        try:
            re.compile(normalized)
        except re.error as exc:
            raise ValueError(f"include invalid regular expression {pattern!r}: {exc}") from exc
        include_patterns.append(normalized)
    exclude_patterns = []
    for pattern in exclude:
        normalized = pattern.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        try:
            re.compile(normalized)
        except re.error as exc:
            raise ValueError(f"exclude invalid regular expression {pattern!r}: {exc}") from exc
        exclude_patterns.append(normalized)
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
