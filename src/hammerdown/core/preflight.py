from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .discovery import DiscoveryResult, _is_text_file, discover_paths, discover_tree
from .estimates import describe
from .path_utils import normalize_path
from .resources import token_count
from .run_models import ResolvedInput, ResolvedInputs
from ..parsers.format_registry import FORMAT_SPECS


@dataclass(frozen=True)
class TokenSummary:
    exact: int = 0
    estimated: int = 0
    unknown: int = 0
    unsupported: int = 0
    errors: int = 0
    markdown_tokens: str = "unavailable"


@dataclass(frozen=True)
class TimeSummary:
    lower_seconds: float = 0.0
    upper_seconds: float | None = 0.0
    unknown_files: int = 0
    confidence: str = "high"
    basis: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructureSummary:
    entries: tuple[str, ...] = ()
    displayed_count: int = 0
    completed_count: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class RiskSummary:
    eligible_files: int = 0
    estimated_seconds: float = 0.0
    confirmation_required: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightEntry:
    input_index: int
    path: str
    identity: str
    category: str | None
    status: str = "selected"
    reason: str | None = None


@dataclass(frozen=True)
class PreflightReport:
    resolved_inputs: ResolvedInputs
    entries: tuple[PreflightEntry, ...]
    tokens: TokenSummary
    time: TimeSummary
    structure: StructureSummary
    risk: RiskSummary
    errors: tuple[tuple[str, str], ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def successful(self) -> bool:
        return not self.errors


def _text_tokens(path: Path) -> int | None:
    if not path.is_file() or not _is_text_file(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
        count = token_count(text)
        if text and count == 0:
            return None
        return count
    except (OSError, UnicodeError):
        return None


def _known_format(path: Path) -> bool:
    return any(spec.extension == path.suffix.lower() for spec in FORMAT_SPECS)


def _build_tokens(entries: Sequence[PreflightEntry]) -> TokenSummary:
    exact = estimated = unknown = unsupported = errors = 0
    for entry in entries:
        if entry.status != "selected":
            continue
        path = Path(entry.path)
        if not path.is_file():
            errors += 1
            continue
        count = _text_tokens(path)
        if count is not None:
            exact += count
        elif _known_format(path):
            try:
                estimated += max(1, path.stat().st_size // 4)
            except OSError:
                errors += 1
        else:
            unsupported += 1
    return TokenSummary(exact, estimated, unknown, unsupported, errors)


def _build_time(entries: Sequence[PreflightEntry]) -> TimeSummary:
    lower = 0.0
    unknown = 0
    basis: list[str] = []
    for entry in entries:
        if entry.status != "selected":
            continue
        estimate, _ = describe(Path(entry.path))
        if estimate is None:
            unknown += 1
        else:
            lower += estimate
            basis.append(f"{Path(entry.path).name}={estimate:.1f}s")
    if unknown:
        return TimeSummary(lower, None, unknown, "low", tuple(basis))
    return TimeSummary(lower, lower, 0, "estimated" if lower else "high", tuple(basis))


def build_preflight_report(
    raw_paths: Sequence[str],
    discovery: DiscoveryResult,
    *,
    structure_limit: int = 100,
) -> PreflightReport:
    resolved: list[ResolvedInput] = []
    for index, raw in enumerate(raw_paths):
        try:
            path = Path(normalize_path(raw)).resolve()
        except (OSError, ValueError):
            continue
        resolved.append(ResolvedInput(f"local:{path}#{index}", raw, path))

    entries = [
        PreflightEntry(index, target.path, f"local:{Path(target.path).resolve()}", target.category)
        for index, target in enumerate(discovery.targets)
    ]
    offset = len(entries)
    entries.extend(
        PreflightEntry(index, path, f"error:{path}", None, "error", reason)
        for index, (path, reason) in enumerate(discovery.errors, offset)
    )
    skipped = tuple((item.path, item.reason) for item in discovery.skipped)
    errors = tuple(discovery.errors)
    all_paths = sorted(
        {entry.path for entry in entries} | {path for path, _ in skipped} | {path for path, _ in errors},
        key=str.casefold,
    )
    shown = tuple(all_paths[:structure_limit])
    timing = _build_time(entries)
    eligible = sum(entry.status == "selected" for entry in entries)
    reasons = []
    if eligible > 20:
        reasons.append("more than 20 eligible files")
    if timing.lower_seconds > 60:
        reasons.append("estimated work exceeds one minute")
    return PreflightReport(
        ResolvedInputs(tuple(resolved)),
        tuple(entries),
        _build_tokens(entries),
        timing,
        StructureSummary(shown, len(shown), len(all_paths), len(all_paths) > structure_limit),
        RiskSummary(eligible, timing.lower_seconds, bool(reasons), tuple(reasons)),
        errors,
        skipped,
    )


def make_discovery(
    paths: Sequence[str],
    *,
    tree: bool,
    all_formats: bool,
    include_patterns=(),
    exclude_patterns=(),
    include_gitignored: bool = False,
) -> DiscoveryResult:
    if tree:
        return discover_tree(
            paths,
            all_formats=all_formats,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            include_gitignored=include_gitignored,
        )
    return discover_paths(
        paths,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        include_gitignored=include_gitignored,
    )


def render_preflight_report(
    report: PreflightReport,
    *,
    tokens: bool,
    timing: bool,
    structure: bool,
) -> str:
    lines: list[str] = []
    if structure:
        lines.append("Structure")
        lines.extend(f"  {path}" for path in report.structure.entries)
        if report.structure.truncated:
            lines.append(f"  ... {report.structure.completed_count - report.structure.displayed_count} more entries")
        lines.append(
            f"  entries: {report.structure.completed_count}; displayed: {report.structure.displayed_count}"
        )
    if tokens:
        value = report.tokens
        lines.extend(
            [
                "Tokens",
                f"  exact source tokens: {value.exact}",
                f"  estimated binary tokens: {value.estimated}",
                f"  unknown: {value.unknown}",
                f"  unsupported: {value.unsupported}",
                f"  operational errors: {value.errors}",
                f"  generated Markdown tokens: {value.markdown_tokens}",
            ]
        )
    if timing:
        value = report.time
        upper = "unknown" if value.upper_seconds is None else f"{value.upper_seconds:.1f}s"
        lines.extend(
            [
                "Time",
                f"  range: {value.lower_seconds:.1f}s - {upper}",
                f"  confidence: {value.confidence}",
                f"  unknown estimates: {value.unknown_files}",
            ]
        )
    lines.append(
        f"Risk: {'confirmation required' if report.risk.confirmation_required else 'no confirmation required'}"
    )
    lines.extend(f"Error: {Path(path).name}: {reason}" for path, reason in report.errors)
    return "\n".join(lines) + "\n"
