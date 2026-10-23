from __future__ import annotations

from pathlib import Path

from hammerdown.parsers.office import convert_xlsx
from hammerdown.parsers.tables import render_table_regions
from hammerdown.parsers.text import convert_csv


def test_table_regions_trim_margins_and_keep_internal_empty_cells() -> None:
    rows = [
        [None, "Name", "Middle", "Length", None, None],
        [None, "Ada", None, "3", None, None],
    ]

    assert render_table_regions(rows) == [
        "| Name | Middle | Length |\n| --- | --- | --- |\n| Ada |  | 3 |"
    ]


def test_csv_ignores_single_isolated_value_after_compact_table(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    source.write_text(
        "id;name;;;;;\n1;Ada;;;;;\n;;;;;;unrelated value\n",
        encoding="utf-8",
    )

    markdown, images = convert_csv(str(source), str(tmp_path))

    assert images == 0
    assert markdown == "| id | name |\n| --- | --- |\n| 1 | Ada |"


def test_xlsx_splits_distinct_blocks_and_uses_formula_when_cache_is_missing(tmp_path: Path) -> None:
    import openpyxl

    source = tmp_path / "blocks.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "left"
    sheet["B1"] = "value"
    sheet["A2"] = "row"
    sheet["B2"] = "=1+1"
    sheet["E1"] = "right"
    sheet["F1"] = "value"
    sheet["E2"] = "item"
    sheet["F2"] = "x"
    sheet["P100"].number_format = "0.00"
    workbook.save(source)

    markdown, images = convert_xlsx(str(source), str(tmp_path))

    assert markdown is not None
    assert images == 0
    assert "| left | value |\n| --- | --- |\n| row | =1+1 |" in markdown
    assert "| right | value |\n| --- | --- |\n| item | x |" in markdown
    assert "0.00" not in markdown


def test_parallel_tables_of_different_lengths_are_split_cleanly():
    rows = [
        ["A1", "B1", None, "X1", "Y1"],
        ["A2", "B2", None, "X2", "Y2"],
        ["A3", "B3", None, None, None],
        ["A4", "B4", None, None, None],
        ["A5", "B5", None, "Z1", "W1"],
        ["A6", "B6", None, "Z2", "W2"],
    ]
    tables = render_table_regions(rows)
    # Left table: A1..B6 (one continuous table)
    # Right tables: X1..Y2 and Z1..W2 (two separate tables)
    assert len(tables) == 3
    assert "| A1 | B1 |" in tables[0]
    assert "| A6 | B6 |" in tables[0]
    assert "| X1 | Y1 |" in tables[1]
    assert "| Z1 | W1 |" in tables[2]
