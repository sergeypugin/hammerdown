from __future__ import annotations

import os
from typing import Any, Collection, Iterable, Sequence

from pathspec import GitIgnoreSpec, PathSpec

_QUOTE_CHARS = frozenset({"'", '"'})
_PRESERVED_ESCAPES = frozenset({"(", ")", ",", "!", "#"})


class OrderedFilterValues(list[str]):
    """Argparse values carrying the original include/exclude operation queue."""

    def __init__(self, values: Iterable[str] = ()) -> None:
        super().__init__(values)
        self.filter_queue: list[tuple[str, str]] | None = None


class _OrderedFilterSpec(PathSpec):
    patterns: Sequence[Any]

    def __init__(self, operations: Sequence[tuple[str, str]]) -> None:
        self.operations = tuple((kind, GitIgnoreSpec.from_lines([pattern])) for kind, pattern in operations)
        self.has_include = any(kind == "include" for kind, _ in operations)
        # Discovery treats any PathSpec with truthy .patterns as having active filters.
        self.patterns = list(self.operations)

    def match_file(
        self,
        file: str | os.PathLike[str],
        separators: Collection[str] | None = None,
    ) -> bool:
        allowed = not self.has_include
        for kind, spec in self.operations:
            if spec.match_file(file, separators=separators):
                allowed = kind == "include"
        return allowed




def _preserves_escape(character: str) -> bool:
    return character in _PRESERVED_ESCAPES or character.isspace()


def _split_filter_value(value: str) -> list[str]:
    tokens: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    token_started = False
    index = 0

    def flush() -> None:
        nonlocal token_started
        if token_started and buffer:
            tokens.append("".join(buffer))
        buffer.clear()
        token_started = False

    while index < len(value):
        character = value[index]
        if character == "\\":
            buffer.append(character)
            token_started = True
            if index + 1 < len(value):
                buffer.append(value[index + 1])
                index += 2
            else:
                index += 1
            continue

        if quote is not None:
            if character == quote:
                quote = None
            else:
                buffer.append(character)
            token_started = True
            index += 1
            continue

        if character in _QUOTE_CHARS:
            quote = character
            token_started = True
        elif character == "," or character.isspace():
            flush()
        else:
            buffer.append(character)
            token_started = True
        index += 1

    if quote is not None:
        raise ValueError("unterminated quote in filter pattern")

    flush()
    return tokens


def normalize_filter_pattern(pattern: str) -> str:
    """Normalize a CLI pattern for GitWildMatch matching on every platform."""
    normalized = pattern.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in _QUOTE_CHARS:
        normalized = normalized[1:-1]

    result: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character == "/":
            if not result or result[-1] != "/":
                result.append(character)
            index += 1
            continue

        if character != "\\":
            result.append(character)
            index += 1
            continue

        end = index
        while end < len(normalized) and normalized[end] == "\\":
            end += 1
        next_character = normalized[end] if end < len(normalized) else None

        if end - index == 1 and next_character is not None and _preserves_escape(next_character):
            result.extend(("\\", next_character))
            index = end + 1
            continue

        if not result or result[-1] != "/":
            result.append("/")
        index = end

    normalized = "".join(result)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def parse_pattern_string(value: str) -> list[str]:
    """Split one CLI value into normalized GitWildMatch patterns."""
    patterns: list[str] = []
    for token in _split_filter_value(value):
        normalized = normalize_filter_pattern(token)
        if normalized:
            patterns.append(normalized)
    return patterns


def normalize_filter_patterns(patterns: Iterable[str]) -> list[str]:
    """Normalize CLI patterns and remove duplicates without changing their order."""
    results: list[str] = []
    seen: set[str] = set()
    for raw in patterns:
        for parsed in parse_pattern_string(raw):
            if parsed not in seen:
                seen.add(parsed)
                results.append(parsed)
    return results


def compile_cli_filters(
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> tuple[PathSpec, PathSpec]:
    """Compile CLI filters, honoring an argparse-preserved operation queue."""
    queued = getattr(include, "filter_queue", None) or getattr(exclude, "filter_queue", None)
    if queued:
        operations: list[tuple[str, str]] = []
        for kind, raw in queued:
            for pattern in parse_pattern_string(raw):
                operations.append((kind, pattern))
        if operations:
            return _OrderedFilterSpec(operations), GitIgnoreSpec.from_lines([])

    include_patterns = normalize_filter_patterns(include)
    exclude_patterns = normalize_filter_patterns(exclude)

    return (
        GitIgnoreSpec.from_lines(include_patterns),
        GitIgnoreSpec.from_lines(exclude_patterns),
    )
