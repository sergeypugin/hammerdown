from __future__ import annotations

from dataclasses import dataclass
import html
from xml.etree import ElementTree as ET


_CHART_NS = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


@dataclass
class _Series:
    kind: str
    name: str
    categories: list[str]
    values: dict[int, float]


def _cache_values(parent: ET.Element, cache_tag: str) -> dict[int, str]:
    cache = parent.find(f".//{_CHART_NS}{cache_tag}")
    if cache is None:
        return {}
    values = {}
    for point in cache.findall(f"{_CHART_NS}pt"):
        index = int(point.get("idx", "0"))
        values[index] = point.findtext(f"{_CHART_NS}v", "")
    return values


def _chart_series(chart: ET.Element, categories: list[str]) -> list[_Series]:
    series_data = []
    for chart_type in chart.iter():
        kind = chart_type.tag.rsplit("}", 1)[-1]
        if kind not in {"barChart", "lineChart"}:
            continue
        for series_index, series in enumerate(chart_type.findall(f"{_CHART_NS}ser")):
            values_element = series.find(f"{_CHART_NS}val")
            if values_element is None:
                continue
            values_text = _cache_values(values_element, "numCache")
            values: dict[int, float] = {}
            for index, value in values_text.items():
                try:
                    values[index] = float(value)
                except ValueError:
                    continue
            if not values:
                continue

            series_categories = categories
            category_element = series.find(f"{_CHART_NS}cat")
            if category_element is not None:
                categories_text = _cache_values(category_element, "strCache")
                if not categories_text:
                    categories_text = _cache_values(category_element, "numCache")
                if categories_text:
                    series_categories = [categories_text.get(index, "") for index in range(max(categories_text) + 1)]
            name = series.findtext(f"{_CHART_NS}tx/{_CHART_NS}v", "")
            if not name:
                name = series.findtext(f"{_CHART_NS}tx/.//{_CHART_NS}v"
, "")
            series_data.append(_Series(kind, name or f"Series {series_index + 1}", series_categories, values))
    return series_data


def render_chart_svg(chart_data: bytes) -> tuple[str, str] | None:
    try:
        root = ET.fromstring(chart_data)
    except ET.ParseError:
        return None

    title = "Chart"
    title_node = root.find(f".//{_CHART_NS}title")
    if title_node is not None:
        title = "".join(title_node.itertext()).strip() or title
    categories: list[str] = []
    category_node = root.find(f".//{_CHART_NS}barChart/{_CHART_NS}ser/{_CHART_NS}cat")
    if category_node is None:
        category_node = root.find(f".//{_CHART_NS}lineChart/{_CHART_NS}ser/{_CHART_NS}cat")
    if category_node is not None:
        category_values = _cache_values(category_node, "strCache")
        if not category_values:
            category_values = _cache_values(category_node, "numCache")
        categories = [category_values.get(index, "") for index in range(max(category_values, default=-1) + 1)]
    series = _chart_series(root, categories)
    if not series:
        return None
    if not categories:
        categories = [str(index + 1) for index in range(max(max(item.values) for item in series) + 1)]

    width, height = 960, 520
    left, top, right, bottom = 78, 72, 30, 105
    plot_width, plot_height = width - left - right, height - top - bottom
    maximum = max(value for item in series for value in item.values.values())
    maximum = maximum if maximum > 0 else 1.0
    palette = ["#4472C4", "#ED7D31", "#70AD47", "#A5A5A5", "#FFC000"]
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    output.append('<rect width="100%" height="100%" fill="white"/>')
    output.append(f'<text x="{width / 2}" y="30" text-anchor="middle" font-family="sans-serif" font-size="18">{html.escape(title)}</text>')
    for tick in range(6):
        y = top + plot_height * tick / 5
        value = maximum * (5 - tick) / 5
        output.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#dddddd"/>')
        output.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.3g}</text>')
    output.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#555"/>')
    output.append(f'<line x1="{left}" y1="{top + plot_height}" x2="{width - right}" y2="{top + plot_height}" stroke="#555"/>')

    category_count = max(len(categories), 1)
    group_width = plot_width / category_count
    bar_series = [item for item in series if item.kind == "barChart"]
    line_series = [item for item in series if item.kind == "lineChart"]
    bar_width = group_width * 0.72 / max(len(bar_series), 1)
    for series_index, item in enumerate(bar_series):
        for index in range(category_count):
            value = item.values.get(index, 0.0)
            bar_height = value / maximum * plot_height
            x = left + index * group_width + group_width * 0.14 + series_index * bar_width
            y = top + plot_height - bar_height
            output.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{palette[series_index % len(palette)]}"/>')
    for series_index, item in enumerate(line_series):
        points = []
        for index in range(category_count):
            value = item.values.get(index, 0.0)
            x = left + (index + 0.5) * group_width
            y = top + plot_height - value / maximum * plot_height
            points.append(f"{x:.1f},{y:.1f}")
        color = palette[(series_index + len(bar_series)) % len(palette)]
        output.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3"/>')
    for index, category in enumerate(categories[:category_count]):
        x = left + (index + 0.5) * group_width
        output.append(f'<text x="{x:.1f}" y="{top + plot_height + 22}" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(category)}</text>')
    legend_y = height - 24
    legend_x = left
    for index, item in enumerate(series):
        color = palette[index % len(palette)]
        output.append(f'<rect x="{legend_x}" y="{legend_y - 11}" width="12" height="12" fill="{color}"/>')
        output.append(f'<text x="{legend_x + 17}" y="{legend_y}" font-family="sans-serif" font-size="12">{html.escape(item.name)}</text>')
        legend_x += 130 + len(item.name) * 6
    output.append("</svg>")
    return title, "\n".join(output)
