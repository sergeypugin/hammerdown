# Python API Reference

`hammerdown` can be used directly as a Python library. You can run high-level document conversions or call individual parsers for specific formats.

## Quickstart

```python
import hammerdown

# Convert a file and save it to disk
result = hammerdown.convert_file("document.pdf")
if result:
    print(f"Wrote {result.output_path}")

# Or get the Markdown text directly in Python memory
markdown_text, image_count = hammerdown.to_markdown("document.docx")
print(markdown_text)
```

## High-Level Functions

### `to_markdown(file_path, target_dir=None, progress_callback=None)`

Converts any supported document to Markdown and extracts any embedded assets.

- `file_path` (`str | Path`): path to the source document
- `target_dir` (`str | Path | None`, optional): directory where extracted assets are written; defaults to the directory of the source file
- `progress_callback` (`Callable[[int, int, str], None] | None`, optional): callback invoked as units (pages, slides, sheets, elements) are converted, taking `(current, total, unit)`
- Returns: `tuple[str | None, int]` -- the generated Markdown string (or `None` on error) and the number of saved images

```python
from hammerdown import to_markdown

def log_progress(current: int, total: int, unit: str):
    print(f"Progress: {current}/{total} {unit}")

text, images = to_markdown("data/report.docx", target_dir="output", progress_callback=log_progress)
```

### `convert_file(...)`

Converts the document and writes the output file to disk. For example, `report.docx` produces `hm_report_docx.md` next to the source.

```python
convert_file(
    file_path,
    overwrite=False,
    skip_existing=False,
    progress_callback=None,
    completion_callback=None,
    batch_mode=False,
    target_dir=None,
    stdout=False,
    asset_dir=None,
    write_markdown=True,
) -> ConversionResult
```

- `file_path` (`str | Path`): path to the source document
- `overwrite` (`bool`, default `False`): rewrites plain-text sources (`.txt`, `.md`) in place instead of producing a copy; ignored with a warning for binary formats
- `skip_existing` (`bool`, default `False`): returns success without converting when the output file already exists
- `progress_callback` (`Callable[[int, int, str], None] | None`, optional): custom progress callback
- `completion_callback` (`Callable[[bool, float, int, int], None] | None`, optional): invoked with `(success, duration, images, tokens)` when conversion finishes
- `batch_mode` (`bool`, default `False`): suppresses interactive terminal output; used by `convert_files`
- `target_dir` (`str | Path | None`, optional): output directory for the Markdown file; defaults to the source directory
- `stdout` (`bool`, default `False`): returns the Markdown in `result.markdown` without writing files, inlining assets as base64; cannot be combined with `overwrite`, `skip_existing`, `target_dir`, or `asset_dir`
- `asset_dir` (`str | Path | None`, optional): directory where extracted assets go; defaults to the output directory
- `write_markdown` (`bool`, default `True`): when `False`, the Markdown is returned in `result.markdown` but not written to disk; this is how merge mode collects text
- Returns: `ConversionResult`

`ConversionResult` is a frozen dataclass with these fields:

- `success` (`bool`): whether conversion succeeded
- `markdown` (`str | None`): the generated Markdown, when available
- `images` (`int`): number of extracted images
- `tokens` (`int`): approximate token count of the generated Markdown
- `duration` (`float`): wall-clock seconds spent converting
- `error` (`str | None`): failure reason, when `success` is `False`
- `output_path` (`Path | None`): path of the written Markdown file, or `None` when nothing was written

The dataclass is truthy when `success` is true, so `if convert_file(...)` still works:

```python
from hammerdown import convert_file

result = convert_file("notes.txt", overwrite=True)
if result:
    print(f"Converted {result.output_path} in {result.duration:.2f}s")
else:
    print(f"Conversion failed: {result.error}")
```

> [!note]
> `overwrite=True` only rewrites plain-text sources in place, and the plain-text extensions are exactly `.txt` and `.md`. For binary formats the flag is ignored with a warning.

### `convert_files(...)`

Runs a batch conversion with the same options as the CLI and returns a process-style exit code (`0` on success, `1` when any file failed).

```python
convert_files(
    files,
    *,
    include=(),
    exclude=(),
    overwrite=False,
    skip_existing=False,
    output_dir=None,
    merge=None,
    stdout=False,
    confirm=False,
) -> int
```

- `files` (`Sequence[str | Path]`): files or directories to convert
- `include` / `exclude` (`Sequence[str]`, optional): regular expressions applied to each path relative to the inputs
- `overwrite`, `skip_existing`, `output_dir`, `merge`, `stdout`, `confirm`: mirror the CLI flags of the same names

```python
import hammerdown

exit_code = hammerdown.convert_files(["folder/"], merge="summary.md", include=[r"reports/.*"])
```

The function raises `ValueError` for unsupported option combinations:

- `confirm` without `stdout`
- `stdout` with `merge`, `output_dir`, `overwrite`, or `skip_existing`
- `merge` with `overwrite` or `output_dir`
- `overwrite` with `skip_existing` or `output_dir`
- an invalid regular expression in `include` or `exclude`

## Format-Specific Converters

If you only need to process a specific document type, you can import and call dedicated converter functions directly.

Each converter has the same signature and returns `tuple[str | None, int]` -- the Markdown text (or `None` on error) and the count of extracted images:

- `file_path` (`str`): path to the input file
- `out_dir` (`str`): directory where extracted assets (such as images or SVG charts) are saved in a subfolder named after the source, for example `hm_images_report_docx/`
- `progress_callback` (`Callable[[int, int, str], None] | None`, optional): progress callback

### Word and Text Documents

- `convert_docx(docx_path, out_dir)` -- converts modern Word (.docx) files, parses tables, turns Word formulas into LaTeX, and renders embedded charts as SVG; additionally accepts `images_dir_name=None` and `progress_callback=None` as keyword arguments
- `convert_doc(doc_path, out_dir)` -- converts legacy Word (.doc) files using LibreOffice or Microsoft Word automation
- `convert_odt(odt_path, out_dir)` -- converts OpenDocument Text (.odt) files with native formula and image extraction
- `convert_txt_or_md(file_path, out_dir)` -- reads plain text, log, or Markdown files with automatic encoding detection; extracts any embedded base64 image strings into files whose extension follows the MIME subtype (`embedded_img_0.png`, `embedded_img_1.jpeg`, and so on) inside the source's asset folder, for example `hm_images_LMS_md/`

```python
from hammerdown import convert_docx, convert_odt

md_text, images = convert_docx("thesis.docx", "out")
odt_text, images = convert_odt("paper.odt", "out")
```

### Spreadsheets and Tables

- `convert_xlsx(xlsx_path, out_dir)` -- converts Excel (.xlsx) workbooks to Markdown tables, supporting formulas and multi-table sheets
- `convert_xls(xls_path, out_dir)` -- converts legacy Excel (.xls) files
- `convert_csv(csv_path, out_dir)` -- automatically detects delimiter and converts CSV into clean Markdown tables

```python
from hammerdown import convert_xlsx, convert_csv

tables_md, _ = convert_xlsx("budget.xlsx", "out")
csv_md, _ = convert_csv("records.csv", "out")
```

### Presentations

- `convert_pptx(pptx_path, out_dir)` -- extracts slides, paragraphs, and tables from PowerPoint (.pptx) presentations
- `convert_ppt(ppt_path, out_dir)` -- converts legacy PowerPoint (.ppt) presentations

```python
from hammerdown import convert_pptx

slides_md, _ = convert_pptx("presentation.pptx", "out")
```

### PDF and E-books

- `convert_pdf_or_ebook(file_path, out_dir)` -- converts PDF, EPUB, MOBI, FB2, and XPS files to text-only Markdown; the PDF path does not extract raster images, so the returned image count is always `0`

```python
from hammerdown import convert_pdf_or_ebook

pdf_md, images = convert_pdf_or_ebook("manual.pdf", "out")
```

## Low-Level Helpers

These utility functions power `hammerdown` internally and are available for custom document processing pipelines.

### `render_table_regions(rows)`

Takes an iterable of row values (such as rows from a CSV or spreadsheet) and groups cells into separated Markdown tables, skipping empty margins.

- `rows` (`Iterable[Iterable[object]]`): two-dimensional cell data
- Returns: `list[str]` -- list of formatted Markdown table strings

```python
from hammerdown import render_table_regions

data = [
    ["Name", "Score"],
    ["Alice", 95],
    ["Bob", 88],
]
tables = render_table_regions(data)
print("\n\n".join(tables))
```

### `render_chart_svg(chart_data)`

Extracts data series from Word chart XML and generates a clean, standalone SVG diagram.

- `chart_data` (`bytes`): raw XML bytes of the chart part
- Returns: `tuple[str, str] | None` -- a tuple of `(chart_title, svg_code)` or `None` if parsing fails

### `render_markdown_table(rows)`

Renders already-stringified table cells into Markdown lines, escaping any `|` inside a cell. Import it from `hammerdown.parsers.markdown_render`:

```python
from hammerdown.parsers.markdown_render import render_markdown_table
```

- `rows` (`Sequence[Sequence[str]]`): two-dimensional cell data where every cell is already a string
- Returns: `list[str]` -- the header row, the `| --- |` separator row, and the body rows

### Estimation helpers

The estimation model lives in `hammerdown.estimates` and is shared by the CLI hints and the API:

- `describe(path)` -> `tuple[float | None, str]` -- the estimated duration in seconds and a display hint suffix such as ` (9 pages, est. ~8.1s)`
- `get_conversion_estimate_seconds(path)` -> `float | None` -- just the estimated duration
- `get_conversion_estimate(path)` -> `str` -- just the display hint (for example `~8.1s`), or an empty string when no estimate is available

### `omml_to_latex(elem)` and `mathml_to_latex(elem)`

Converts equation XML elements into standard LaTeX math expressions.

- Word stores formulas using a format called OMML (Office Math Markup Language)
- LibreOffice and OpenDocument store formulas using MathML
- `elem` (`xml.etree.ElementTree.Element`): root XML node of the equation
- Returns: `str` -- formula translated to LaTeX notation

```python
import xml.etree.ElementTree as ET
from hammerdown import mathml_to_latex

math_xml = "<math><mfrac><mn>1</mn><mi>N</mi></mfrac></math>"
latex = mathml_to_latex(ET.fromstring(math_xml))
print(latex)  # \frac{1}{N}
```
