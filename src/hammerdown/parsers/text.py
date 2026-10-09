from __future__ import annotations

import base64
import csv
import io
import re
from pathlib import Path
import zipfile

from hammerdown.parsers.tables import render_table_regions
from hammerdown.utils import get_images_dir_name


def convert_txt_or_md(file_path: str, out_dir: str) -> tuple[str | None, int]:
    raw = Path(file_path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    # Extract base64 images from Markdown/text
    # Pattern: data:image/(png|jpeg|jpg|webp|gif);base64,[data]
    img_dir_name = get_images_dir_name(file_path)
    img_dir = Path(out_dir) / img_dir_name
    saved_imgs = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal saved_imgs
        ext = match.group(1)
        b64_data = match.group(2)
        try:
            img_bytes = base64.b64decode(b64_data)
            if not img_dir.exists():
                img_dir.mkdir(parents=True, exist_ok=True)

            img_name = f"embedded_img_{saved_imgs}.{ext}"
            (img_dir / img_name).write_bytes(img_bytes)
            saved_imgs += 1
            return f"{img_dir_name}/{img_name}"
        except Exception:
            return match.group(0)

    # Replace data URIs in Markdown image syntax or raw links
    # Matches: data:image/png;base64,iVBOR...
    pattern = r"data:image/([a-zA-Z]+);base64,([a-zA-Z0-9+/=]+)"
    processed_text = re.sub(pattern, replacer, text)

    return processed_text, saved_imgs


def convert_csv(csv_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(csv_path):
        try:
            import openpyxl  # type: ignore
            data = Path(csv_path).read_bytes()
            workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            formula_workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=True)
            blocks: list[str] = []
            for sheet in workbook.sheetnames:
                blocks.append(f"# Sheet: {sheet}")
                data_sheet = workbook[sheet]
                formula_sheet = formula_workbook[sheet]
                rows = []
                for data_row, formula_row in zip(data_sheet.iter_rows(), formula_sheet.iter_rows()):
                    row = []
                    for data_cell, formula_cell in zip(data_row, formula_row):
                        value = data_cell.value
                        if value is None and formula_cell.data_type == "f":
                            value = formula_cell.value
                        row.append(value)
                    rows.append(row)
                blocks.extend(render_table_regions(rows))
            workbook.close()
            formula_workbook.close()
            return "\n\n".join(blocks), 0
        except Exception:
            pass

    raw = Path(csv_path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        text = raw.decode("utf-8", errors="replace")

    sample = text[:2048]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        if ";" in sample and "," not in sample:
            delimiter = ";"
        elif "\t" in sample and "," not in sample:
            delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return "", 0

    return "\n\n".join(render_table_regions(rows)), 0


CONVERTERS = {
    ".csv": convert_csv,
    ".txt": convert_txt_or_md,
    ".md": convert_txt_or_md,
    ".log": convert_txt_or_md,
}
