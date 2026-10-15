from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Sequence

from hammerdown import SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS
from hammerdown.core import convert_file, get_conversion_estimate_seconds
from hammerdown.ipc import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.utils import BatchUI, format_duration, normalize_path

logger = logging.getLogger("hammerdown")


def _expand_paths(
    paths: Sequence[str],
    excluded_dir: Path | None = None,
) -> list[tuple[str, str | None]]:
    targets: list[tuple[str, str | None]] = []
    seen_paths: set[Path] = set()
    excluded_dir = excluded_dir.resolve() if excluded_dir is not None else None

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
                    if f.startswith("~$") or f.startswith("."):
                        continue
                    try:
                        file_path = (Path(root) / f).resolve()
                        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS and file_path not in seen_paths:
                            seen_paths.add(file_path)
                            targets.append((str(file_path), None))
                    except OSError:
                        continue
        elif p.is_file():
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                targets.append((str(p), "unsupported format"))
            elif p not in seen_paths:
                seen_paths.add(p)
                targets.append((str(p), None))

    return targets


def _merge_converted_files(
    files: Sequence[str],
    results: Sequence[bool],
    merge_target: str,
    overwrite_sources: bool = False,
    output_paths: Sequence[Path] | None = None,
    skip_existing: bool = False,
) -> bool:
    merged_sections: list[str] = []
    for index, (file_path, succeeded) in enumerate(zip(files, results)):
        if not succeeded:
            continue
        source = Path(normalize_path(file_path))
        stem = source.stem
        ext_clean = source.suffix.lower().lstrip(".")
        out_md_name = f"hm_{stem}_{ext_clean}.md" if ext_clean else f"hm_{stem}.md"
        out_md = output_paths[index] if output_paths is not None else source.parent / out_md_name
        if overwrite_sources and source.suffix.lower() in TEXT_EXTENSIONS:
            out_md = source
        if out_md.is_file():
            content = out_md.read_text(encoding="utf-8").strip()
            section = f"# {source.name}\n\n{content}" if content else f"# {source.name}"
            merged_sections.append(section)

    if not merged_sections:
        return False

    dest = Path(normalize_path(merge_target))
    if skip_existing and dest.exists():
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n\n".join(merged_sections) + "\n", encoding="utf-8", newline="\n")
    return True


def _process_single_file(args_tuple: tuple[str, bool, bool, bool, bool]) -> bool:
    file_path, in_place, quiet, overwrite, skip_existing = args_tuple
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if quiet:
        logger.setLevel(logging.ERROR)
    return convert_file(
        file_path,
        in_place=in_place,
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


def run_batch(args: argparse.Namespace) -> int:
    raw_files = args.files
    if not raw_files:
        logger.info("No supported documents found to convert")
        return 0

    output_dir = getattr(args, "output_dir", None)
    output_root = Path(output_dir).resolve() if output_dir else None
    if output_root is not None and output_root.exists() and not output_root.is_dir():
        logger.error("output directory path is not a directory: %s", output_root)
        return 1
    targets = _expand_paths(raw_files, excluded_dir=output_root)
    if not targets:
        logger.info("No supported documents found to convert")
        return 0

    targets.sort(key=lambda item: item[0].lower())
    try:
        output_paths = (
            _output_paths(raw_files, targets, output_root)
            if output_root is not None
            else [Path(path).parent / f"hm_{Path(path).stem}_{Path(path).suffix.lower().lstrip('.')}.md" for path, _ in targets]
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    files = [path for path, error in targets if error is None]
    ui_files = [path for path, _ in targets]

    use_ipc = args.coordinator or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
    options = {
        "in_place": args.in_place,
        "overwrite": args.overwrite,
        "skip_existing": args.skip_existing,
        "quiet": args.quiet,
    }

    if use_ipc and try_delegate_to_coordinator(files, options):
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

        files = coordinator.collect_files(files, assembly_timeout=0.35)
    elif use_ipc:
        return 0

    estimates = [
        get_conversion_estimate_seconds(Path(path)) if error is None else None
        for path, error in targets
    ]
    started_at = time.monotonic()
    results: list[bool] = []
    total_tokens = 0
    conversion_finished = False
    batch_ui = BatchUI(ui_files, quiet=args.quiet, estimates=estimates)

    if batch_ui.can_redraw:
        batch_ui.start()

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
            if args.skip_existing and output_path.exists() and output_path != f_path:
                status_info = f"skipped, existing output: {output_path.name}"
            elif args.overwrite and extension in TEXT_EXTENSIONS:
                status_info = "overwritten"
            elif args.overwrite:
                status_info = "overwrite ignored (binary file)"

            def on_progress(current: int, total: int, unit: str = "pages") -> None:
                batch_ui.update_progress(idx, current, total, unit)

            def on_complete(success: bool, dur: float, imgs: int, tokens: int) -> None:
                nonlocal total_tokens
                total_tokens += tokens
                batch_ui.complete_file(idx, success, format_duration(dur), imgs, tokens, status_info)

            res = convert_file(
                f_path,
                in_place=args.in_place,
                overwrite=args.overwrite,
                skip_existing=args.skip_existing,
                progress_callback=on_progress,
                completion_callback=on_complete,
                batch_mode=True,
                target_dir=output_path.parent if output_root is not None else None,
            )
            results.append(res)
        conversion_finished = True
    finally:
        if not conversion_finished:
            batch_ui.stop()
        if coordinator:
            coordinator.stop()

    failed_count = results.count(False)
    if args.merge and any(results):
        successful_indexes = [index for index, ((_, error), result) in enumerate(zip(targets, results)) if error is None and result]
        successful_files = [targets[index][0] for index in successful_indexes]
        successful_outputs = [output_paths[index] for index in successful_indexes]
        merge_target = Path(normalize_path(args.merge))
        merge_was_existing = args.skip_existing and merge_target.exists()
        merge_completed = _merge_converted_files(
            successful_files,
            [True] * len(successful_files),
            args.merge,
            overwrite_sources=args.overwrite,
            output_paths=successful_outputs,
            skip_existing=args.skip_existing,
        )
        if merge_was_existing:
            batch_ui.add_summary_message(f"Merge skipped: {merge_target.name} already exists")
        elif merge_completed:
            batch_ui.add_summary_message(f"Merged {len(successful_files)} documents into {merge_target.name}")

    batch_ui.finish()

    should_wait = (
        os.name == "nt"
        and not args.quiet
        and (
            args.coordinator
            or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
            or getattr(sys, "frozen", False)
        )
    )
    if should_wait:
        try:
            if batch_ui.errors:
                choice = input("\nType `e` and press Enter to extend the error list, or press Enter to exit: ")
                if choice.strip().lower() == "e":
                    batch_ui.print_error_list()
                    input("\nPress Enter to exit... ")
            else:
                input("\nPress Enter to exit... ")
        except (EOFError, KeyboardInterrupt):
            pass

    return 1 if failed_count else 0
