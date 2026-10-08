# hammerdown

[![Tests](https://img.shields.io/github/actions/workflow/status/sergeypugin/hammerdown/release.yaml?branch=main&label=tests&logo=github&style=flat-square)](https://github.com/sergeypugin/hammerdown/actions)
[![PyPI](https://img.shields.io/pypi/v/hammerdown?style=flat-square&color=2ea44f&logo=pypi&logoColor=white)](https://pypi.org/project/hammerdown/)
[![GitHub Release](https://img.shields.io/github/v/release/sergeypugin/hammerdown?style=flat-square&color=2ea44f&logo=github)](https://github.com/sergeypugin/hammerdown/releases)
[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?style=flat-square)](https://github.com/sergeypugin/hammerdown/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-a1ffcb?style=flat-square&labelColor=191919)](CONTRIBUTING.md)

`hammerdown` converts PDF, Word, Excel, PowerPoint, and plain-text documents to Markdown. PDF conversion uses PyMuPDF and PyMuPDF4LLM; source images are extracted into the output folder and Markdown image references are generated.

## Table of Contents

- [Installation](#installation)
  - [Recommended: Python package (pip)](#recommended-python-package-pip)
  - [Direct Download (Standalone binaries)](#direct-download-standalone-binaries)
  - [Context menu integration](#context-menu-integration)
- [Usage](#usage)
- [Supported Formats](#supported-formats)
- [Output Structure](#output-structure)
- [Contributing](#contributing)

## Installation

### Recommended: Python package (pip)

If Python (3.10+) is installed on your system, installing via pip is the recommended method:

```sh
pip install hammerdown
```

Or after cloning the repository locally:

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

### Context menu integration

Run `--install` to register file manager integrations, or `--uninstall` to remove them:

```sh
hammerdown --install
```

What happens on each platform:
- windows: moves binary or script into `%LOCALAPPDATA%\Programs\hammerdown\` and adds a "Hammer down file" context menu item for PDF files in Windows Explorer
- linux: creates launcher in `~/.local/bin/hammerdown` and Nautilus script in `~/.local/share/nautilus/scripts/Hammer down file`
- macOS: creates launcher in `~/.local/bin/hammerdown`

Update hammerdown to the latest version at any time:

```sh
hammerdown --update
```

This installer is local and does not require administrator privileges.

## Usage

Convert one or several supported files:

```sh
hammerdown document.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Files can also be dragged onto the executable. Running `hammerdown` without file arguments opens a file-selection dialog when a graphical desktop is available. `--quiet` suppresses routine status messages, which is used by file-manager integrations:

```sh
hammerdown --quiet document.pdf
hammerdown --force document.pdf
hammerdown --version
hammerdown --help
```

## Supported Formats

Supported document extensions:
- **PDF & E-books**: `.pdf`, `.epub`, `.mobi`, `.fb2`, `.xps`
- **Word**: `.docx`, `.doc` (legacy `.doc` via LibreOffice / MS Word)
- **Excel**: `.xlsx`, `.xls` (legacy `.xls` via LibreOffice / MS Excel)
- **PowerPoint**: `.pptx`, `.ppt` (legacy `.ppt` via LibreOffice / MS PowerPoint)
- **Plain text & tabular**: `.txt`, `.md`, `.log`, `.csv`

## Output Structure

For each input file, an output folder `MD_<name>_<ext>` is written next to the source document:

```text
document.pdf
MD_document_pdf/
├── document.md
└── images/
    └── extracted illustration and embedded document images
```

Output folder names consistently include the file extension suffix (for example, `MD_report_doc/` and `MD_report_docx/`) to prevent conflicts between different document formats with the same base name.

Images embedded in PDF, Word, or PowerPoint documents are extracted into `MD_<name>_<ext>/images/`, and the generated Markdown contains relative image links. Conversion continues through a batch if an individual file fails; the process exits with status `1` if any input fails.

## Contributing

Contributions are welcome. Please refer to [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines. For architectural details, processing pipelines, and internal specifications, see [TECHNICAL.md](TECHNICAL.md).
