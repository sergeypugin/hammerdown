from __future__ import annotations

from collections.abc import Iterable

from hammerdown.parsers.markdown_render import render_markdown_table


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

    active_columns = [
        index
        for index in range(width)
        if any(not _is_empty(matrix[row][index]) for row in range(len(matrix)))
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
    for column_group in groups(active_columns):
        sub_matrix = [[matrix[row][column] for column in column_group] for row in range(len(matrix))]
        col_active_rows = [
            row for row in range(len(matrix))
            if any(not _is_empty(sub_matrix[row][col_idx]) for col_idx in range(len(column_group)))
        ]

        for row_group in groups(col_active_rows):
            region = [sub_matrix[row] for row in row_group]
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
            table_rows = [
                [str(value).strip() if not _is_empty(value) else "" for value in row]
                for row in region
            ]
            rendered.append("\n".join(render_markdown_table(table_rows)))

    return rendered
