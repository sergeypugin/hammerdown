# Technical Reference

This document describes how `hammerdown` processes documents, extracts images and math formulas, and handles different file formats.

## Output Directory Layout

When converting a document, `hammerdown` creates the resulting Markdown file and asset folder next to the original file:

**Before conversion:**
```text
folder/
└── document.pdf
```

**After conversion:**
```text
folder/
├── document.pdf
├── document_pdf.md
└── hammerdown_images/
    └── document_p001_xref105.png
```

Key naming rules:
- the output Markdown file uses the template `<stem>_<ext>.md` (for example, `report_doc.md` or `report_docx.md`) to avoid name collisions between files with identical names but different extensions
- images, charts, and extracted assets are stored in a folder named `hammerdown_images/` next to the Markdown file
- relative image links in the Markdown point to `hammerdown_images/...`

## File Processing Details

### PDF and E-books (.pdf, .epub, .mobi, .fb2, .xps)

- text and layout structure are parsed using [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- raster images embedded in pages are extracted directly by their internal reference (XREF); images smaller than 50 x 50 pixels are skipped to filter out minor UI icons and decorative bullet points
- extracted images are saved as PNG/JPEG files in `hammerdown_images/`

### Word Documents (.docx, .doc, .odt)

- **Text and Paragraphs**: headings, paragraphs, and list items are converted to standard Markdown syntax
- **Math Formulas**: Word stores equations internally using XML structures (such as OMML in Word or MathML in LibreOffice). `hammerdown` converts these equation trees into standard LaTeX formulas (e.g. `\frac{1}{N}`, `\sum`, `\sqrt{x}`) using a character mapping dictionary stored in `src/hammerdown/parsers/symbols.json`
- **Charts and Diagrams**: embedded charts in Word documents are converted into vector SVG graphics
- **Legacy Files (.doc)**: if LibreOffice or Microsoft Word is installed on the system, legacy binary files are converted to DOCX first, then processed normally

### Excel Workbooks and CSV (.xlsx, .xls, .csv)

- **Sheet Tables**: each worksheet is exported with a `# Sheet: <name>` header
- **Cell Matrix Detection**: empty rows and margins are automatically trimmed; isolated tables on the same sheet are split into separate Markdown tables
- **Formulas vs Values**: cell values are preferred, but if calculated values are missing, formula strings are preserved
- **CSV Encoding and Dialect**: CSV files are read with automatic encoding detection (UTF-8, CP1251, Latin-1) and delimiter detection (comma, semicolon, tab)

### Plain Text and Markdown (.txt, .md, .log)

- text is decoded with automatic fallback across UTF-8, CP1251, and Latin-1 encodings
- if a Markdown file contains embedded base64 image strings (like `data:image/png;base64,...`), `hammerdown` decodes them, saves them as PNG/JPEG files in `hammerdown_images/`, and replaces the inline base64 string with a clean relative link

### PowerPoint Presentations (.pptx, .ppt)

- slides are extracted as Level 2 Markdown headings (`## Slide N`)
- text frames and tables within each slide are converted into paragraphs and Markdown tables

## Mathematical Symbols Reference

When normalizing math equations from Word and OpenDocument files, `hammerdown` translates special characters into standard LaTeX commands.

The symbol catalog is maintained in `src/hammerdown/parsers/symbols.json` and is aligned with the LaTeX Mathematical Symbols Reference:
- Official reference: https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf
- Local copy bundled in repository: [symbols.pdf](../symbols.pdf)

## References and External Sources

- **LaTeX Symbol Catalog**: based on the [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf) (local copy: [symbols.pdf](../symbols.pdf))
- **PDF Engine**: powered by [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- **Office Document Parsers**: [python-docx](https://python-docx.readthedocs.io/) for Word, [openpyxl](https://openpyxl.readthedocs.io/) for Excel, and [python-pptx](https://python-pptx.readthedocs.io/) for PowerPoint
