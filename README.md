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
  - [File Manager Context Menu](#file-manager-context-menu)
- [Usage](#usage)
  - [Command Line Interface](#command-line-interface)
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

### File Manager Context Menu

Register system context menu integration using `--install`:

```sh
hammerdown --install
```

To remove integration:

```sh
hammerdown --uninstall
```

To update `hammerdown` to the latest version:

```sh
hammerdown --update
```

## Usage

### Command Line Interface

Convert one or multiple files:

```sh
hammerdown document.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Options:
- `-i`, `--in-place` -- save output Markdown and extracted images in the same directory as the source file
- `-f`, `--force` -- overwrite existing output Markdown files
- `-q`, `--quiet` -- suppress routine status output
- `-v`, `--version` -- display version information

```sh
hammerdown -i document.pdf
hammerdown -f report.docx
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
- [Contributing Guidelines](CONTRIBUTING.md) -- development setup and testing guidelines
