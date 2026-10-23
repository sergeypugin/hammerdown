# Technical Reference

This document describes how `hammerdown` processes documents, extracts images and math formulas, and handles different file formats.

## Output Directory Layout

When converting a document, `hammerdown` creates the resulting Markdown file and asset folder next to the original file:

**Before conversion:**
```text
folder/
└── report.docx
```

**After conversion:**
```text
folder/
├── report.docx
├── hm_report_docx.md
└── hm_images_report_docx/
    └── chart_000.svg
```

Key naming rules:
- the output Markdown file is named after the source and its extension: `report.docx` becomes `hm_report_docx.md`, while `report.doc` becomes `hm_report_doc.md`. This avoids collisions between files with identical names but different extensions. With `-w`/`--overwrite`, plain-text sources are rewritten in place instead
- extracted assets are stored in a dedicated folder next to the Markdown file: Word charts land in `hm_images_report_docx/`, and OpenDocument or Markdown images land in a folder such as `hm_images_report_odt/` or `hm_images_LMS_md/`
- relative image links in the Markdown point into that folder, for example `hm_images_report_docx/chart_000.svg`

## File Processing Details

### PDF and E-books (.pdf, .epub, .mobi, .fb2, .xps)

- text and layout are reconstructed with [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM) on top of [PyMuPDF](https://pymupdf.readthedocs.io/), with OCR disabled (`use_ocr=False`)
- the PDF path produces text-only Markdown: `convert_pdf_or_ebook` always reports `0` extracted images and never writes an asset folder
- documents with more than one page are split into contiguous chunks of roughly `ceil(pages / cpu_count)` pages (minimum 2) and converted concurrently in a `ThreadPoolExecutor`
- a chunk that fails falls back to safe per-page conversion, emitting an HTML comment warning for any page that cannot be parsed
- the progress counter and callback are updated from worker threads and guarded by a lock
- single-page documents convert on the main thread without a pool

### Word Documents (.docx, .doc, .odt)

- paragraphs and inline runs are converted to Markdown text, and tables become Markdown tables; headings and list items keep their text but are not promoted to Markdown heading or list syntax
- equations are translated from internal XML structures into standard LaTeX formulas using character mapping definitions in `src/hammerdown/parsers/math/symbols.json`
- embedded Word DrawingML charts are exported as vector SVG graphics
- binary `.doc` legacy files are converted to DOCX first when LibreOffice or Microsoft Word is installed

### Excel Workbooks and CSV (.xlsx, .xls, .csv)

- each worksheet is exported with a header such as `# Sheet: Data`
- cell boundaries are detected automatically, trimming blank margins and turning separate tables on the same sheet into individual Markdown tables
- evaluated values take precedence over raw formulas when available
- character encodings (UTF-8, CP1251, CP1252, Latin-1) and tabular delimiters (comma, semicolon, tab, pipe) are detected automatically for CSV files

### Plain Text and Markdown (.txt, .md, .log)

- text is decoded with automatic fallback across UTF-8, CP1251, CP1252, and Latin-1 encodings
- if a Markdown file contains embedded base64 image strings (like `data:image/png;base64,...`), `hammerdown` decodes them, saves them as `embedded_img_0.png`, `embedded_img_1.jpeg`, and so on inside the source's asset folder, and replaces the inline base64 string with a clean relative link. For `LMS.md`, the folder is `hm_images_LMS_md/`

### PowerPoint Presentations (.pptx, .ppt)

- slides are extracted as Level 2 Markdown headings (`## Slide N`)
- text frames and tables within each slide are converted into paragraphs and Markdown tables

## Mathematical Symbols Reference

When normalizing math equations from Word and OpenDocument files, `hammerdown` translates special characters into standard LaTeX commands.

The symbol catalog is maintained in `src/hammerdown/parsers/math/symbols.json` and is aligned with the LaTeX Mathematical Symbols Reference:
- Official reference: https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf
- Local copy bundled in repository: [symbols.pdf](../src/hammerdown/parsers/math/symbols.pdf)

## Release and PyPI Immutability

> [!important]
> Release versions are strictly immutable across both distribution channels:
> - PyPI registry: once a version package (such as `1.5.2`) is published to PyPI, the index entry is permanently locked. PyPI prohibits overwriting or re-uploading an existing version artifact under any circumstances. Any attempt to re-upload the same version will immediately fail with an HTTP error (`File already exists`), regardless of pipeline settings.
> - GitHub release tags: repository tag rulesets (`Protect release tags` targeting `v*`) explicitly forbid force-pushing, updating, or deleting existing release tags on GitHub.

Any fixes or subsequent updates must always increment the version number (e.g. `1.5.3`) and be released as a fresh tag.

### Release channels

Tags decide both the GitHub Release and the PyPI upload:
- stable: `vX.Y.Z` (for example `v3.1.0`). The release becomes the latest GitHub release and is published to PyPI after the workflow verifies that `X.Y.Z` matches `__version__`
- prerelease: a tag with a suffix (for example `v3.1.2-pre`). It is published as a GitHub prerelease, never becomes latest, and is not uploaded to PyPI

This matches the convention used by Zed (`-pre`) and Electron (`-beta`), and the tags stay valid SemVer. The tradeoff is that a plain tag publishes to PyPI, so release tags must be pushed deliberately.

> [!warning]
> **Legacy Version Ambiguity (v1.5.2 "Frankenstein")**: Due to a synchronization overlap during the transition to tag protection, version `1.5.2` on PyPI may differ from the `v1.5.2` tag on GitHub. To ensure a clean state for any version below `2.0.0`, it is strictly recommended to run the following recovery sequence:
> 1. `pip uninstall hammerdown`
> 2. `pip install --no-cache-dir hammerdown`
> 3. `hammerdown --install` (to refresh OS integrations)

Starting from version `2.0.0`, overwriting existing target Markdown files is the default behavior. The `--force` flag remains removed in favor of `--skip-existing` (`-s`) when existing output should be preserved. Version `3.0.0` accepts only hyphenated long option names, so `--skip_existing` is rejected.

## Architecture and File Conventions in v3.0.0

### Output Naming Convention
To prevent collisions between documents with the same name across different formats or subfolders, `hammerdown` 3.0.0 enforces:
- Output Markdown filename: `report.docx` becomes `hm_report_docx.md`, and `notes.txt` becomes `hm_notes_txt.md`
- Extracted images directory: `report.docx` uses `hm_images_report_docx/`

### Single-Instance IPC Coordinator
On Windows, selecting multiple files in Explorer normally starts a separate process for each file. `hammerdown` combines Explorer's native multi-select grouping with an IPC fallback to handle these launches:

- native multi-select grouping in Explorer is configured via `MultiSelectModel = "Player"` without an `AppliesTo` filter, because Explorer hides a filtered verb unless the filter matches every selected item
- unsupported files in a mixed selection are skipped and listed in the batch summary instead of being filtered out by Explorer
- the Explorer verb launches `pythonw.exe`, so delegate processes never allocate a console; the coordinator calls `AllocConsole()` only after it wins the IPC race and rebinds `stdin`, `stdout`, and `stderr`
- local IPC channels (`\\.\pipe\hammerdown_coordinator` on Windows) catch additional launches when command line limits (8191 characters) are exceeded or files arrive separately
- incoming paths are assembled over a 0.35-second window by the coordinator before rendering them together in one console window

### Recursive Directory Traversal
When a directory is passed to `hammerdown`, it recursively scans for all files matching `SUPPORTED_EXTENSIONS`, pruning directories that never hold user documents:

- directories whose name starts with `.` are skipped
- `__pycache__`, `node_modules`, `venv`, `env`, `$Recycle.Bin`, and `System Volume Information` are skipped by name
- ignored files are temporary office lock files (`~$*`), hidden dotfiles, and previously generated `hm_*.md` outputs

### Include and Exclude Filters
`-i` / `--include` and `-e` / `--exclude` accept regular expressions matched against each candidate's normalized relative path (relative to the directory passed on the command line). Both flags may be repeated. Include narrows the recursive scan first, then exclude removes matches from that set, so exclusions always take priority. Patterns are validated at startup, and an invalid regex aborts the run before any conversion starts.

### Merged Output (`-m / --merge`)
`-m summary.md` bundles every successful conversion into one Markdown file. The target is written incrementally as the batch runs, so a partial document remains usable if the run is interrupted. Its contents are:

- a `Directory structure:` tree listing every source relative to their common root
- one block per document, introduced by a separator line of 48 `=` characters, a line such as `FILE: notes/draft.md`, and the separator again, followed by the converted Markdown

Extracted assets are kept apart from the originals: images, charts, and decoded pictures are written into `hm_merged_into_summary_images/` next to the merge target, inside subfolders that mirror each document's relative path, and their links are rewritten to match.

`--merge` is rejected together with `--overwrite` and with `--output-dir`, and the merge target cannot also be one of the source documents. Combined with `-s` / `--skip-existing`, the entire merge is skipped when the target file already exists.

### Streaming to stdout (`--stdout`)
`--stdout` emits the same merged document as `-m`, but writes it to stdout and leaves nothing on disk:

- each conversion runs against a temporary output directory, so no `hm_*.md` files or asset folders are created
- `resources.embed_temporary_resources` inlines every temporary asset as a base64 data URI, keeping the stream self-contained
- the merged document goes to stdout while progress output is suppressed and errors go to stderr, and the exit code is non-zero when any document failed
- `--stdout` is rejected together with `--merge`, `--output-dir`, `--overwrite`, and `--skip-existing`
- `--confirm` adds a preflight estimate and an interactive `[y/n]` prompt. `y` and `yes` proceed, `n` and `no` cancel, other answers re-ask, and a missing TTY cancels immediately. The token part of the estimate covers only plain-text sources

> [!note]
> If a CI workflow fails during early stages (such as linting, unit tests, or matrix builds) before the PyPI upload step executes, the version number has not been registered on PyPI yet. In that case, fixing the root cause and updating the git tag to re-trigger the release workflow is safe, because PyPI only locks version numbers once an actual distribution archive (`.whl` or `.tar.gz`) has been successfully received by its registry index.

## Performance Optimizations

To deliver maximum speed when processing large documents and batch conversions, `hammerdown` employs multi-level parallelism and lazy loading:

1. batch conversion is sequential: `run_batch` walks the resolved file list in a single loop and converts one document at a time, so the only thread pool in the conversion path is the PDF page-chunk pool described below
2. golden test conversions run concurrently across available CPU threads (`ThreadPoolExecutor`), cutting execution time roughly in half
3. PDF documents with more than one page are split into contiguous page chunks that are converted concurrently in background threads before the results are assembled into final Markdown
4. text extraction disables OCR (`use_ocr=False`), so pages are parsed from their embedded text layer instead of being rasterized and recognized
5. heavy third-party libraries (`pymupdf`, `python-docx`, `openpyxl`, `python-pptx`) are loaded lazily on demand inside converter routines, letting quick commands (`--version`, `--install`, `--help`) and plain text files run instantly (<0.04s startup)
6. each parser writes its extracted assets to disk as it walks the document, so no separate image post-processing pass is required

### Benchmarks

Empirical timings measured across test workloads demonstrate the impact of cascade parsing and concurrency:

- parsing a standard Word document with in-memory `python-docx` takes ~172 ms, whereas spawning headless LibreOffice takes ~5,324 ms, a **30.8x speedup** for pure Python
- converting a batch of diverse test documents (PDF, DOCX, XLSX, CSV, TXT) sequentially takes ~43.7 s, whereas the multi-threaded golden-test harness finishes in ~22.7 s, a **1.9x speedup**

## References and External Sources

- math symbols are referenced against the [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf) (local copy: [symbols.pdf](../src/hammerdown/parsers/math/symbols.pdf))
- PDF rendering and extraction rely on [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- office documents are parsed using [python-docx](https://python-docx.readthedocs.io/) for Word, [openpyxl](https://openpyxl.readthedocs.io/) for Excel, and [python-pptx](https://python-pptx.readthedocs.io/) for PowerPoint
