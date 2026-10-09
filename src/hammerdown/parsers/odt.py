from __future__ import annotations

import logging
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from hammerdown.parsers.math import mathml_to_latex, xml_name

logger = logging.getLogger("hammerdown")

ODF_NS = {
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}


def _render_node(
    node: ET.Element,
    archive: zipfile.ZipFile,
    output_dir: Path,
    stem: str,
    images: dict[str, str],
) -> list[str | tuple[str, str]]:
    tag = xml_name(node)
    if tag == "object":
        href = unquote(node.attrib.get(f"{{{ODF_NS['xlink']}}}href", "").rstrip("/"))
        if not href:
            return []
        try:
            math_root = ET.fromstring(archive.read(f"{href}/content.xml"))
        except (KeyError, ET.ParseError):
            return []
        if xml_name(math_root) != "math":
            return []
        return [("math", mathml_to_latex(math_root).strip())]
    if tag == "image":
        href = unquote(node.attrib.get(f"{{{ODF_NS['xlink']}}}href", ""))
        if not href:
            return []
        if href not in images:
            try:
                image_data = archive.read(href)
            except KeyError:
                return []
            extension = Path(href).suffix.lower()
            if not extension:
                return []
            image_dir = output_dir / "images"
            image_dir.mkdir(parents=True, exist_ok=True)
            image_name = f"img_{stem}_{len(images):03d}{extension}"
            (image_dir / image_name).write_bytes(image_data)
            images[href] = f"![Image](images/{image_name})"
        return [images[href]]
    if tag == "s":
        count = int(node.attrib.get(f"{{{ODF_NS['text']}}}c", "1"))
        return [" " * max(1, count)]
    if tag == "tab":
        return ["\t"]
    if tag == "line-break":
        return ["\n"]

    parts: list[str | tuple[str, str]] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        parts.extend(_render_node(child, archive, output_dir, stem, images))
        if child.tail:
            parts.append(child.tail)
    return parts


def _render_paragraph(
    element: ET.Element,
    archive: zipfile.ZipFile,
    output_dir: Path,
    stem: str,
    images: dict[str, str],
) -> str:
    parts = _render_node(element, archive, output_dir, stem, images)
    has_text = any(isinstance(part, str) and part.strip() for part in parts)
    rendered = []
    display = xml_name(element) == "h"
    for part in parts:
        if isinstance(part, tuple):
            delimiter = "$$" if display or not has_text else "$"
            rendered.append(f"{delimiter}{part[1]}{delimiter}")
        else:
            rendered.append(part)
    text = "".join(rendered).strip()
    if xml_name(element) == "h" and text:
        level = min(6, max(1, int(element.attrib.get(f"{{{ODF_NS['text']}}}outline-level", "1"))))
        return f"{'#' * level} {text}"
    return text


def _render_table(
    table: ET.Element,
    archive: zipfile.ZipFile,
    output_dir: Path,
    stem: str,
    images: dict[str, str],
) -> list[str]:
    rows = table.findall(".//table:table-row", ODF_NS)
    lines: list[str] = []
    for row_index, row in enumerate(rows):
        cells = [child for child in row if xml_name(child) in {"table-cell", "covered-table-cell"}]
        rendered_cells = []
        for cell in cells:
            paragraphs = [
                _render_paragraph(child, archive, output_dir, stem, images)
                for child in cell
                if xml_name(child) in {"p", "h"}
            ]
            rendered_cells.append("<br>".join(text for text in paragraphs if text).replace("|", "\\|"))
        lines.append(f"| {' | '.join(rendered_cells)} |")
        if row_index == 0:
            lines.append(f"| {' | '.join(['---'] * len(rendered_cells))} |")
    if lines:
        lines.append("")
    return lines


def convert_odt(odt_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        with zipfile.ZipFile(odt_path) as archive:
            root = ET.fromstring(archive.read("content.xml"))
            body = root.find(".//office:body/office:text", ODF_NS)
            if body is None:
                logger.error("ODT document has no office:text body")
                return None, 0

            output_dir = Path(out_dir)
            stem = Path(odt_path).stem
            images: dict[str, str] = {}
            lines: list[str] = []
            try:
                styles = ET.fromstring(archive.read("styles.xml"))
            except KeyError:
                styles = None
            if styles is not None:
                for image in styles.findall(".//draw:image", ODF_NS):
                    for part in _render_node(image, archive, output_dir, stem, images):
                        if isinstance(part, str) and part not in lines:
                            lines.append(part)

            def render_block(element: ET.Element) -> None:
                tag = xml_name(element)
                if tag in {"p", "h"}:
                    text = _render_paragraph(element, archive, output_dir, stem, images)
                    if text:
                        lines.append(text)
                elif tag == "table":
                    lines.extend(_render_table(element, archive, output_dir, stem, images))
                elif tag == "list-item":
                    start = len(lines)
                    for child in element:
                        render_block(child)
                    if len(lines) > start:
                        lines[start] = f"- {lines[start]}"
                else:
                    for child in element:
                        render_block(child)

            for element in body:
                render_block(element)
            return "\n\n".join(lines), len(images)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        logger.error("ODT conversion failed: %s", exc)
        return None, 0
