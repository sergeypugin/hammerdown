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
    └── chart_001.svg
```

Key naming rules:
- the output Markdown file has a deterministic per-source name: `report.docx` becomes `hm_report_docx.md`, while `report.doc` becomes `hm_report_doc.md`. The source extension is part of the name and is normalized to lowercase, which avoids collisions between identical stems in different supported formats. With `-w`/`--overwrite`, plain-text sources are rewritten in place instead
- extracted assets are stored in a dedicated folder next to the Markdown file: Word charts land in `hm_images_report_docx/`, and OpenDocument or Markdown images land in a folder such as `hm_images_report_odt/` or `hm_images_LMS_md/`
- relative image links in the Markdown point into that folder, for example `hm_images_report_docx/chart_001.svg`
- a successful normal rerun replaces the Markdown target and the complete corresponding `hm_images_*` directory, so stale files and old asset extensions are removed; if the new conversion produces no assets, the old asset directory is removed
- `-s`/`--skip-existing` checks only the Markdown target. When it already exists, conversion is skipped and the existing Markdown and asset directory are both left untouched, even if stale

## File Processing Details

### PDF and E-books (.pdf, .epub, .mobi, .fb2, .xps)

- text and layout are reconstructed with [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM) on top of [PyMuPDF](https://pymupdf.readthedocs.io/), with OCR disabled (`use_ocr=False`)
- the PDF path produces text-only Markdown: `convert_pdf_or_ebook` always reports `0` extracted images and never writes an asset folder
- in ordinary batch runs, multi-page documents are planned by the work-unit scheduler into contiguous 32-page chunks (`HAMMERDOWN_PDF_CHUNK_PAGES` overrides the size) that convert concurrently under a PDF permit of two (`HAMMERDOWN_PDF_LIMIT` overrides it); the parser's own `ThreadPoolExecutor` capped at four workers performs the same chunked conversion on the sequential-fallback and stdout paths
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
- if a Markdown file contains embedded base64 image strings (like `data:image/png;base64,...`), `hammerdown` decodes them, saves them as `embedded_img_1.png`, `embedded_img_2.jpeg`, and so on inside the source's asset folder, and replaces the inline base64 string with a clean relative link. For `LMS.md`, the folder is `hm_images_LMS_md/`

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

Starting from version `2.0.0`, overwriting existing target Markdown files is the default behavior. The `--force` flag remains removed in favor of `--skip-existing` (`-s`) when existing output should be preserved. The current CLI accepts option names case-insensitively, but option values, paths, and filter patterns preserve case. Long option names must use their exact two-dash, hyphenated spelling: `--skip_existing`, single-dash long forms, and abbreviated long forms are rejected.

## Current Architecture and File Conventions

### Output Naming Convention
To prevent collisions between documents with the same name across different formats or subfolders, Hammerdown uses deterministic per-source output names:
- Output Markdown filename: `report.docx` becomes `hm_report_docx.md`, and `notes.txt` becomes `hm_notes_txt.md`
- Extracted images directory: `report.docx` uses `hm_images_report_docx/`

A successful rerun replaces the complete Markdown-and-assets output for that source. `--skip-existing` preserves an existing target and its asset directory as a unit, even when stale.

### Single-Instance IPC Coordinator
On Windows, selecting multiple files in Explorer normally starts a separate process for each file. `hammerdown` combines Explorer's native multi-select grouping with an IPC fallback to handle these launches:

- native multi-select grouping in Explorer is configured via `MultiSelectModel = "Player"` without an `AppliesTo` filter, because Explorer hides a filtered verb unless the filter matches every selected item
- unsupported files in a mixed selection are skipped and listed in the batch summary instead of being filtered out by Explorer
- the Explorer verb launches the frozen GUI-subsystem executable (`hammerdown-windows-x64.exe`), so delegate processes never allocate a console; `AllocConsole()` is called only as a fallback via `_ensure_console_window()` when Windows Terminal is unavailable
- local IPC channels (`\\.\pipe\hammerdown_coordinator` on Windows) catch additional launches when command line limits (8191 characters) are exceeded or files arrive separately
- incoming paths are assembled over a 2.0-second window (`assembly_timeout=2.0`) by the coordinator before handing off to Windows Terminal (`wt.exe -w new new-tab --title Hammerdown`) or, if unavailable, allocating a fallback console

### Recursive Directory Traversal
When a directory is passed to `hammerdown`, it recursively discovers resources while pruning directories and files excluded by safety rules. `hm_*.md` and `hammerdowned.md` are generated outputs and are excluded from the recursive source set. Explicitly passing one of these files is an error, and a directory containing only generated outputs fails because no input resources remain. Discovery deduplicates canonical paths, so repeated files, a file plus its containing directory, and overlapping parent/child roots are processed once.

Tree mode (`--tree`) always writes one combined Markdown target. It collects Gitingest-like text and source-like files without adding Hammerdown's binary document formats by default. `--all-formats` adds supported Hammerdown documents, while unknown binary files remain skipped. The tree target defaults to `hammerdowned.md` and can be changed with `-m`. `--tree` and `--all-formats` may appear before, between, or after positional resources. Tree mode rejects `-o/--output-dir` and `-w/--overwrite`.

`.log` is not default-excluded and is processed unless an ignore rule or filter excludes it.

Repository `.gitignore` and `.gitingestignore` files are discovered in the resource tree, including nested directories. For each selected root, Hammerdown checks ancestor locations up to the nearest Git root; without a Git root, the selected root is the boundary. Their nested rules and negation apply to paths in their scope. Files above the Git root and global ignore configuration are not used. `--include-gitignored` disables only repository ignore files, not command-line filters, safety exclusions, generated-output exclusions, or format rules. Paths to discovered ignore files are shown in the `Ignore files used` panel before processing; files ignored by those rules do not appear in the skipped-file list.

Option names are case-insensitive, but values, paths, and filter patterns preserve case. The CLI requires exact two-dash long option names, so single-dash long forms and abbreviated long forms remain errors.

### Include and Exclude Filters
`-i` / `--include` and `-e` / `--exclude` accept Gitingest-compatible GitWildMatch/pathspec patterns matched against paths relative to the resource context. Each option may be repeated, and the options form one ordered queue in command-line order. A path starts included when no include option is present, or excluded when an include option is present; each matching `-e` excludes it and each later matching `-i` includes it again. The last matching operation decides, so a later include can restore a path excluded earlier. Pattern values accept comma- or whitespace-separated patterns. Use single or double quotes to group an argument. Apostrophes or quote characters inside a file name are not supported by the CLI quote parser; backticks are not quoting syntax.

### Merged Output (`-m / --merge`)
The merge option treats the next argument as the output Markdown target and then expects one or more source resources. If no target argument is supplied, the default is `hammerdowned.md`. Because the next positional after `-m` is always the target, `hammerdown -m anything.ext` has no source and is invalid; `hammerdown -m output.md source.pdf` supplies both the target and a resource. The target is assembled in a hidden staging directory and committed atomically once every source is appended, so an interrupted run leaves the previous target untouched instead of a partial document. Its contents are:

- a YAML frontmatter metadata block recording provenance -- `tool`, `version`, `date`, `mode`, `source`, `inputs`, `files`, and `tokens_estimate` -- so a stale target is easy to tell from a fresh one
- a `Directory structure:` tree listing every source relative to their common root
- one block per document, introduced by a separator line of 48 `=` characters, a line such as `FILE: notes/draft.md`, and the separator again, followed by the converted Markdown

Extracted assets are kept apart from the originals: images, charts, and decoded pictures are written into `hm_merged_into_summary_images/` next to the merge target, inside subfolders that mirror each document's relative path, and their links are rewritten to match.

A successful rerun replaces the merge target and its complete merge asset directory, frontmatter included, so the metadata always reflects the latest run. With `-s` / `--skip-existing`, an existing merge target skips the entire merge and leaves both the target and its assets untouched, even if stale. If a custom merge target is inside a recursively selected directory, discovery excludes it so a rerun does not merge the previous output into itself; explicitly passing that target as a source remains an error.

`--merge` is rejected together with `--overwrite` and with `--output-dir`.

### Streaming to stdout (`--stdout`)
`--stdout` emits the same merged document as `-m`, but writes it to stdout and leaves nothing on disk:

- each conversion runs against a temporary output directory, so no `hm_*.md` files or asset folders are created
- `resources.embed_temporary_resources` inlines every temporary asset as a base64 data URI, keeping the stream self-contained
- the merged document goes to stdout while progress output is suppressed and errors go to stderr, and the exit code is non-zero when any document failed; the stream stays headerless, so the frontmatter metadata block is never printed to stdout
- `--stdout` is rejected together with `--merge`, `--output-dir`, `--overwrite`, and `--skip-existing`
- `--confirm` adds a preflight estimate and an interactive `[y/n]` prompt. `y` and `yes` proceed, `n` and `no` cancel, other answers re-ask, and a missing TTY cancels immediately. The token part of the estimate covers only plain-text sources

> [!note]
> If a CI workflow fails during early stages (such as linting, unit tests, or matrix builds) before the PyPI upload step executes, the version number has not been registered on PyPI yet. In that case, fixing the root cause and updating the git tag to re-trigger the release workflow is safe, because PyPI only locks version numbers once an actual distribution archive (`.whl` or `.tar.gz`) has been successfully received by its registry index.

## Performance Optimizations

To deliver maximum speed when processing large documents and batch conversions, `hammerdown` employs multi-level parallelism and lazy loading:

1. ordinary batch conversion is concurrent and bounded: `run_batch` schedules resolved files through `core/scheduler.py` -- a `BatchScheduler` with an in-flight window of two jobs for PDF-free batches, or a `WorkUnitScheduler` (32-page PDF work units, two concurrent PDF chunks by default, worker count from `calculate_optimal_workers()`) when the batch contains a real PDF; `HAMMERDOWN_FORCE_SEQUENTIAL=1`, `--dir-struct`, and `--stdout` use a single-loop sequential path instead, and the PDF parser's own four-worker chunk pool is reached only on those sequential and stdout paths
2. golden test conversions run concurrently across available CPU threads (`ThreadPoolExecutor`), cutting execution time roughly in half
3. PDF documents with more than one page are split into contiguous page chunks that are converted concurrently in background threads before the results are assembled into final Markdown
4. text extraction disables OCR (`use_ocr=False`), so pages are parsed from their embedded text layer instead of being rasterized and recognized
5. heavy third-party libraries (`pymupdf`, `python-docx`, `openpyxl`, `python-pptx`) are loaded lazily on demand inside converter routines, so quick commands (`--version`, `--install`, `--help`) and plain-text batches never load the heavy parsers at all
6. each parser writes its extracted assets to disk as it walks the document, so no separate image post-processing pass is required

### Benchmarks

Empirical timings measured across test workloads demonstrate the impact of cascade parsing and concurrency:

- parsing a standard Word document with in-memory `python-docx` takes ~172 ms, whereas spawning headless LibreOffice takes ~5,324 ms, a **30.8x speedup** for pure Python
- converting a batch of diverse test documents (PDF, DOCX, XLSX, CSV, TXT) sequentially takes ~43.7 s, whereas the multi-threaded golden-test harness finishes in ~22.7 s, a **1.9x speedup**

## References and External Sources

- math symbols are referenced against the [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf) (local copy: [symbols.pdf](../src/hammerdown/parsers/math/symbols.pdf))
- PDF rendering and extraction rely on [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM)
- office documents are parsed using [python-docx](https://python-docx.readthedocs.io/) for Word, [openpyxl](https://openpyxl.readthedocs.io/) for Excel, and [python-pptx](https://python-pptx.readthedocs.io/) for PowerPoint
