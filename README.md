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
- on Windows: adds a **Hammer down file** action with an icon to the File Explorer context menu for all supported document formats (no administrator privileges required)
- on Linux: installs the executable into `~/.local/bin` and adds a context script for GNOME Nautilus (`Scripts -> Hammer down file`)

To convert a file, right-click any supported document (`.pdf`, `.docx`, etc.) and select **Hammer down file**. The Markdown output and extracted images are saved directly next to the original document.

To remove file manager integration and clean up shortcuts:

```sh
hammerdown --uninstall
```

To update `hammerdown` to the latest version:

```sh
hammerdown --update
```

> [!warning]
> **Note for users upgrading from version 1.5.1 or earlier:** run `hammerdown --install` immediately after updating, or perform a clean reinstall to refresh context menu launcher scripts:
>
> ```sh
> pip uninstall hammerdown -y
> pip install --no-cache-dir hammerdown
> hammerdown --install
> ```
>
> Starting from version 1.5.2, `hammerdown --update` automatically refreshes all launcher scripts and file manager integrations without manual reinstallation.

## Usage

### Command Line Interface

Convert one or multiple files:

```sh
hammerdown document.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Options:
- `-i`, `--in-place` -- save output Markdown and extracted images in the same directory as the source file
- `-w`, `--overwrite` -- overwrite plain-text source files (`.txt`, `.md`, `.log`, `.csv`) in-place instead of creating a copy
- `-f`, `--force` -- overwrite existing output Markdown files
- `-q`, `--quiet` -- suppress routine status output
- `-v`, `--version` -- display version information

```sh
hammerdown -i document.pdf
hammerdown -w notes.txt
hammerdown -f report.docx
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

If you have a Markdown file with embedded base64 images (such as `data:image/png;base64,...`), running `hammerdown` with `--in-place` will extract those raw image strings into PNG or JPEG files inside `hammerdown_images_<stem>_<ext>/` and replace inline base64 data URIs with clean relative links:

```sh
hammerdown document.md --in-place
```

### Python Library Quickstart

Use `hammerdown` directly in your Python code:

```python
import hammerdown

# Convert a file on disk
hammerdown.convert_file("document.pdf", force=True)

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

## Output Directory Layout

Output Markdown files are saved using the template `<stem>_<ext>.md` to avoid conflicts when files of different formats share the same base name.

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

## Math Formulas and Symbol Normalization

Equations inside Word and OpenDocument files are automatically translated into standard LaTeX syntax. Special math characters and Greek letters are mapped using a catalog aligned with official LaTeX references:

- Official Reference: [Rice University LaTeX Symbols Reference](https://cmor-faculty.rice.edu/~heinken/latex/symbols.pdf)
- Bundled Copy: [symbols.pdf](symbols.pdf)

## Documentation links

For additional guides and specifications:

- [Python API Reference](docs/PYTHON.md) -- complete guide to Python library methods
- [Technical Reference](docs/TECHNICAL.md) -- internal format processing and parser details
- [Architecture](docs/ARCHITECTURE.md) -- system layers and Mermaid pipeline diagram
- [Conversion Benchmarks & Estimations](docs/PREDICTIONS.md) -- empirical performance tables and ETA model
- [Contributing Guidelines](CONTRIBUTING.md) -- development setup and testing guidelines
