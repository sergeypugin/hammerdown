from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import tempfile
import urllib.error
from pathlib import Path
from typing import Sequence

from ..core import (
    ConversionResult,
    TEXT_EXTENSIONS,
    convert_file,
    get_conversion_estimate_seconds,
    get_output_path,
)
from ..core.job import ConversionJob, PreparedConversion, failed_conversion, prepare_conversion
from ..core.discovery import DiscoveredTarget, DiscoveryResult, discover_paths, discover_tree, output_paths as compute_output_paths
from ..core.google_drive import download_google_url, extract_file_id, is_google_drive_url
from ..core.github import acquire_github, parse_github_locator
from ..core.acquisition import acquire_inputs, validate_local_inputs
from ..core.ipc import IPCCoordinator, try_delegate_to_coordinator
from ..core.merge import (
    MergeSession,
    append_merged_document,
    convert_source_text,
    initialize_merge_file,
    merge_asset_paths,
    merge_root_for_inputs,
    render_merged_markdown,
    _is_convertible_binary,
    _is_binary_file,
)
from ..ui.batch_ui import BatchUI
from ..core.stdout_mode import confirm_stdout, run_stdout_conversion
from ..core.formatting import format_duration
from ..core.filters import OrderedFilterValues
from ..core.output import OutputStaging
from ..core.path_utils import normalize_path
from ..core.platform_utils import is_windows
from ..core.preflight import build_preflight_report, render_preflight_report
from ..core.scheduler import BatchScheduler, calculate_optimal_workers, create_scheduler, should_use_concurrent_scheduler

logger = logging.getLogger("hammerdown")
_prepare_conversion = prepare_conversion


def _ensure_console_window() -> None:
    """Show the current console or allocate a fallback console on Windows."""
    if os.name != "nt":
        return

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
    kernel32.SetConsoleTitleW("Hammerdown")
    if hwnd:
        user32.ShowWindow(hwnd, 5)
        user32.SetForegroundWindow(hwnd)


def confirm_merge_overwrite(target: Path) -> bool:
    """Ask before reusing an existing merge/tree target; True overwrites, False skips the run."""
    print(f"merge target {target.name} already exists.", file=sys.stderr)
    while True:
        try:
            print(f"Overwrite {target.name}? [y/n] ", end="", file=sys.stderr, flush=True)
            line = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.", file=sys.stderr)
            return False
        if not line:
            print("\nCancelled.", file=sys.stderr)
            return False
        answer = line.strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            print("Cancelled.", file=sys.stderr)
            return False
        print('Please answer "y" or "n".', file=sys.stderr)


def hand_off_to_windows_terminal(
    files: Sequence[str],
    args: argparse.Namespace,
    merge_auto: bool,
) -> bool:
    """Run an Explorer selection in one Windows Terminal window.

    Returns ``False`` when this is not a Windows context-menu run or when
    Windows Terminal is unavailable, so the caller can fall back to a console.
    """
    if not is_windows() or getattr(args, "context_worker", False):
        return False
    if not getattr(args, "coordinator", False):
        return False

    from ..integrations.windows_terminal import launch_context_worker

    if getattr(args, "include_gitignored", False):
        return False

    tree = getattr(args, "tree", False)
    filter_queue = getattr(getattr(args, "include", None), "filter_queue", None)
    if filter_queue is None:
        filter_queue = getattr(getattr(args, "exclude", None), "filter_queue", None)
    handoff_options = {
        "merge": getattr(args, "merge", None),
        "merge_auto": merge_auto,
        "tree": tree,
        "all_formats": getattr(args, "all_formats", False),
        "include": getattr(args, "include", []),
        "exclude": getattr(args, "exclude", []),
        "overwrite": getattr(args, "overwrite", False),
        "skip_existing": getattr(args, "skip_existing", False),
        "yes": getattr(args, "yes", False),
        "no": getattr(args, "no", False),
        "output_dir": getattr(args, "output_dir", None),
    }
    if filter_queue is not None:
        handoff_options["filter_queue"] = list(filter_queue)
    return launch_context_worker(files, **handoff_options)


def run_batch(args: argparse.Namespace) -> int:
    google_staging = tempfile.TemporaryDirectory(prefix="hammerdown-remote-")
    try:
        return _run_batch(args, Path(google_staging.name))
    finally:
        google_staging.cleanup()


def _run_batch(args: argparse.Namespace, google_staging_dir: Path) -> int:
    raw_files = args.files
    initial_input_paths = list(raw_files)
    merge_requested = getattr(args, "merge", None)
    merge_auto = getattr(args, "merge_auto", False)
    tree_mode = getattr(args, "tree", False)
    dir_struct = getattr(args, "dir_struct", False)
    structure_mode = tree_mode or dir_struct
    all_formats = getattr(args, "all_formats", False)

    if tree_mode:
        merge_auto = False
        
    # Ensure merge_sources is defined for all paths
    merge_sources: list[str] = []
    if merge_requested and getattr(args, "overwrite", False):
        logger.error("--merge cannot be combined with --overwrite")
        return 1
    if merge_requested and getattr(args, "output_dir", None):
        logger.error("--merge cannot be combined with --output-dir")
        return 1
    if not raw_files:
        logger.info("No supported documents found to convert")
        return 0

    # Validate local paths, output paths and filters before any remote acquisition.
    output_dir = getattr(args, "output_dir", None)
    output_root = Path(output_dir).resolve() if output_dir else None
    if output_root is not None and output_root.exists() and not output_root.is_dir():
        logger.error("output directory path is not a directory: %s", output_root)
        return 1
    discovery_merge_target = Path(normalize_path(merge_requested)) if merge_requested else None
    from ..core.filters import compile_cli_filters
    try:
        include_spec, exclude_spec = compile_cli_filters(
            getattr(args, "include", []),
            getattr(args, "exclude", []),
        )
    except (TypeError, ValueError) as exc:
        logger.error("invalid filter pattern: %s", exc)
        return 1
    input_errors = validate_local_inputs(
        raw_files,
        allow_github_repository_root=structure_mode,
        google_url_checker=is_google_drive_url,
    )
    remote_inputs = [
        raw
        for raw in raw_files
        if is_google_drive_url(raw)
        or parse_github_locator(raw, allow_repository_root=structure_mode) is not None
    ]
    if input_errors and remote_inputs:
        for path, reason in input_errors:
            logger.error("%s: %s", path, reason)
        return 1

    # Resolve all remote inputs in one run-owned staging pass before discovery.
    allow_github_root = structure_mode
    acquired = acquire_inputs(
        raw_files,
        google_staging_dir,
        allow_github_repository_root=allow_github_root,
        google_downloader=download_google_url,
        google_url_checker=is_google_drive_url,
        github_acquirer=acquire_github,
    )
    google_downloaded = {
        str(item.local_path.resolve())
        for item in acquired.inputs
        if item.provenance.get("kind") == "google" and item.local_path is not None
    }
    github_downloaded = {
        str(item.local_path.resolve())
        for item in acquired.inputs
        if item.provenance.get("kind") == "github" and item.local_path is not None
    }
    acquisition_failed = [
        (item.original, item.error or "input acquisition failed", item.provenance.get("kind"))
        for item in acquired.inputs
        if item.error is not None
    ]
    resolved_files = [
        str(item.local_path)
        for item in acquired.inputs
        if item.local_path is not None
    ]
    raw_files = resolved_files

    if getattr(args, "tokens", False) or getattr(args, "report_time", False) or dir_struct:
        targets_for_report = (
            discover_tree(
                resolved_files,
                include_patterns=include_spec,
                exclude_patterns=exclude_spec,
                all_formats=True if dir_struct and not getattr(args, "all_formats", False) else all_formats,
                include_gitignored=getattr(args, "include_gitignored", False),
            )
            if dir_struct
            else discover_paths(
                resolved_files,
                include_patterns=include_spec,
                exclude_patterns=exclude_spec,
                include_gitignored=getattr(args, "include_gitignored", False),
            )
        )
        if acquired.errors:
            targets_for_report.errors.extend(acquired.errors)
        report = build_preflight_report(resolved_files, targets_for_report)
        rendered_report = render_preflight_report(
            report,
            tokens=getattr(args, "tokens", False),
            timing=getattr(args, "report_time", False),
            structure=dir_struct,
        )
        print(rendered_report, end="")
        return 1 if acquired.errors or targets_for_report.errors else 0



    def discover(paths: Sequence[str]) -> DiscoveryResult:
        if tree_mode:
            return discover_tree(
                paths,
                all_formats=all_formats,
                excluded_dir=output_root,
                include_patterns=include_spec,
                exclude_patterns=exclude_spec,
                include_gitignored=getattr(args, "include_gitignored", False),
                excluded_file=discovery_merge_target,
            )
        return discover_paths(
            paths,
            excluded_dir=output_root,
            include_patterns=include_spec,
            exclude_patterns=exclude_spec,
            include_gitignored=getattr(args, "include_gitignored", False),
            excluded_file=discovery_merge_target,
        )

    def explicitly_selected_files(paths: Sequence[str]) -> set[Path]:
        selected: set[Path] = set()
        for raw_path in paths:
            try:
                candidate = Path(raw_path).resolve()
                if candidate.is_file():
                    selected.add(candidate)
            except OSError:
                continue
        return selected

    def targets_from_discovery(result: DiscoveryResult, paths: Sequence[str]) -> list[tuple[str, str | None, str | None]]:
        discovered_targets: list[tuple[str, str | None, str | None]] = [
            (target.path, None, target.category) for target in result.targets
        ]
        discovered_targets.extend((path, error, None) for path, error in result.errors)
        selected = explicitly_selected_files(paths)
        if not tree_mode:
            for skip in result.skipped:
                if skip.reason == "unsupported format" and Path(skip.path).resolve() in selected:
                    discovered_targets.append((skip.path, skip.reason, None))
        for generated in result.generated_outputs:
            if Path(generated).resolve() in selected:
                discovered_targets.append((generated, "generated output is not an input resource", None))
        return discovered_targets

    def skips_from_discovery(result: DiscoveryResult, paths: Sequence[str]):
        selected = explicitly_selected_files(paths) if not tree_mode else set()
        ignore_paths = {Path(path).resolve() for path in result.ignore_files}
        return [
            skip for skip in result.skipped
            if Path(skip.path).resolve() not in ignore_paths
            and not (skip.reason == "unsupported format" and Path(skip.path).resolve() in selected)
        ]

    discovery = discover(raw_files)
    targets = targets_from_discovery(discovery, raw_files)
    if not targets and discovery.generated_outputs:
        generated = Path(discovery.generated_outputs[0]).name
        targets.append((generated, "all input resources are generated outputs; no input resources to convert", None))
    discovery_skips = skips_from_discovery(discovery, raw_files)
    ignore_files = list(discovery.ignore_files)
    for input_path, reason, kind in acquisition_failed:
        label = input_path
        if kind == "google":
            file_id = extract_file_id(input_path)
            if file_id:
                label = f"Google Doc ({file_id[:8]}...)"
        logger.error("%s: %s", label, reason)
        targets.append((label, reason, None))
    files: list[str] = []
    merge_sources: list[str] = []
    ui_files: list[str] = []
    estimates: list[float | None] = []

    def update_merge_state():
        nonlocal files, merge_sources, ui_files, estimates
        targets.sort(key=lambda item: item[0].lower())
        files = [path for path, error, _ in targets if error is None]
        merge_sources = [str(Path(p).resolve()) for p in files]
        ui_files = [path for path, _, _ in targets]
        estimates = [
            get_conversion_estimate_seconds(Path(path)) if error is None else None
            for path, error, _ in targets
        ]

    update_merge_state()

    if getattr(args, "stdout", False):
        initial_errors = [(path, error) for path, error, _ in targets if error is not None]
        for path, error in initial_errors:
            print(f"[!] {Path(path).name}: {error}", file=sys.stderr)
        reporting_ui = BatchUI(ui_files, estimates=estimates)
        reporting_ui.skipped_files.extend((Path(skip.path).name, skip.reason) for skip in discovery_skips)
        reporting_ui.print_ignore_files(ignore_files, file=sys.stderr)
        reporting_ui.print_skipped_list(file=sys.stderr)
        file_estimates = [estimate for (_, error, _), estimate in zip(targets, estimates) if error is None]
        if getattr(args, "confirm", False) and files and not confirm_stdout(files, file_estimates):
            return 1
        if not files:
            return 1 if initial_errors else 0
        conversion_status = run_stdout_conversion(files, raw_files)
        return 1 if initial_errors or conversion_status else 0

    context_worker = getattr(args, "context_worker", False)
    use_ipc = (
        (getattr(args, "coordinator", False) or os.environ.get("HAMMERDOWN_COORDINATOR") == "1")
        and not context_worker
    )
    options = {
        "tree": tree_mode,
        "all_formats": all_formats,
        "merge": merge_requested,
        "merge_auto": merge_auto,
        "include": list(getattr(args, "include", [])),
        "exclude": list(getattr(args, "exclude", [])),
        "overwrite": getattr(args, "overwrite", False),
        "skip_existing": getattr(args, "skip_existing", False),
        "yes": getattr(args, "yes", False),
        "no": getattr(args, "no", False),
        "output": getattr(args, "output_dir", None),
        "stdout": getattr(args, "stdout", False),
        "confirm": getattr(args, "confirm", False),
        "include_gitignored": getattr(args, "include_gitignored", False),
    }

    filter_queue = getattr(getattr(args, "include", None), "filter_queue", None)
    if filter_queue is None:
        filter_queue = getattr(getattr(args, "exclude", None), "filter_queue", None)
    if filter_queue is not None:
        options["filter_queue"] = list(filter_queue)

    coordinator = IPCCoordinator() if use_ipc else None
    coordinator_started = coordinator.start() if coordinator else False
    if coordinator is not None and coordinator_started and hasattr(coordinator, "set_initial_options"):
        coordinator.set_initial_options(options)
    if use_ipc and not coordinator_started:
        if getattr(args, "include_gitignored", False) or google_downloaded:
            coordinator = None
            use_ipc = False
        else:
            if (
                not google_downloaded
                and files
                and not any(error for _, error, _ in targets)
                and try_delegate_to_coordinator(files, options)
            ):
                logger.info("Delegated %d files to active hammerdown coordinator", len(files))
                return 0
            if files:
                # Delegation declined (coordinator busy, options conflict, or
                # unreachable): convert locally instead of exiting silently.
                logger.info("Coordinator unavailable; converting %d files locally", len(files))
                coordinator = None
                use_ipc = False
            else:
                reporting_ui = BatchUI(ui_files, estimates=estimates)
                reporting_ui.errors.extend((path, error) for path, error, _ in targets if error is not None)
                reporting_ui.skipped_files.extend((Path(skip.path).name, skip.reason) for skip in discovery_skips)
                reporting_ui.print_error_list()
                reporting_ui.print_ignore_files(ignore_files)
                reporting_ui.print_skipped_list()
                return 1 if reporting_ui.errors else 0

    if coordinator is not None and coordinator_started:
        initial_errors = [target for target in targets if target[1] is not None]
        collected_files = coordinator.collect_files(files, assembly_timeout=2.0)
        close_assembly = getattr(coordinator, "close_assembly", None)
        if close_assembly is not None:
            close_assembly()
        delegated = getattr(coordinator, "delegated_options", None)
        if delegated is not None:
            tree_mode = delegated["tree"]
            all_formats = delegated["all_formats"]
            merge_requested = delegated["merge"]
            merge_auto = delegated["merge_auto"]
            args.include = list(delegated["include"])
            args.exclude = list(delegated["exclude"])
            if "filter_queue" in delegated:
                args.include = OrderedFilterValues(args.include)
                args.exclude = OrderedFilterValues(args.exclude)
                args.include.filter_queue = list(delegated["filter_queue"])
                args.exclude.filter_queue = list(delegated["filter_queue"])
            args.overwrite = delegated["overwrite"]
            args.skip_existing = delegated["skip_existing"]
            args.yes = delegated["yes"]
            args.no = delegated["no"]
            args.output_dir = delegated["output"]
            args.stdout = delegated["stdout"]
            args.confirm = delegated["confirm"]
            args.include_gitignored = delegated["include_gitignored"]
            include_spec, exclude_spec = compile_cli_filters(args.include, args.exclude)
            discovery_merge_target = Path(normalize_path(merge_requested)) if merge_requested else None
        local_rescan_inputs = [
            path
            for path in initial_input_paths
            if not is_google_drive_url(path)
            and parse_github_locator(path, allow_repository_root=structure_mode) is None
        ]
        rescan_paths = [*local_rescan_inputs, *raw_files, *collected_files]
        rescanned = discover(rescan_paths)
        targets = targets_from_discovery(rescanned, rescan_paths)
        if not targets and rescanned.generated_outputs:
            generated = Path(rescanned.generated_outputs[0]).name
            targets.append((generated, "all input resources are generated outputs; no input resources to convert", None))
            
        update_merge_state()
        ignore_files = sorted(set(ignore_files).union(rescanned.ignore_files))
        discovery_skips.extend(
            skip for skip in skips_from_discovery(rescanned, rescan_paths) if skip not in discovery_skips
        )
        output_path_inputs = [*raw_files, *collected_files]

        # The worker is asynchronous, while Google sources live only in this run's staging directory.
        if not google_downloaded and hand_off_to_windows_terminal(
            list(dict.fromkeys(output_path_inputs)), args, merge_auto
        ):
            coordinator.stop()
            return 0
        _ensure_console_window()
    elif use_ipc:
        return 0
    else:
        output_path_inputs = raw_files

    # Resolve default merge output for --right-click --merge-auto once the full
    # selection is known, so the target does not depend on which process won
    # the coordinator race.
    if merge_auto and merge_requested is None and files:
        merge_parent = Path.cwd()
        for path in files:
            source = Path(path)
            if str(source.resolve()) not in google_downloaded:
                merge_parent = source.parent
                break
        merge_requested = str(merge_parent / "hammerdowned.md")

    # merge_sources is already correctly defined and resolved by update_merge_state().
    merge_target = Path(normalize_path(merge_requested)) if merge_requested else None
    if merge_target is None and tree_mode:
        coordinator_tree = (
            getattr(args, "right_click", False)
            or getattr(args, "coordinator", False)
            or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
        )
        merge_parent = (
            merge_root_for_inputs(output_path_inputs, [Path(path) for path in merge_sources])
            if coordinator_tree
            else Path.cwd()
        )
        merge_requested = str(merge_parent / "hammerdowned.md")
        merge_target = Path(normalize_path(merge_requested))

    if merge_target is not None and any(Path(path).resolve() == merge_target.resolve() for path in merge_sources):
        logger.error("merge target cannot be one of the source files: %s", merge_target)
        if coordinator:
            coordinator.stop()
        return 1

    merge_root = (
        merge_root_for_inputs(output_path_inputs, [Path(path) for path in merge_sources]).resolve()
        if merge_target is not None
        else None
    )
    merge_skipped = bool(merge_target is not None and args.skip_existing and merge_target.exists())

    try:
        if merge_target is not None:
            target_paths = [merge_target] * len(targets)
        elif output_root is not None:
            target_paths = compute_output_paths(
                output_path_inputs,
                [(path, error) for path, error, _ in targets],
                output_root,
            )
        else:
            target_paths = []
            for path, _, _ in targets:
                p = Path(path)
                # Google-downloaded HTML lives in a temporary staging folder; write
                # its Markdown output next to the user (cwd) or in -o/--output-dir.
                if str(p.resolve()) in google_downloaded:
                    base = output_root if output_root is not None else Path.cwd()
                    target_paths.append(get_output_path(p, base))
                else:
                    target_paths.append(get_output_path(p))
    except ValueError as exc:
        logger.error("%s", exc)
        if coordinator:
            coordinator.stop()
        return 1

    directory_collisions = list(dict.fromkeys(path for path in target_paths if path.is_dir()))
    if directory_collisions:
        for collision in directory_collisions:
            logger.error("output target is a directory: %s", collision)
        if coordinator:
            coordinator.stop()
        return 1

    if merge_target is not None and not merge_skipped and merge_target.exists() and not getattr(args, "yes", False):
        if getattr(args, "no", False):
            merge_skipped = True
        elif sys.stdin.isatty():
            if not confirm_merge_overwrite(merge_target):
                merge_skipped = True
        else:
            logger.error(
                "merge target %s already exists; re-run with --skip-existing to keep it, --yes to overwrite it, or -m <path> for a different file",
                merge_target.name,
            )
            if coordinator:
                coordinator.stop()
            return 1

    results: list[bool] = []
    merged_count = 0
    merge_initialized = False
    merge_commit_failed = False
    batch_ui = BatchUI(ui_files, estimates=estimates)
    batch_ui.skipped_files.extend((Path(skip.path).name, skip.reason) for skip in discovery_skips)
    batch_ui.print_ignore_files(ignore_files)

    if not targets:
        logger.info("No supported documents found to convert")

    if batch_ui.can_redraw:
        batch_ui.start()

    conversion_finished = False
    merge_session: MergeSession | None = None

    has_real_pdf = any(
        Path(path).suffix.lower() in {".pdf", ".epub", ".mobi", ".fb2", ".xps"}
        and Path(path).is_file()
        and Path(path).stat().st_size > 1024
        for path, error, _ in targets
        if error is None
    )

    scheduler: BatchScheduler | None = None
    try:
        if merge_target is not None and not merge_skipped:
            merge_session = MergeSession(merge_target)
        use_concurrent = should_use_concurrent_scheduler(
            merge=merge_target is not None,
            tree=tree_mode,
            dir_struct=dir_struct,
            stdout=getattr(args, "stdout", False),
            use_work_units=has_real_pdf,
        )
        if use_concurrent:
            if merge_target is not None and merge_skipped:
                for idx, (f, error, category) in enumerate(targets):
                    if error is not None:
                        batch_ui.fail_file(idx, error)
                        results.append(False)
                    else:
                        batch_ui.skip_file(idx, f"existing merge output: {merge_target.name}")
                        results.append(True)
            else:
                ui_completed: set[int] = set()
                merge_prepare_errors: dict[int, BaseException] = {}

                def finish_ui(job: ConversionJob, success: bool, duration: float, images: int, tokens: int) -> None:
                    idx = job.input_index if job.input_index is not None else -1
                    ui_completed.add(idx)
                    batch_ui.complete_file(idx, success, duration, images, tokens, "")

                def prepare_for_merge(job: ConversionJob, progress_callback=None) -> PreparedConversion:
                    started_at = time.monotonic()
                    if job.category == "source_code":
                        raw = convert_source_text(job.source)
                        duration = time.monotonic() - started_at
                        if raw.success:
                            tokens = len(raw.markdown or "")
                            finish_ui(job, True, duration, 0, tokens)
                            staging = OutputStaging.create(
                                job.resource_dir.parent,
                                prefix=f".hammerdown-{job.source.stem}-src-",
                            )
                            staged = staging.path / job.output_path.name
                            staged.write_text(raw.markdown or "", encoding="utf-8", newline="\n")
                            return PreparedConversion(
                                job=job,
                                source=job.source,
                                output_path=job.output_path,
                                staged_markdown=staged,
                                staging=staging,
                                tokens=tokens,
                                duration=duration,
                            )
                        return failed_conversion(job, raw.error or "conversion failed", duration=duration)

                    asset_dir = None
                    if merge_session is not None and merge_root is not None:
                        asset_dir = merge_session.staging_asset_directory(job.source, merge_root)

                    def completion_callback(success: bool, duration: float, images: int, tokens: int) -> None:
                        finish_ui(job, success, duration, images, tokens)

                    try:
                        raw = convert_file(
                            job.source,
                            overwrite=args.overwrite,
                            skip_existing=False,
                            progress_callback=progress_callback,
                            completion_callback=completion_callback,
                            batch_mode=True,
                            asset_dir=asset_dir,
                            write_markdown=False,
                            merge_session=merge_session,
                        )
                    except Exception as exc:
                        if job.input_index is not None:
                            merge_prepare_errors[job.input_index] = exc
                        return failed_conversion(job, f"failed to convert {job.source.name}")

                    duration = getattr(raw, "duration", None) or (time.monotonic() - started_at)
                    if getattr(raw, "success", False):
                        staged_markdown_path: Path | None = None
                        staging: OutputStaging | None = None
                        markdown_text = getattr(raw, "markdown", None)
                        if markdown_text is not None:
                            staging = OutputStaging.create(
                                job.resource_dir.parent,
                                prefix=f".hammerdown-{job.source.stem}-merge-",
                            )
                            staged_markdown_path = staging.path / job.output_path.name
                            staged_markdown_path.write_text(markdown_text, encoding="utf-8", newline="\n")
                        return PreparedConversion(
                            job=job,
                            source=job.source,
                            output_path=job.output_path,
                            staged_markdown=staged_markdown_path,
                            staging=staging,
                            images=getattr(raw, "images", 0),
                            tokens=getattr(raw, "tokens", 0),
                            duration=duration,
                        )
                    return failed_conversion(
                        job,
                        getattr(raw, "error", None) or f"conversion failed for {job.source.name}",
                        duration=duration,
                    )

                scheduler = create_scheduler(
                    merge=merge_target is not None,
                    tree=tree_mode,
                    dir_struct=dir_struct,
                    stdout=getattr(args, "stdout", False),
                    prepare_fn=prepare_for_merge if merge_target is not None else _prepare_conversion,
                    use_work_units=has_real_pdf,
                    work_unit_max_workers=calculate_optimal_workers(),
                    work_unit_pdf_limit=2,
                    in_flight_limit=1 if merge_target is not None and not has_real_pdf else None,
                )
                jobs: list[ConversionJob] = []
                for idx, (f, error, category) in enumerate(targets):
                    if error is not None:
                        continue
                    f_path = Path(f)
                    output_path = target_paths[idx]
                    is_google_cache = str(f_path.resolve()) in google_downloaded or str(f_path.resolve()) in github_downloaded
                    output_dir_for_job = (
                        output_path.parent
                        if output_root is not None or is_google_cache
                        else f_path.parent
                    )
                    job = ConversionJob(
                        source=f_path,
                        output_path=(
                            f_path
                            if args.overwrite and f_path.suffix.lower() in TEXT_EXTENSIONS and not is_google_cache
                            else output_path
                        ),
                        resource_dir=output_dir_for_job,
                        skip_existing=args.skip_existing if merge_target is None else False,
                        batch_mode=True,
                        input_index=idx,
                        category=category,
                    )
                    jobs.append(job)

                def on_job_start(job: ConversionJob) -> None:
                    if job.input_index is not None:
                        idx = job.input_index
                        estimate = estimates[idx]
                        hint = f"~{format_duration(estimate)}" if estimate is not None else ""
                        batch_ui.start_file(idx, hint=hint)

                def on_job_progress(job: ConversionJob, current: int, total: int, unit: str = "pages") -> None:
                    if job.input_index is not None:
                        batch_ui.update_progress(job.input_index, current, total, unit)

                scheduled_iter = scheduler.schedule(
                    jobs,
                    on_start=on_job_start,
                    on_progress=on_job_progress,
                    auto_commit=merge_target is None,
                )

                resolved_merge_sources = [Path(s).resolve() for s in merge_sources]

                for idx, (f, error, category) in enumerate(targets):
                    f_path = Path(f).resolve()
                    if error:
                        batch_ui.fail_file(idx, error)
                        results.append(False)
                        continue

                    error_count_before = len(batch_ui.errors)
                    res = next(scheduled_iter)
                    if merge_target is not None:
                        pending_error = merge_prepare_errors.pop(idx, None)
                        if pending_error is not None:
                            raise pending_error
                    output_path = target_paths[idx]
                    extension = f_path.suffix.lower()
                    is_google_cache = str(f_path) in google_downloaded or str(f_path) in github_downloaded
                    status_info = ""
                    if res.status == "skipped":
                        status_info = f"skipped, existing output: {output_path.name}"
                    elif args.overwrite and extension in TEXT_EXTENSIONS and not is_google_cache:
                        status_info = "overwritten"
                    elif args.overwrite:
                        status_info = "overwrite ignored (binary file)"

                    cleanup_error = getattr(res, "cleanup_error", None)
                    if cleanup_error:
                        logger.warning(
                            "Staging cleanup failed for %s: %s",
                            f_path.name,
                            cleanup_error,
                        )

                    if res.status == "skipped":
                        batch_ui.skip_file(idx, f"existing output: {output_path.name}")
                        results.append(True)
                    elif res.success:
                        # Parallel Merge / Tree Support
                        if merge_target is not None and merge_root is not None:
                            try:
                                if not merge_initialized:
                                    initialize_merge_file(merge_target, merge_sources, merge_root, merge_session)
                                    merge_initialized = True

                                asset_dir, asset_prefix = merge_asset_paths(
                                    f_path, merge_root, merge_target, merge_session
                                )
                                is_binary = _is_binary_file(f_path)

                                # Work-unit PDF assembly leaves assets in job-local
                                # staging; relocate them under the session asset prefix.
                                staged_assets = getattr(res, "staged_assets", None)
                                if staged_assets is not None and staged_assets.is_dir():
                                    asset_dir.mkdir(parents=True, exist_ok=True)
                                    os.replace(staged_assets, asset_dir / staged_assets.name)

                                content: str | None = None
                                staged_markdown = getattr(res, "staged_markdown", None)
                                if staged_markdown is not None and staged_markdown.exists():
                                    content = staged_markdown.read_text(encoding="utf-8")

                                if content is None:
                                    res.abort()
                                    if idx in ui_completed:
                                        batch_ui.converted_count -= 1
                                        batch_ui.statuses[idx] = "[!]"
                                        batch_ui.details[idx] = "-"
                                    batch_ui.errors.append(
                                        (f_path.name, "conversion returned no Markdown for merge")
                                    )
                                    results.append(False)
                                    continue

                                append_merged_document(
                                    merge_target,
                                    f_path,
                                    content,
                                    merge_root,
                                    asset_prefix,
                                    is_binary=is_binary,
                                    session=merge_session,
                                )
                                merged_count += 1
                                # Now that we merged it, we can discard the conversion result
                                # (since merge target IS the output in merge mode)
                                res.abort()
                            except OSError as exc:
                                res.abort()
                                if idx in ui_completed:
                                    batch_ui.converted_count -= 1
                                    batch_ui.statuses[idx] = "[!]"
                                    batch_ui.details[idx] = "-"
                                    batch_ui.errors.append(
                                        (f_path.name, f"could not append to merge output: {exc}")
                                    )
                                else:
                                    batch_ui.complete_file(idx, False, res.duration, 0, 0, f"merge failed: {exc}")
                                results.append(False)
                                continue

                        if idx not in ui_completed:
                            batch_ui.complete_file(idx, True, res.duration, res.images, res.tokens, status_info)
                        results.append(True)
                    else:
                        reason = getattr(res, "error", None) or "conversion failed"
                        # Handle Merge Failure during parallel run
                        if merge_target is not None and merge_root is not None:
                            if idx in ui_completed:
                                if len(batch_ui.errors) > error_count_before:
                                    name, previous_reason = batch_ui.errors[-1]
                                    batch_ui.errors[-1] = (name, reason or previous_reason)
                                else:
                                    batch_ui.errors.append((f_path.name, reason))
                            try:
                                if not merge_initialized:
                                    initialize_merge_file(merge_target, merge_sources, merge_root, merge_session)
                                    merge_initialized = True
                                _, asset_prefix = merge_asset_paths(f_path, merge_root, merge_target, merge_session)
                                is_binary = _is_binary_file(f_path)
                                append_merged_document(
                                    merge_target,
                                    f_path,
                                    "",
                                    merge_root,
                                    asset_prefix,
                                    error=reason,
                                    session=merge_session,
                                    is_binary=is_binary,
                                )
                            except OSError:
                                pass
                            res.abort()
                        if idx not in ui_completed:
                            batch_ui.complete_file(idx, False, res.duration, 0, 0, reason)
                        results.append(False)

                if merge_session is not None:
                    try:
                        merge_session.finish()
                    except OSError as exc:
                        merge_commit_failed = True
                        batch_ui.errors.append((merge_session.target.name, f"could not commit merge output: {exc}"))
        else:
            # Sequential fallback
            resolved_merge_sources = [Path(s).resolve() for s in merge_sources]
            
            class MockPrepared:
                def __init__(self, res, duration):
                    self.success = bool(res)
                    self.markdown = res.markdown if res else None
                    self.duration = duration
                    self.images = res.images if res else 0
                    self.tokens = res.tokens if res else 0
                    self.status = "committed" if res else "failed"
                def abort(self):
                    pass

            for idx, (f, error, category) in enumerate(targets):
                f_path = Path(f).resolve()
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
                elif args.skip_existing and output_path.exists():
                    status_info = f"skipped, existing output: {output_path.name}"
                elif args.overwrite and extension in TEXT_EXTENSIONS:
                    status_info = "overwritten"
                elif args.overwrite:
                    status_info = "overwrite ignored (binary file)"

                if merge_skipped and merge_target is not None:
                    reason = f"existing merge output: {merge_target.name}"
                    batch_ui.skip_file(idx, reason)
                    results.append(True)
                    continue

                # Directly skip if the output exists to avoid re-parsing
                if args.skip_existing and output_path.exists() and merge_target is None:
                    reason = f"existing output: {output_path.name}"
                    batch_ui.skip_file(idx, reason)
                    results.append(True)
                    continue

                def on_progress(current: int, total: int, unit: str = "pages") -> None:
                    batch_ui.update_progress(idx, current, total, unit)

                def on_complete(success: bool, dur: float, imgs: int, tokens: int) -> None:
                    batch_ui.complete_file(idx, success, dur, imgs, tokens, status_info)

                error_count_before = len(batch_ui.errors)
                logger_was_disabled = logger.disabled
                logger.disabled = True
                is_google_cache = str(f_path.resolve()) in google_downloaded
                started_at = time.monotonic()
                try:
                    if category == "source_code":
                        res_raw = convert_source_text(f_path)
                        if res_raw.success:
                            on_complete(True, 0.0, 0, len(res_raw.markdown or ""))
                        res = MockPrepared(res_raw, time.monotonic() - started_at)
                    else:
                        res_raw = convert_file(
                            f_path,
                            overwrite=args.overwrite and not is_google_cache,
                            skip_existing=args.skip_existing if merge_target is None else False,
                            progress_callback=on_progress,
                            completion_callback=on_complete,
                            batch_mode=True,
                            target_dir=(
                                output_path.parent
                                if merge_target is None and (output_root is not None or is_google_cache)
                                else None
                            ),
                            asset_dir=(
                                merge_asset_paths(f_path, merge_root, merge_target, merge_session)[0]
                                if merge_target is not None and merge_root is not None
                                else None
                            ),
                            write_markdown=merge_target is None,
                            merge_session=merge_session,
                        )
                        res = MockPrepared(res_raw, time.monotonic() - started_at)
                finally:
                    logger.disabled = logger_was_disabled
                    
                succeeded = bool(res)
                if not succeeded:
                    reason = getattr(res_raw, "error", None) or "conversion failed"
                    if len(batch_ui.errors) > error_count_before:
                        name, previous_reason = batch_ui.errors[-1]
                        batch_ui.errors[-1] = (name, reason or previous_reason)
                    else:
                        batch_ui.errors.append((f_path.name, reason))

                    if merge_target is not None and merge_root is not None:
                        try:
                            if not merge_initialized:
                                initialize_merge_file(merge_target, resolved_merge_sources, merge_root, merge_session)
                                merge_initialized = True
                            _, asset_prefix = merge_asset_paths(f_path, merge_root, merge_target, merge_session)
                            is_binary = _is_binary_file(f_path)
                            append_merged_document(
                                merge_target,
                                f_path,
                                "",
                                merge_root,
                                asset_prefix,
                                error=reason,
                                session=merge_session,
                                is_binary=is_binary,
                            )
                        except OSError:
                            pass
                        if hasattr(res, "abort"):
                            res.abort()
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
                                initialize_merge_file(merge_target, resolved_merge_sources, merge_root, merge_session)
                                merge_initialized = True
                            _, asset_prefix = merge_asset_paths(f_path, merge_root, merge_target, merge_session)
                            is_binary = _is_binary_file(f_path)
                            append_merged_document(
                                merge_target,
                                f_path,
                                res.markdown,
                                merge_root,
                                asset_prefix,
                                is_binary=is_binary,
                                session=merge_session,
                            )
                            merged_count += 1
                        except OSError as exc:
                            succeeded = False
                            batch_ui.converted_count -= 1
                            batch_ui.statuses[idx] = "[!]"
                            batch_ui.details[idx] = "-"
                            batch_ui.errors.append((f_path.name, f"could not append to merge output: {exc}"))
                        
                    res.abort()
                results.append(succeeded)
            if merge_session is not None:
                try:
                    merge_session.finish()
                except OSError as exc:
                    merge_commit_failed = True
                    batch_ui.errors.append((merge_session.target.name, f"could not commit merge output: {exc}"))
        conversion_finished = True
    finally:
        if 'scheduler' in locals() and scheduler:
            scheduler.cancel()
        if not conversion_finished:
            if merge_session is not None:
                merge_session.abort()
            batch_ui.stop()
        if coordinator:
            coordinator.stop()

    failed_count = sum(not result for result in results)
    merge_failed = merge_commit_failed
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
    if batch_ui.skipped_files:
        batch_ui.print_skipped_list()
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
    yes: bool = False,
    no: bool = False,
    output_dir: str | os.PathLike[str] | None = None,
    merge: str | os.PathLike[str] | None = None,
    stdout: bool = False,
    confirm: bool = False,
    include_gitignored: bool = False,
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
    if yes and no:
        raise ValueError("yes cannot be combined with no")
    if yes and skip_existing:
        raise ValueError("yes cannot be combined with skip_existing")
    include_patterns = _validated_patterns(include, "include")
    exclude_patterns = _validated_patterns(exclude, "exclude")
    namespace = argparse.Namespace(
        files=[os.fspath(path) for path in files],
        include=include_patterns,
        exclude=exclude_patterns,
        overwrite=overwrite,
        skip_existing=skip_existing,
        yes=yes,
        no=no,
        output_dir=os.fspath(output_dir) if output_dir is not None else None,
        merge=os.fspath(merge) if merge is not None else None,
        stdout=stdout,
        confirm=confirm,
        include_gitignored=include_gitignored,
        coordinator=False,
        context_worker=False,
        right_click=False,
    )
    return run_batch(namespace)


def _validated_patterns(patterns: Sequence[str], flag: str) -> list[str]:
    from ..core.filters import compile_cli_filters

    try:
        if flag == "include":
            compile_cli_filters(patterns, ())
        else:
            compile_cli_filters((), patterns)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{flag} invalid filter pattern: {exc}") from exc
    return list(patterns)
