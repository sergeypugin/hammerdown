from __future__ import annotations

from collections.abc import Iterable


def _is_empty(value: object) -> bool:
    return value is None or not str(value).strip()


def render_table_regions(rows: Iterable[Iterable[object]]) -> list[str]:
    matrix = [list(row) for row in rows]
    if not matrix:
        return []

    width = max((len(row) for row in matrix), default=0)
    if not width:
        return []
    matrix = [row + [None] * (width - len(row)) for row in matrix]

    active_rows = [index for index, row in enumerate(matrix) if any(not _is_empty(value) for value in row)]
    active_columns = [
        index
        for index in range(width)
        if any(not _is_empty(matrix[row][index]) for row in active_rows)
    ]

    def groups(indices: list[int]) -> list[list[int]]:
        result: list[list[int]] = []
        for index in indices:
            if not result or index != result[-1][-1] + 1:
                result.append([index])
            else:
                result[-1].append(index)
        return result

    rendered: list[str] = []
    for row_group in groups(active_rows):
        for column_group in groups(active_columns):
            region = [
                [matrix[row][column] for column in column_group]
                for row in row_group
            ]
            nonempty_count = sum(not _is_empty(value) for row in region for value in row)
            if nonempty_count < 2:
                continue

            while region and all(_is_empty(value) for value in region[0]):
                region.pop(0)
            while region and all(_is_empty(value) for value in region[-1]):
                region.pop()
            if not region:
                continue

            region_width = max(len(row) for row in region)
            region = [row + [None] * (region_width - len(row)) for row in region]
            header = [str(value).strip().replace("|", "\\|") if not _is_empty(value) else "" for value in region[0]]
            lines = [
                f"| {' | '.join(header)} |",
                f"| {' | '.join(['---'] * region_width)} |",
            ]
            for row in region[1:]:
                cells = [str(value).strip().replace("|", "\\|") if not _is_empty(value) else "" for value in row]
                lines.append(f"| {' | '.join(cells)} |")
            rendered.append("\n".join(lines))

    return rendered
