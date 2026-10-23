# hammerdown

[![Tests](https://img.shields.io/github/actions/workflow/status/sergeypugin/hammerdown/release.yaml?branch=main&label=tests&logo=github&style=flat-square)](https://github.com/sergeypugin/hammerdown/actions)
[![PyPI](https://img.shields.io/pypi/v/hammerdown?style=flat-square&color=2ea44f&logo=pypi&logoColor=white)](https://pypi.org/project/hammerdown/)
[![GitHub Release](https://img.shields.io/github/v/release/sergeypugin/hammerdown?style=flat-square&color=2ea44f&logo=github)](https://github.com/sergeypugin/hammerdown/releases)
[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?style=flat-square)](https://github.com/sergeypugin/hammerdown/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-a1ffcb?style=flat-square&labelColor=191919)](CONTRIBUTING.md)

<div align="center">
  <img src="assets/logo.svg" alt="hammerdown logo" width="220" height="220">
</div>

`hammerdown` is a cross-platform tool and Python library for converting PDF, Word, Excel, PowerPoint, OpenDocument, CSV, and plain-text documents into clean Markdown. Word charts are rendered as SVG, OpenDocument and Markdown images are extracted, and mathematical formulas are converted to LaTeX.

The PDF pipeline is built on [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM), which do the actual page-layout reconstruction and Markdown generation. This is the central feature the project was built around. Everything else -- routing, batch handling, merging, and file-manager integration -- is built around that core.

## Supported Formats

- **PDF and E-books**: `.pdf`, `.epub`, `.mobi`, `.fb2`, `.xps`
- **Word and OpenDocument**: `.docx`, `.doc`, `.odt`
- **Spreadsheets**: `.xlsx`, `.xls`, `.csv`
- **Presentations**: `.pptx`, `.ppt`
- **Text and Markdown**: `.txt`, `.md`, `.log`
- **Web pages**: `.html`, `.htm`
- **Google Drive exports**: `.zip` (Google Docs "Web page" export, containing an `.html` file and an optional `images/` folder)
- **Google Docs/Drive links**: public `docs.google.com` (document, spreadsheets, presentation) and `drive.google.com/file` URLs are downloaded automatically; **Drive folders are not supported**

> [!important]
> Legacy binary formats (`.doc`, `.xls`, `.ppt`) require a compatible desktop office suite installed on the same computer as `hammerdown`. These applications are not bundled with `hammerdown`.
>
> - on Windows, the matching desktop Microsoft Office application is tried first, then LibreOffice
> - on Linux and macOS, LibreOffice is required
>
> Modern formats (`.docx`, `.xlsx`, `.pptx`) are processed without an external office suite.

## Table of Contents

- [Output Directory Layout](#output-directory-layout)
- [Installation](#installation)
  - [Recommended: Python package (pip)](#recommended-python-package-pip)
  - [Direct Download (Standalone binaries)](#direct-download-standalone-binaries)
  - [File Manager Context Menu Integration](#file-manager-context-menu-integration)
  - [Logging and Progress Tracking](#logging-and-progress-tracking)
- [Advanced Usage](#advanced-usage)
  - [Command Line Interface](#command-line-interface)
    - [Merging Documents into a Single File](#merging-documents-into-a-single-file)
    - [Streaming to stdout](#streaming-to-stdout)
  - [Python Library Quickstart](#python-library-quickstart)
- [Implementation Notes](#implementation-notes)
  - [Extracting Base64 Images from Markdown](#extracting-base64-images-from-markdown)
  - [Math Formulas and Symbol Normalization](#math-formulas-and-symbol-normalization)
  - [Tables and Spreadsheets](#tables-and-spreadsheets)
- [Credits and Attribution](#credits-and-attribution)
- [Documentation links](#documentation-links)

## Output Directory Layout

Output Markdown files are named after the source document, so `report.docx` becomes `hm_report_docx.md` and `notes.txt` becomes `hm_notes_txt.md`. The source extension is part of the name, which keeps `report.docx` and `report.doc` from overwriting each other.

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

PDF text is converted directly to Markdown without producing an asset folder. Asset folders are created only where the format exposes separate assets: Word charts are rendered as SVG, OpenDocument images are copied out, and base64 images in Markdown are decoded. Presentations and spreadsheets produce Markdown text and tables only. Web page (`.html`) and Google Drive ZIP exports copy their referenced images into the target folder with the same `hm_images_...` naming convention.

## Installation

### Recommended: Python package (pip)

If Python (3.10+) is installed on your system, install via pip:

```sh
pip install hammerdown
```

Or install from local source:

```sh
git clone https://github.com/sergeypugin/hammerdown.git
cd hammerdown
pip install .
```

#### Development install (editable)

To test the latest changes without waiting for a release, install the package in editable mode from the repository. This makes the `hammerdown` command point directly at your local source tree, so edits to `src/` are picked up immediately:

```sh
git clone https://github.com/sergeypugin/hammerdown.git
cd hammerdown
python -m pip install -e .
hammerdown --install
```

`hammerdown --install` registers the file-manager integration using the freshly installed local package, so right-clicking a document uses this build right away.

### Direct Download (Standalone binaries)

If you do not have Python installed, precompiled standalone binaries are available on the [GitHub Releases page](https://github.com/sergeypugin/hammerdown/releases) or you can download directly from the links below:

| OS | Download |
| :--- | :--- |
| **Windows** | [![Windows x64](https://img.shields.io/badge/Windows-x64-0078d7?style=flat-square&logo=windows&logoColor=white)](https://github.com/sergeypugin/hammerdown/releases/latest/download/hammerdown-windows-x64.exe) |
| **Linux** | [![Linux x64](https://img.shields.io/badge/Linux-x64-fcc624?style=flat-square&logo=linux&logoColor=black)](https://github.com/sergeypugin/hammerdown/releases/latest/download/hammerdown-linux-x64) |
| **macOS** | [![macOS x64](https://img.shields.io/badge/macOS-x64-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/sergeypugin/hammerdown/releases/latest/download/hammerdown-macos-x64) [![macOS ARM64](https://img.shields.io/badge/macOS-ARM64-ea4c89?style=flat-square&logo=apple&logoColor=white)](https://github.com/sergeypugin/hammerdown/releases/latest/download/hammerdown-macos-arm64) |

On Linux and macOS, make the downloaded binary executable before running:

```sh
chmod +x ./hammerdown-linux-x64
./hammerdown-linux-x64 --version
```

### File Manager Context Menu Integration

You can integrate `hammerdown` directly into your OS file manager to convert documents with a single right-click, without opening a terminal:

```sh
hammerdown --install
```

What this does:

- on Windows: adds a **Hammer down file** action with an icon to the File Explorer context menu for all supported document formats, adds folder context menu options for recursive directory conversions, creates a **Send to** shortcut (`Send to -> Hammer down`) for first-level access in Windows 11, and activates an IPC coordinator to process multi-file selections in a single terminal window
- on Linux: installs the launcher into `~/.local/bin`, installs a FreeDesktop application entry in `~/.local/share/applications/hammerdown.desktop` with MIME associations, registers KDE Dolphin ServiceMenus in `~/.local/share/kio/servicemenus` and `~/.local/share/kservices5/ServiceMenus`, and adds scripts for Nautilus, Nemo, and Caja (`Scripts -> Hammer down file`)
- on macOS: installs the launcher into `~/.local/bin`, creates an Automator Quick Action in `~/Library/Services/Hammer down.workflow` for the Finder right-click context menu, and generates a drag-and-drop Droplet in `~/Applications/Hammer down.app` with `CFBundleDocumentTypes` for Finder "Open With"

To convert a file or folder, right-click any supported document or folder and select **Hammer down file** (or use **Send to -> Hammer down**). The Markdown output and extracted images are saved directly next to each original document.

On Windows, multi-file selections are collected by a hidden background coordinator and opened in a single Windows Terminal window titled `Hammerdown`, so selecting several documents never produces several console windows. When Windows Terminal is not installed, the same run falls back to one regular console window instead.

On Windows, a second menu item **Hammer down and merge** can combine a selection of files into one Markdown file (equivalent to `hammerdown --merge output.md file1 file2 ...`). The merged file is saved next to the first selected document as `hammerdowned.md`. This static menu item may also appear when only one file is selected; in that case it creates a merged Markdown output with one document. The verb uses a distinct dark red icon (`#48161b`) to distinguish it from the regular **Hammer down file** action.

To remove file manager integration and clean up shortcuts:

```sh
hammerdown --uninstall
```

> [!note]
> `hammerdown --install` updates both context menu items (**Hammer down file** and **Hammer down and merge**) and SendTo shortcuts. Run it after upgrading to refresh launcher scripts.

#### Supported platforms for file-manager integration

File-manager integration is installed only on these systems:

| OS | Supported | Notes |
| :--- | :--- | :--- |
| Windows | yes | File Explorer context menu, SendTo shortcuts |
| macOS | yes | Finder Quick Action and droplet |
| Linux | yes | XDG `.desktop` entries, KDE ServiceMenus, Nautilus/Nemo/Caja scripts |
| FreeBSD and other systems | no | `--install` and `--uninstall` exit with an error |

On unsupported systems the converter itself still works normally from the terminal:

```sh
hammerdown report.pdf
hammerdown -m merged.md report.pdf notes.docx
```

Unknown desktop environments cannot be wired up automatically: every file manager exposes its own extension mechanism, and writing entries blindly could break existing associations with no reliable way to detect or undo it. If you need a context-menu action on a system that is not listed above, add a small adapter as described in [CONTRIBUTING.md](CONTRIBUTING.md#adding-support-for-another-platform) and open a pull request.


To update `hammerdown` to the latest version:

```sh
hammerdown --update
```

> [!warning]
> **Legacy version ambiguity (versions below 2.0.0):** due to a release synchronization conflict on version 1.5.2, run the clean recovery sequence below to avoid environment inconsistencies:
>
> ```sh
> pip uninstall hammerdown -y
> pip install --no-cache-dir hammerdown
> hammerdown --install
> ```
>
> Starting from version 1.5.2, `hammerdown --update` automatically refreshes all launcher scripts and file manager integrations without manual reinstallation.

### Versioning and release tags

`hammerdown` follows semantic versioning. A tag `vX.Y.Z` (for example `v3.1.0`) is a **stable** release: it is marked as the latest and published to PyPI. A tag with a prerelease suffix (for example `v3.1.0-pre1`) is a **preview**: it is published as a GitHub release but is never marked latest and is not pushed to PyPI.

On every push to `main`, the CI workflow inspects the commit messages since the previous `v*` tag and bumps the version automatically, following Conventional Commits:

- `feat!:` or `fix!:` (breaking change) bumps the **major** version
- `feat:` bumps the **minor** version
- `fix:` or `perf:` bumps the **patch** version
- `docs`/`style`/`refactor`/`test`/`build`/`ci`/`chore` do not trigger a bump

The bump applies **once** to the whole range between two tags (the strongest single change wins), not per commit. The bot commit it creates is excluded from the next run, which keeps the workflow from looping. Preview tags (`-pre`, `-pre1`) are created manually when you want a testable build before the next stable release.

Release tags are protected by tag rulesets (`Protect release tags`) on GitHub; the release bot needs `contents: write` permission and must be allowed to create tags for the automatic bump to work.

### Logging and Progress Tracking

When converting documents from the terminal, `hammerdown` renders a live view instead of scrolling log lines. The `Summary` panel shows elapsed time, the preflight estimate, completed files, the running token count, and the number of errors. The `Processing` panel keeps a sliding window of the file queue:

<div align="center">
  <img src="docs/assets/batch-progress.png" alt="Live batch progress" width="600">
</div>

- a completed file gets a green marker and its duration, image count, and token count
- the active file shows an inline progress bar in the state column and its live elapsed time
- queued files are dimmed and show their preflight estimate
- failed files get a red marker and are repeated in a separate `Error list` panel with the failure reason
- the `Processing` panel border is orange while the batch is running and green once it finishes
- the `Results` panel summarizes merged documents, converted files, and extracted images

<div align="center">
  <img src="docs/assets/batch-summary.png" alt="Batch summary, error list, and results" width="600">
</div>

In non-interactive environments (CI pipelines, redirected logs, or non-TTY outputs) no live view is drawn. Each file is announced when it starts and reported when it finishes, and the same `Summary`, `Error list`, and `Results` panels are printed once at the end as plain text without terminal control characters:

```text
Processing report.pdf ~8.1s...
Completed report.pdf (8.1s, ~1_200 tokens)
Processing notes.txt ~0.5s...
Completed notes.txt (0.5s, ~12 tokens)
```

When using `hammerdown` as a Python library, custom progress callbacks can be passed to `to_markdown()` or `convert_file()`:

```python
def on_progress(current: int, total: int, unit: str):
    print(f"Processed {current}/{total} {unit}")

hammerdown.convert_file("report.pdf", progress_callback=on_progress)
```

## Advanced Usage

### Command Line Interface

Run without arguments to see a short description, supported formats, and usage hint:

```sh
hammerdown
```

Convert one or multiple files:

```sh
hammerdown report.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Convert a public Google Docs, Sheets, or Slides link directly (it must be shared as "Anyone with the link"):

```sh
hammerdown "https://docs.google.com/document/d/...."
hammerdown "https://docs.google.com/spreadsheets/d/...."
hammerdown "https://docs.google.com/presentation/d/...."
hammerdown "https://drive.google.com/file/d/...."
```

The HTML export is downloaded to a temporary staging folder, converted, and then removed. Google Drive **folders** (`.../drive/folders/...`) are not supported because they require Drive API authentication, and private documents (HTTP 401) are reported as errors. Images referenced by Google are left as external links in the Markdown, since Google hosts them on `googleusercontent.com` rather than alongside the HTML.

Options:

> [!tip]
> Running `hammerdown` without arguments prints a short description, the list of supported formats, and a hint to run `hammerdown --help` for full usage.
>
> Example output:
>
> ```text
> hammerdown 3.1.0-pre1 is a cross-platform tool and Python library for converting PDF, Word, Excel, PowerPoint, OpenDocument, CSV, and plain-text documents into clean Markdown. Word charts are rendered as SVG, OpenDocument and Markdown images are extracted, and mathematical formulas are converted to LaTeX.
>
> Supported formats: pdf, epub, mobi, fb2, xps, docx, doc, odt, xlsx, xls, pptx, ppt, csv, txt, md, log, html, htm, gdoc, gsheets, gslides, gfile, zip
>
> Run 'hammerdown --help' for usage.
> ```

- `-i`, `--include REGEX` -- only process files whose normalized relative path matches REGEX; may be repeated
- `-e`, `--exclude REGEX` -- skip files whose normalized relative path matches REGEX; may be repeated; exclusions always take priority
- `-w`, `--overwrite` -- overwrite plain-text source files (`.txt`, `.md`) in-place instead of creating a copy
- `-s`, `--skip-existing` -- skip conversion when the target Markdown file already exists; without it, existing `hm_*.md` outputs are overwritten
- `-o`, `--output-dir DIR` -- save Markdown output and extracted images under DIR, preserving the relative layout of the input tree
- `-m`, `--merge OUTPUT_MD` -- merge every converted Markdown document into a single target Markdown file
- `--stdout` -- write the merged Markdown document to stdout; errors go to stderr
- `--confirm` -- with `--stdout`, print a preflight estimate and ask for confirmation before writing anything
- `-v`, `--version` -- display version information

> [!note]
> The `-f` / `--force`, `--in-place`, and `--quiet` flags are not supported. Long option names use hyphens, so `--skip_existing` is rejected; use `--skip-existing` instead.

Include and exclude filters are applied to the path relative to the directory that was passed on the command line. Include narrows the recursive scan first, then exclude removes matches from that set:

```sh
hammerdown -i 'reports/.*' -e '/draft/' folder/
hammerdown -s report.pdf
```

#### Merging Documents into a Single File

`-m` / `--merge` converts many documents and concatenates the results into one Markdown file. This is convenient when you want to feed a whole project folder into an LLM as a single context block:

```sh
hammerdown -m summary.md project/report.pdf project/notes.docx project/drafts/
```

The target file is built incrementally and has two parts.

First, a directory tree of every source document, relative to their common root:

```text
Directory structure:
└── project/
    ├── report.pdf
    ├── notes.docx
    └── drafts/
        └── plan.md
```

Then one block per document. Each block starts with a line of 48 `=` characters, a `FILE:` line with the path relative to the common root, the same separator again, and the converted Markdown:

```text
================================================
FILE: report.pdf
================================================
# Quarterly Report

Revenue grew by 12% in Q3.

================================================
FILE: drafts/plan.md
================================================
# Draft Plan

- collect metrics
- review results
```

Key properties:

- output is written as the batch runs, so a partially converted file is still usable if the run is interrupted
- extracted assets are not mixed with the originals: for the target `summary.md`, images, charts, and decoded pictures are written into `hm_merged_into_summary_images/` next to the target, in subfolders that mirror each document's relative path, and their links are rewritten accordingly
- `--merge` is rejected together with `--overwrite` and with `--output-dir`, so plain-text sources are never modified during a merge
- combined with `-s` / `--skip-existing`, the whole merge is skipped when the target file already exists
- the merge target cannot also be one of the source documents

After the run the sources stay where they were, and the merged file sits next to its assets:

```text
project/
├── report.pdf
├── notes.docx
├── drafts/
│   └── plan.md
├── summary.md
└── hm_merged_into_summary_images/
    ├── hm_images_notes_docx/
    │   └── chart_000.svg
    └── drafts/
        └── hm_images_plan_md/
            └── embedded_img_0.png
```

#### Streaming to stdout

`--stdout` produces the same merged document as `-m`, but writes it to stdout instead of a file, and does not create any intermediate `hm_*.md` files:

```sh
hammerdown --stdout project/ > summary.md
```

Assets are inlined as base64 data URIs, so the stream is self-contained. Progress tables and per-file messages are suppressed; errors go to stderr, and the exit code is non-zero when any document failed.

Add `--confirm` to inspect the cost before anything is printed. Missing paths are reported first, then the preflight line shows the file count, a token estimate for text sources, and an estimated duration. The prompt accepts `y` and `yes`, rejects `n` and `no`, and re-asks on anything else:

```text
[!] drafts: file or directory not found
[!] missing.md: file or directory not found
Preflight: 16 files, ~2_400 tokens from text sources, estimated time ~1m 43.9s.
Continue and write Markdown to stdout? [y/n] Lk
Please answer "y" or "n".
Continue and write Markdown to stdout? [y/n] nO
Cancelled.
```

Only formats that are already plain text (`.txt`, `.md`, `.log`, `.csv`) contribute to the token estimate, because the size of a PDF, DOCX, or XLSX says nothing about the Markdown that comes out of it. For mixed inputs the clause is marked `from text sources`; when no such files are present, the token clause is omitted entirely. `--confirm` requires an interactive stdin; without a terminal it cancels safely instead of waiting. `--stdout` is incompatible with `--merge`, `--output-dir`, `--overwrite`, and `--skip-existing`.

### Python Library Quickstart

Use `hammerdown` directly in your Python code:

```python
import hammerdown

# Convert a file on disk
hammerdown.convert_file("report.pdf", skip_existing=True)

# Get Markdown text in memory
text, image_count = hammerdown.to_markdown("report.docx")

# Convert a batch with CLI-equivalent options
hammerdown.convert_files(["project/"], merge="summary.md", include=[r"reports/.*"])
```

For specialized format converters and low-level helpers, see [docs/PYTHON.md](docs/PYTHON.md).

## Implementation Notes

### Extracting Base64 Images from Markdown

If you have a Markdown file with embedded base64 images, running `hammerdown` with `--overwrite` extracts each image using its MIME type (`png`, `jpeg`, `webp`, `gif`, `svg` and other supported image subtypes) into a sibling folder named after the source. For `LMS.md`, the first decoded image is written as `hm_images_LMS_md/embedded_img_0.png` and the link in the document is rewritten to that path. The image is not converted to PNG: PNG is used only when the source data URI says `image/png`.

```sh
hammerdown LMS.md --overwrite
```

### Math Formulas and Symbol Normalization

Equations inside Word and OpenDocument files are automatically translated into standard LaTeX syntax. Special math characters and Greek letters are mapped using a catalog aligned with official LaTeX references:

- Official Reference: [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf)
- Bundled Copy: [symbols.pdf](symbols.pdf)

### Tables and Spreadsheets

Tables are reconstructed as real Markdown tables instead of loose text:

- **CSV**: the delimiter is detected from the first lines (comma, semicolon, tab, or pipe), and the file is decoded through the same UTF-8, CP1251, CP1252, and Latin-1 fallback chain as other text inputs
- **XLSX**: every worksheet starts with a `# Sheet: Data` heading. Cells with evaluated values use them; when a formula has no cached value, the formula text itself is used. Empty rows and columns at the edges are trimmed, and separate blocks of cells on the same sheet become separate Markdown tables
- **DOCX and PPTX**: table cells are rendered as Markdown rows. Pipes inside a cell are escaped as `\|`, and empty cells are kept so the column layout stays stable

The shared renderer lives in `parsers/markdown_render.py`, and the matrix segmentation logic used by spreadsheets and CSV lives in `parsers/tables.py`.

## Credits and Attribution

- The CLI flag functionality for `-m` / `--merge`, `-i` / `--include`, and `-e` / `--exclude` was adapted from [gitingest](https://github.com/coderamp-labs/gitingest), an excellent reference implementation for packing a directory tree into a single LLM-friendly text blob. `hammerdown` adapts those ideas to document conversion.
- PDF, EPUB, MOBI, FB2, and XPS conversion is powered by [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyMuPDF4LLM](https://github.com/pymupdf/PyMuPDF4LLM). This is the central feature the project was built around.
- Office documents are parsed with [python-docx](https://python-docx.readthedocs.io/), [openpyxl](https://openpyxl.readthedocs.io/), and [python-pptx](https://python-pptx.readthedocs.io/).

## Documentation links

For additional guides and specifications:

- [Python API Reference](docs/PYTHON.md) -- complete guide to Python library methods
- [Technical Reference](docs/TECHNICAL.md) -- internal format processing and parser details
- [Architecture](docs/ARCHITECTURE.md) -- system layers and Mermaid pipeline diagram
- [Performance & Estimation Model](docs/PERFORMANCE.md) -- conversion benchmarks, multi-threading architecture, and ETA model
- [Contributing Guidelines](CONTRIBUTING.md) -- development setup and testing guidelines
