from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Sequence

from . import convert_file
from .merge import merge_root_for_inputs, render_merged_markdown
from .formatting import format_duration

logger = logging.getLogger("hammerdown")

# Only these formats are already plain text, so their byte size is a usable
# proxy for the size of the converted Markdown. Binary containers (PDF, DOCX,
# XLSX) are mostly compressed payload and metadata, and their size says nothing
# about the text that comes out of them.
TEXT_TOKEN_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".log", ".csv"})


def text_source_count(paths: Sequence[str]) -> int:
    return sum(1 for path in paths if Path(path).suffix.lower() in TEXT_TOKEN_EXTENSIONS)


def approximate_tokens(paths: Sequence[str]) -> int | None:
    """Approximate output tokens for text sources, or ``None`` when there are none."""
    total_bytes = 0
    counted = 0
    try:
        for path in paths:
            file_path = Path(path)
            if file_path.suffix.lower() not in TEXT_TOKEN_EXTENSIONS:
                continue
            total_bytes += file_path.stat().st_size
            counted += 1
    except OSError:
        return None
    if not counted:
        return None
    return max(1, total_bytes // 4)


def confirm_stdout(paths: Sequence[str], estimates: Sequence[float | None]) -> bool:
    """Show a preflight estimate and continue only on an explicit ``y`` answer."""
    token_estimate = approximate_tokens(paths)
    known_estimates = [value for value in estimates if value is not None]
    seconds = sum(known_estimates) if known_estimates else (0.0 if not paths else None)
    duration_text = f"~{format_duration(seconds)}" if seconds is not None else "unknown"
    file_label = "file" if len(paths) == 1 else "files"
    if token_estimate is None:
        token_clause = ""
    elif text_source_count(paths) < len(paths):
        token_clause = f", ~{token_estimate:_} tokens from text sources"
    else:
        token_clause = f", ~{token_estimate:_} tokens"
    print(
        f"Preflight: {len(paths)} {file_label}{token_clause}, estimated time {duration_text}.",
        file=sys.stderr,
    )
    if not sys.stdin.isatty():
        print("Confirmation requires interactive stdin; cancelled.", file=sys.stderr)
        return False
    while True:
        try:
            print("Continue and write Markdown to stdout? [y/n] ", end="", file=sys.stderr, flush=True)
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


def run_stdout_conversion(files: Sequence[str], raw_inputs: Sequence[str]) -> int:
    """Stream a merged Markdown document to stdout without writing files."""
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
        # If there's only a single file, output just its raw markdown for clean piping
        if len(converted) == 1:
            sys.stdout.write(converted[0][1])
        else:
            root = merge_root_for_inputs(raw_inputs, [Path(path) for path, _ in converted])
            sys.stdout.write(render_merged_markdown(converted, root))
    return 1 if failed else 0
