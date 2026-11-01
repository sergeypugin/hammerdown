from __future__ import annotations

from typing import Iterable, Sequence

from pathspec import GitIgnoreSpec

_QUOTE_CHARS = frozenset({"'", '"'})
_PRESERVED_ESCAPES = frozenset({"(", ")", ",", "!", "#"})


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
) -> tuple[GitIgnoreSpec, GitIgnoreSpec]:
    """Compile include and exclude groups with Gitingest-compatible semantics.

    Identical patterns are removed from the exclude group. During discovery,
    exclude matches still take priority over include matches.
    """
    include_patterns = normalize_filter_patterns(include)
    exclude_patterns = normalize_filter_patterns(exclude)

    include_set = set(include_patterns)
    final_exclude = [pattern for pattern in exclude_patterns if pattern not in include_set]

    return (
        GitIgnoreSpec.from_lines(include_patterns),
        GitIgnoreSpec.from_lines(final_exclude),
    )
