from __future__ import annotations

import base64
import os
import re
import shutil
from pathlib import Path
from typing import Callable, cast

from bs4 import BeautifulSoup, NavigableString, Tag, PageElement

from hammerdown.path_utils import get_images_dir_name

ProgressCallback = Callable[[int, int, str], None]

# Matches an inline base64 image, e.g. data:image/png;base64,iVBORw0KGgo...
_DATA_IMAGE_RE = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,([a-zA-Z0-9+/=]+)$")


def _is_remote_or_absolute(src: str) -> bool:
    """Return True when an image src is not a plain relative local path.

    Remote URLs (https://, data:) and absolute paths (C:\\, /, //) are left as
    external references rather than being copied from disk.
    """
    lowered = src.strip().lower()
    return bool(
        lowered.startswith(("http://", "https://", "ftp://", "data:", "//"))
        or lowered.startswith(("/", "\\"))
        or (":" in lowered[1:3])
    )


def convert_html(
    file_path: str | os.PathLike[str],
    asset_dir: str | os.PathLike[str],
    images_dir_name: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    source_path = Path(file_path)
    if not source_path.is_file():
        return None, 0

    try:
        content = source_path.read_text(encoding="utf-8")
    except Exception:
        try:
            content = source_path.read_text(encoding="latin-1")
        except Exception:
            return None, 0

    soup = BeautifulSoup(content, "lxml")
    body = soup.find("body") or soup

    saved_images = 0
    img_dir_name = images_dir_name or get_images_dir_name(source_path)
    images_dir = Path(asset_dir) / img_dir_name
    source_dir = source_path.parent

    # Process images and prepare mapping
    img_map: dict[str, str] = {}
    if isinstance(body, Tag):
        for img in body.find_all("img"):
            src_val = img.get("src")
            if not src_val or not isinstance(src_val, str):
                continue

            # Inline base64 image (data:image/...;base64,...) is written to disk
            # instead of being kept as a huge data URI in the Markdown. This
            # happens for Google Docs exports that inline every picture.
            data_match = _DATA_IMAGE_RE.match(src_val.strip())
            if data_match:
                sub_type = data_match.group(1).split("+", 1)[0] or "png"
                try:
                    img_bytes = base64.b64decode(data_match.group(2))
                except Exception:
                    continue
                images_dir.mkdir(parents=True, exist_ok=True)
                image_name = f"img_{saved_images:03d}.{sub_type}"
                (images_dir / image_name).write_bytes(img_bytes)
                img_map[src_val] = f"{img_dir_name}/{image_name}"
                saved_images += 1
                continue

            # Skip remote or absolute URLs (e.g. Google-hosted images). These
            # are left untouched in the Markdown instead of being downloaded.
            if _is_remote_or_absolute(src_val):
                continue

            # Local image path (relative to the HTML file, e.g. images/foo.png)
            local_img_path = source_dir / src_val
            if local_img_path.is_file():
                images_dir.mkdir(parents=True, exist_ok=True)
                ext = local_img_path.suffix or ".png"
                image_name = f"img_{saved_images:03d}{ext}"
                shutil.copy2(local_img_path, images_dir / image_name)
                img_map[src_val] = f"{img_dir_name}/{image_name}"
                saved_images += 1

    # Convert HTML elements to Markdown
    def process_node(node: PageElement) -> str:
        if isinstance(node, NavigableString):
            return str(node)

        if not isinstance(node, Tag):
            return ""

        tag_name = node.name.lower()
        
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(tag_name[1])
            text = "".join(process_node(c) for c in node.children).strip()
            return f"\n\n{'#' * level} {text}\n\n"

        if tag_name == "p":
            text = "".join(process_node(c) for c in node.children).strip()
            if not text:
                return ""
            return f"\n\n{text}\n\n"

        if tag_name == "img":
            src_attr = node.get("src", "")
            src = src_attr if isinstance(src_attr, str) else ""
            alt_attr = node.get("alt", "")
            alt = alt_attr if isinstance(alt_attr, str) else ""
            mapped_src = img_map.get(src, src)
            return f"![{alt}]({mapped_src})"

        if tag_name in ["b", "strong"]:
            text = "".join(process_node(c) for c in node.children)
            return f"**{text}**" if text.strip() else text

        if tag_name in ["i", "em"]:
            text = "".join(process_node(c) for c in node.children)
            return f"*{text}*" if text.strip() else text

        if tag_name == "code":
            text = "".join(process_node(c) for c in node.children)
            return f"`{text}`"

        if tag_name == "pre":
            text = node.get_text()
            return f"\n\n```\n{text}\n```\n\n"

        if tag_name == "a":
            text = "".join(process_node(c) for c in node.children)
            href_attr = node.get("href", "")
            href = href_attr if isinstance(href_attr, str) else ""
            if href and text.strip():
                return f"[{text}]({href})"
            return text

        if tag_name == "ul":
            items = []
            for li in node.find_all("li", recursive=False):
                item_text = "".join(process_node(c) for c in li.children).strip()
                items.append(f"- {item_text}")
            return "\n\n" + "\n".join(items) + "\n\n"

        if tag_name == "ol":
            items = []
            for i, li in enumerate(node.find_all("li", recursive=False), 1):
                item_text = "".join(process_node(c) for c in li.children).strip()
                items.append(f"{i}. {item_text}")
            return "\n\n" + "\n".join(items) + "\n\n"

        if tag_name == "table":
            rows: list[list[str]] = []
            for tr in node.find_all("tr"):
                cells = [
                    "".join(process_node(c) for c in td.children).strip().replace("\n", " ")
                    for td in tr.find_all(["td", "th"])
                ]
                if cells:
                    rows.append(cells)
            
            if not rows:
                return ""

            # Build markdown table
            col_counts = [len(r) for r in rows]
            max_cols = max(col_counts) if col_counts else 0
            if max_cols == 0:
                return ""

            md_table: list[str] = []
            header = rows[0] + [""] * (max_cols - len(rows[0]))
            md_table.append("| " + " | ".join(header) + " |")
            md_table.append("| " + " | ".join(["---"] * max_cols) + " |")

            for row in rows[1:]:
                padded_row = row + [""] * (max_cols - len(row))
                md_table.append("| " + " | ".join(padded_row) + " |")

            return "\n\n" + "\n".join(md_table) + "\n\n"

        # Default: process children
        return "".join(process_node(c) for c in node.children)

    full_md = process_node(body)
    
    # Cleanup multiple newlines
    lines = full_md.split("\n")
    cleaned_lines: list[str] = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 1:
                cleaned_lines.append("")
        else:
            blank_count = 0
            cleaned_lines.append(line)

    result_md = "\n".join(cleaned_lines).strip() + "\n"
    return result_md, saved_images


CONVERTERS = {
    ".html": convert_html,
    ".htm": convert_html,
    ".gdoc": convert_html,
    ".gsheets": convert_html,
    ".gslides": convert_html,
    ".gfile": convert_html,
}
