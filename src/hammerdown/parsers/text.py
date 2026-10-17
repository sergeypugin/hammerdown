from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Callable

from hammerdown.parsers.office.spreadsheet import convert_xlsx
from hammerdown.parsers.tables import render_table_regions
from hammerdown.utils import get_images_dir_name

ProgressCallback = Callable[[int, int, str], None]


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def convert_txt_or_md(
    file_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    raw = Path(file_path).read_bytes()
    text = _decode_bytes(raw)

    # Extract base64 images from Markdown/text
    # Pattern: data:image/(png|jpeg|jpg|webp|gif);base64,[data]
    img_dir_name = get_images_dir_name(file_path)
    img_dir = Path(out_dir) / img_dir_name
    saved_imgs = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal saved_imgs
        mime_subtype = match.group(1).lower()
        ext = mime_subtype.split("+", 1)[0]
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
    pattern = r"data:image/([a-zA-Z0-9.+-]+);base64,([a-zA-Z0-9+/=]+)"
    processed_text = re.sub(pattern, replacer, text)

    if progress_callback:
        progress_callback(1, 1, "file")

    return processed_text, saved_imgs


def convert_csv(
    csv_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    if zipfile.is_zipfile(csv_path):
        try:
            result = convert_xlsx(csv_path, out_dir, progress_callback=progress_callback)
            if result[0] is not None:
                return result
        except Exception:
            pass

    raw = Path(csv_path).read_bytes()
    text = _decode_bytes(raw)

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
    if progress_callback:
        progress_callback(1, 1, "rows" if not rows else f"{len(rows)} rows")
    if not rows:
        return "", 0

    return "\n\n".join(render_table_regions(rows)), 0


CONVERTERS = {
    ".csv": convert_csv,
    ".txt": convert_txt_or_md,
    ".md": convert_txt_or_md,
    ".log": convert_txt_or_md,
}
