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
└── hammerdown_images_document_pdf/
    └── img_p001_xref105.png
```

Key naming rules:
- the output Markdown file uses the template `<stem>_<ext>.md` (for example, `report_doc.md` or `report_docx.md`) to avoid name collisions between files with identical names but different extensions (or overwrites the source file directly when `-w`/`--overwrite` is specified for plain text formats)
- images, charts, and extracted assets are stored in a dedicated folder named `hammerdown_images_<stem>_<ext>/` next to the Markdown file
- relative image links in the Markdown point to `hammerdown_images_<stem>_<ext>/...`

## File Processing Details

### PDF and E-books (.pdf, .epub, .mobi, .fb2, .xps)

- text and layout structure are parsed using [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- raster images embedded in pages are extracted directly by their internal reference (XREF); images smaller than 50 x 50 pixels are skipped to filter out minor UI icons and decorative bullet points
- extracted images are saved as PNG/JPEG files in `hammerdown_images_<stem>_<ext>/` with names formatted as `img_p{page:03d}_xref{xref}.{ext}`

### Word Documents (.docx, .doc, .odt)

- headings, paragraphs, and list items are converted to standard Markdown syntax
- equations are translated from internal XML structures into standard LaTeX formulas using character mapping definitions in `src/hammerdown/parsers/symbols.json`
- embedded diagrams and charts are exported as vector SVG graphics
- binary `.doc` legacy files are converted to DOCX first when LibreOffice or Microsoft Word is installed

### Excel Workbooks and CSV (.xlsx, .xls, .csv)

- each worksheet is exported with a `# Sheet: <name>` header
- cell boundaries are detected automatically, trimming blank margins and turning separate tables on the same sheet into individual Markdown tables
- evaluated values take precedence over raw formulas when available
- character encodings (UTF-8, CP1251, Latin-1) and tabular delimiters (comma, semicolon, tab) are detected automatically for CSV files

### Plain Text and Markdown (.txt, .md, .log)

- text is decoded with automatic fallback across UTF-8, CP1251, and Latin-1 encodings
- if a Markdown file contains embedded base64 image strings (like `data:image/png;base64,...`), `hammerdown` decodes them, saves them as PNG/JPEG files in `hammerdown_images_<stem>_<ext>/`, and replaces the inline base64 string with a clean relative link

### PowerPoint Presentations (.pptx, .ppt)

- slides are extracted as Level 2 Markdown headings (`## Slide N`)
- text frames and tables within each slide are converted into paragraphs and Markdown tables

## Mathematical Symbols Reference

When normalizing math equations from Word and OpenDocument files, `hammerdown` translates special characters into standard LaTeX commands.

The symbol catalog is maintained in `src/hammerdown/parsers/symbols.json` and is aligned with the LaTeX Mathematical Symbols Reference:
- Official reference: https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf
- Local copy bundled in repository: [symbols.pdf](../symbols.pdf)

## Release and PyPI Immutability

> [!important]
> Release versions are strictly immutable across both distribution channels:
> - PyPI registry: once a version package (such as `1.5.2`) is published to PyPI, the index entry is permanently locked. PyPI prohibits overwriting or re-uploading an existing version artifact under any circumstances. Any attempt to re-upload the same version will immediately fail with an HTTP error (`File already exists`), regardless of pipeline settings.
> - GitHub release tags: repository tag rulesets (`Protect release tags` targeting `v*`) explicitly forbid force-pushing, updating, or deleting existing release tags on GitHub.

Any fixes or subsequent updates must always increment the version number (e.g. `1.5.3`) and be released as a fresh tag.

> [!warning]
> **Legacy Version Ambiguity (v1.5.2 "Frankenstein")**: Due to a synchronization overlap during the transition to tag protection, version `1.5.2` on PyPI may differ from the `v1.5.2` tag on GitHub. To ensure a clean state for any version below `2.0.0`, it is strictly recommended to run the following recovery sequence:
> 1. `pip uninstall hammerdown`
> 2. `pip install --no-cache-dir hammerdown`
> 3. `hammerdown --install` (to refresh OS integrations)

Starting from version `2.0.0`, overwriting existing target Markdown files is the default behavior. The `--force` flag remains removed in favor of `--skip-existing` (`-s`) when existing output should be preserved. Version `3.0.0` accepts only hyphenated long option names, so `--skip_existing` is rejected.

## Architecture and File Conventions in v3.0.0

### Output Naming Convention
To prevent collisions between documents with the same name across different formats or subfolders, `hammerdown` 3.0.0 enforces:
- Output Markdown filename: `hm_<stem>_<ext>.md` (e.g. `hm_report_docx.md` or `hm_notes_txt.md`)
- Extracted images directory: `hm_images_<stem>_<ext>/` (e.g. `hm_images_report_docx/`)

### Single-Instance IPC Coordinator
On Windows, selecting multiple files in Explorer normally starts a separate process for each file. `hammerdown` combines Explorer's native multi-select grouping with an IPC fallback to handle these launches:

- native multi-select grouping in Explorer is configured via `MultiSelectModel = "Player"` and an Advanced Query Syntax (`AppliesTo`) filter so Explorer passes supported files to a **single process**
- local IPC channels (`\\.\pipe\hammerdown_coordinator` on Windows) catch additional launches when command line limits (8191 characters) are exceeded or files arrive separately
- incoming paths are assembled over a 0.35-second window by the coordinator before rendering them together in one console window

### Interactive File Queue UI
When files are processed in an interactive terminal (TTY), `hammerdown` displays a progress table. Status colors are fixed ANSI values for consistent visibility across terminal themes:

- finished files switch to green (`#a7c939`) marked with `[x]` alongside execution duration and asset counts
- active files display an orange (`#ec7c39`) `[>]` indicator, while queued files remain in dim gray (`#909090`) `[ ]`
- unhandled errors or parsing failures appear in red (`#9d2f34`) marked with `[!]`

### Recursive Directory Traversal
When passing a directory to `hammerdown`, it recursively scans for all files matching `SUPPORTED_EXTENSIONS` while skipping temporary office lock files (`~$*`) and hidden files (`.*`).

### Merged Output (`-m / --merge`)
When `-m <output.md>` is specified, all successful Markdown conversions are bundled into a single destination file separated with document headings (`# <filename>`).

> [!note]
> If a CI workflow fails during early stages (such as linting, unit tests, or matrix builds) before the PyPI upload step executes, the version number has not been registered on PyPI yet. In that case, fixing the root cause and updating the git tag to re-trigger the release workflow is safe, because PyPI only locks version numbers once an actual distribution archive (`.whl` or `.tar.gz`) has been successfully received by its registry index.

## Performance Optimizations

To deliver maximum speed when processing large documents and batch conversions, `hammerdown` employs multi-level parallelism and lazy loading:

1. multi-process CPU workers (`ProcessPoolExecutor`) execute conversions in parallel when multiple documents are passed via the CLI (`hammerdown doc1.pdf doc2.docx doc3.pdf`)
2. golden test conversions run concurrently across available CPU threads (`ThreadPoolExecutor`), cutting execution time roughly in half
3. large PDF documents (>4 pages) are split into page chunks and rendered concurrently in background threads before assembling final Markdown
4. text extraction bypasses OCR verification (`use_ocr=False`) because embedded raster graphics are extracted directly via PyMuPDF XREF in milliseconds
5. heavy third-party libraries (`pymupdf`, `python-docx`, `openpyxl`, `python-pptx`) are loaded lazily on demand inside converter routines, letting quick commands (`--version`, `--install`, `--help`) and plain text files run instantly (<0.04s startup)
6. saving extracted images, vector charts, and base64 assets to disk runs concurrently in background thread pools, keeping disk I/O from blocking parsing logic

### Benchmarks

Empirical timings measured across test workloads demonstrate the impact of cascade parsing and concurrency:

- parsing a standard Word document via in-memory `python-docx` takes ~172 ms, whereas spawning headless LibreOffice takes ~5,324 ms (`--` a **30.8x speedup** for pure Python)
- converting a batch of diverse test documents (PDF, DOCX, XLSX, CSV, TXT) sequentially takes ~43.7 s, while parallel multi-threaded conversion finishes in ~22.7 s (`--` a **1.9x speedup**)

## References and External Sources

- math symbols are referenced against the [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf) (local copy: [symbols.pdf](../symbols.pdf))
- PDF rendering and extraction rely on [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- office documents are parsed using [python-docx](https://python-docx.readthedocs.io/) for Word, [openpyxl](https://openpyxl.readthedocs.io/) for Excel, and [python-pptx](https://python-pptx.readthedocs.io/) for PowerPoint
