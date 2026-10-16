# hammerdown

[![Tests](https://img.shields.io/github/actions/workflow/status/sergeypugin/hammerdown/release.yaml?branch=main&label=tests&logo=github&style=flat-square)](https://github.com/sergeypugin/hammerdown/actions)
[![PyPI](https://img.shields.io/pypi/v/hammerdown?style=flat-square&color=2ea44f&logo=pypi&logoColor=white)](https://pypi.org/project/hammerdown/)
[![GitHub Release](https://img.shields.io/github/v/release/sergeypugin/hammerdown?style=flat-square&color=2ea44f&logo=github)](https://github.com/sergeypugin/hammerdown/releases)
[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?style=flat-square)](https://github.com/sergeypugin/hammerdown/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-a1ffcb?style=flat-square&labelColor=191919)](CONTRIBUTING.md)

<p align="center">
  <img src="assets/logo.svg" alt="hammerdown logo" width="220" height="220">
</p>

`hammerdown` is a cross-platform tool and Python library for converting PDF, Word, Excel, PowerPoint, OpenDocument, CSV, and plain-text documents into clean Markdown. Embedded images, SVG charts, and mathematical formulas are automatically extracted and formatted.

## Table of Contents

- [Installation](#installation)
  - [Recommended: Python package (pip)](#recommended-python-package-pip)
  - [Direct Download (Standalone binaries)](#direct-download-standalone-binaries)
  - [File Manager Context Menu Integration](#file-manager-context-menu-integration)
- [Usage](#usage)
  - [Command Line Interface](#command-line-interface)
  - [Logging and Progress Tracking](#logging-and-progress-tracking)
  - [Extracting Base64 Images from Markdown](#extracting-base64-images-from-markdown)
  - [Python Library Quickstart](#python-library-quickstart)
- [Supported Formats](#supported-formats)
- [Output Directory Layout](#output-directory-layout)
- [Math Formulas and Symbol Normalization](#math-formulas-and-symbol-normalization)
- [Documentation links](#documentation-links)

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

To remove file manager integration and clean up shortcuts:

```sh
hammerdown --uninstall
```

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
> Starting from version 1.5.2, `hammerdown --update` automatically refreshes all launcher scripts and file manager integrations without manual reinstallation. Release tags on GitHub are protected by immutable tag rulesets (`Protect release tags`).

## Usage

### Command Line Interface

Convert one or multiple files:

```sh
hammerdown document.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Options:
- `-i`, `--include REGEX` -- only process files whose normalized relative path matches REGEX; may be repeated
- `-e`, `--exclude REGEX` -- skip files whose normalized relative path matches REGEX; may be repeated; exclusions always take priority
- `-w`, `--overwrite` -- overwrite plain-text source files (`.txt`, `.md`, `.log`, `.csv`) in-place instead of creating a copy
- `-s`, `--skip-existing` -- skip conversion if the target Markdown file already exists (overwriting is enabled by default)
- `-o`, `--output-dir DIR` -- save Markdown output and extracted images under DIR
- `-m`, `--merge OUTPUT_MD` -- merge all converted Markdown documents into a single target Markdown file; the output starts with a directory tree and uses `FILE: relative/path` blocks for each document
- `--stdout` -- write merged Markdown to stdout; diagnostics and errors are written to stderr
- `--confirm` -- with `--stdout`, show an approximate preflight and continue only after an exact `y` response
- `-v`, `--version` -- display version information

> [!note]
> The `-f` / `--force`, `--in-place`, and `--quiet` flags are not supported. Long option names use hyphens, so `--skip_existing` is rejected; use `--skip-existing` instead.

```sh
hammerdown -i 'reports/.*' -e '/draft/' folder/
hammerdown -s document.pdf
hammerdown -m summary.md file1.pdf file2.docx
hammerdown --stdout folder/ > summary.md
hammerdown --stdout --confirm folder/ > summary.md
```

### Logging and Progress Tracking

When converting documents from the terminal, `hammerdown` displays an interactive real-time progress bar indicating the exact progress (e.g., page, slide, or sheet counts):

```text
Processing document.pdf: [████████████░░░░░░░░] 60% (30/50 pages)
Completed document.pdf in 1.4s (3 images extracted)
```

In non-interactive environments (CI/CD pipelines, redirected log files, or non-TTY outputs), progress is logged as periodic status lines starting from 0% without terminal control characters:

```text
[hammerdown] Processing document.pdf (50 pages, est. ~45s)...
[hammerdown] Processing document.pdf: 0/50 pages (0%)...
[hammerdown] Processing document.pdf: 1/50 pages (2%)...
...
[hammerdown] Processing document.pdf: 50/50 pages (100%)...
[hammerdown] Completed document.pdf in 1.4s (3 images extracted)
```

When using `hammerdown` as a Python library, custom progress callbacks can be passed to `to_markdown()` or `convert_file()`:

```python
def on_progress(current: int, total: int, unit: str):
    print(f"Processed {current}/{total} {unit}")

hammerdown.convert_file("document.pdf", progress_callback=on_progress)
```

### Extracting Base64 Images from Markdown

If you have a Markdown file with embedded base64 images, running `hammerdown` with `--overwrite` will extract each image using its MIME type (`png`, `jpeg`, `webp`, `gif`, `svg` and other supported image subtypes) into `hm_images_<stem>_<ext>/` and replace inline base64 data URIs with clean relative links. The image is not converted to PNG: PNG is used only when the source data URI says `image/png`.

```sh
hammerdown document.md --overwrite
```

### Python Library Quickstart

Use `hammerdown` directly in your Python code:

```python
import hammerdown

# Convert a file on disk
hammerdown.convert_file("document.pdf", skip_existing=True)

# Get Markdown text in memory
text, image_count = hammerdown.to_markdown("report.docx")
```

For specialized format converters and low-level helpers, see [docs/PYTHON.md](docs/PYTHON.md).

## Supported Formats

- **PDF and E-books**: `.pdf`, `.epub`, `.mobi`, `.fb2`, `.xps`
- **Word and OpenDocument**: `.docx`, `.doc`, `.odt`
- **Spreadsheets**: `.xlsx`, `.xls`, `.csv`
- **Presentations**: `.pptx`, `.ppt`
- **Text and Markdown**: `.txt`, `.md`, `.log`

> [!important]
> Legacy binary formats (`.doc`, `.xls`, `.ppt`) require a compatible desktop office suite installed on the same computer as `hammerdown`. These applications are not bundled with `hammerdown`.
>
> - on Windows, the matching desktop Microsoft Office application is tried first, then LibreOffice
> - on Linux and macOS, LibreOffice is required
>
> Modern formats (`.docx`, `.xlsx`, `.pptx`) are processed without an external office suite.

## Output Directory Layout

Output Markdown files are saved using the template `hm_<stem>_<ext>.md` to avoid conflicts when files of different formats share the same base name.

**Before conversion:**
```text
folder/
└── document.pdf
```

**After conversion:**
```text
folder/
├── document.pdf
├── hm_document_pdf.md
└── hm_images_document_pdf/
    └── img_p001_xref105.png
```

## Math Formulas and Symbol Normalization

Equations inside Word and OpenDocument files are automatically translated into standard LaTeX syntax. Special math characters and Greek letters are mapped using a catalog aligned with official LaTeX references:

- Official Reference: [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf)
- Bundled Copy: [symbols.pdf](symbols.pdf)

## Documentation links

For additional guides and specifications:

- [Python API Reference](docs/PYTHON.md) -- complete guide to Python library methods
- [Technical Reference](docs/TECHNICAL.md) -- internal format processing and parser details
- [Architecture](docs/ARCHITECTURE.md) -- system layers and Mermaid pipeline diagram
- [Performance & Estimation Model](docs/PERFORMANCE.md) -- conversion benchmarks, multi-threading architecture, and ETA model
- [Contributing Guidelines](CONTRIBUTING.md) -- development setup and testing guidelines
