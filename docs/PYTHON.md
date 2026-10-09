# Python API Reference

`hammerdown` can be used directly as a Python library. You can run high-level document conversions or call individual parsers for specific formats.

## Quickstart

```python
import hammerdown

# Convert a file and save it to disk
success = hammerdown.convert_file("document.pdf")

# Or get the Markdown text directly in Python memory
markdown_text, image_count = hammerdown.to_markdown("document.docx")
print(markdown_text)
```

## High-Level Functions

### `to_markdown(file_path, out_dir=None)`

Converts any supported document to Markdown and extracts any embedded images.

- `file_path` (`str | Path`): path to the source document
- `out_dir` (`str | Path | None`, optional): directory where extracted images should be saved; defaults to the directory of the source file
- Returns: `tuple[str | None, int]` -- the generated Markdown string (or `None` on error) and the number of saved images

```python
from hammerdown import to_markdown

text, images = to_markdown("data/report.docx", out_dir="output")
```

### `convert_file(file_path, force=False, in_place=True)`

Converts the document and writes the output file `<stem>_<ext>.md` to disk.

- `file_path` (`str | Path`): path to the source document
- `force` (`bool`, default `False`): if `True`, overwrites existing output Markdown files
- `in_place` (`bool`, default `True`): saves output files next to the source file
- Returns: `bool` -- `True` if conversion succeeded, `False` otherwise

```python
from hammerdown import convert_file

if convert_file("notes.pdf", force=True):
    print("Conversion finished!")
```

## Format-Specific Converters

If you only need to process a specific document type, you can import and call dedicated converter functions directly.

Each converter function takes:
- `file_path` (`str`): path to the input file
- `out_dir` (`str`): directory where extracted assets (such as images or SVG charts) are saved in a subfolder `hammerdown_images/`
- Returns: `tuple[str | None, int]` -- the Markdown text and the count of extracted images

### Word and Text Documents

- `convert_docx(docx_path, out_dir)` -- converts modern Word (.docx) files, parses tables, turns Word formulas into LaTeX, and renders embedded charts as SVG
- `convert_doc(doc_path, out_dir)` -- converts legacy Word (.doc) files using LibreOffice or Microsoft Word automation
- `convert_odt(odt_path, out_dir)` -- converts OpenDocument Text (.odt) files with native formula and image extraction
- `convert_txt_or_md(file_path, out_dir)` -- reads plain text, log, or Markdown files with automatic encoding detection; extracts any embedded base64 image strings into PNG/JPEG files inside `hammerdown_images/`

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

- `convert_pdf_or_ebook(file_path, out_dir)` -- converts PDF, EPUB, MOBI, FB2, and XPS files, extracting raster images by XREF

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
