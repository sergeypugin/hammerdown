# md-maker

[![Tests](https://img.shields.io/github/actions/workflow/status/sergeypugin/md-maker/release.yaml?branch=main&label=tests&logo=github&style=flat-square)](https://github.com/sergeypugin/md-maker/actions)
[![GitHub Release](https://img.shields.io/github/v/release/sergeypugin/md-maker?style=flat-square&color=2ea44f&logo=github)](https://github.com/sergeypugin/md-maker/releases)
[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?style=flat-square)](https://github.com/sergeypugin/md-maker/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-a1ffcb?style=flat-square&labelColor=191919)](CONTRIBUTING.md)

`md-maker` converts PDF, Word, Excel, PowerPoint, and plain-text documents to Markdown. PDF conversion uses PyMuPDF and PyMuPDF4LLM; source images are extracted into the output folder and Markdown image references are generated.

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

If Python (3.10+) is installed on your system, installing via pip is the recommended method. It avoids SmartScreen or antivirus false-positive warnings associated with newly compiled binaries:

```sh
python -m pip install "git+https://github.com/sergeypugin/md-maker.git"
```

Or after cloning the repository locally:

```sh
git clone https://github.com/sergeypugin/md-maker.git
cd md-maker
python -m pip install .
```

### Direct Download (Standalone binaries)

If you do not have Python installed, precompiled standalone binaries are available on the [GitHub Releases page](https://github.com/sergeypugin/md-maker/releases) or you can download directly from the links below:

| OS | Download |
| :--- | :--- |
| **Windows** | [![Windows x64](https://img.shields.io/badge/Windows-x64-0078d7?style=flat-square&logo=windows&logoColor=white)](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-windows-x64.exe) |
| **Linux** | [![Linux x64](https://img.shields.io/badge/Linux-x64-fcc624?style=flat-square&logo=linux&logoColor=black)](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-linux-x64) |
| **macOS** | [![macOS x64](https://img.shields.io/badge/macOS-x64-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-macos-x64) [![macOS ARM64](https://img.shields.io/badge/macOS-ARM64-ea4c89?style=flat-square&logo=apple&logoColor=white)](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-macos-arm64) |

On Linux and macOS, make the downloaded binary executable before running:

```sh
chmod +x ./md-maker-linux-x64
./md-maker-linux-x64 --version
```

### Context menu integration

#### Windows Explorer

Run the installer command in terminal:

```cmd
md-maker --install
```

What happens on Windows:
- the executable or script is copied into `%LOCALAPPDATA%\Programs\md-maker\` (does not require Administrator rights)
- a context menu action is added to current user Registry (`HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\Convert to Markdown`)
- when you right-click any `.pdf` file in Windows Explorer, select **"Show more options"** (or press **Shift + Right Click**), and click **"Convert to Markdown"**, `md-maker` runs silently with `--quiet` and generates the Markdown directory adjacent to the original file

#### Linux

Run the installer command in terminal:

```sh
md-maker --install
```

What happens on Linux:
- creates a launcher script `~/.local/bin/md-maker`
- adds a context menu script into `~/.local/share/nautilus/scripts/Convert to Markdown`
- in GNOME Files (Nautilus), right-click any file -> **Scripts** -> **"Convert to Markdown"**

#### macOS

Run the installer command in terminal:

```sh
md-maker --install
```

What happens on macOS:
- copies the launcher into `~/.local/bin/md-maker` so the command is globally available from Terminal

Remove the integration and installed files with:

```sh
md-maker --uninstall
```

Update md-maker to the latest version at any time:

```sh
md-maker --update
```

This installer is local: run it on the downloaded binary or installed package. It does not require administrator privileges.

## Usage

Convert one or several supported files:

```sh
md-maker document.pdf
md-maker report.docx workbook.xlsx slides.pptx
```

Files can also be dragged onto the executable. Running `md-maker` without file arguments opens a file-selection dialog when a graphical desktop is available. `--quiet` suppresses routine status messages, which is used by file-manager integrations:

```sh
md-maker --quiet document.pdf
md-maker --version
```

## Supported Formats

Supported document extensions:
- **PDF & E-books**: `.pdf`, `.epub`, `.mobi`, `.fb2`, `.xps`
- **Word**: `.docx`, `.doc` (legacy `.doc` via LibreOffice / MS Word)
- **Excel**: `.xlsx`, `.xls` (legacy `.xls` via LibreOffice / MS Excel)
- **PowerPoint**: `.pptx`, `.ppt` (legacy `.ppt` via LibreOffice / MS PowerPoint)
- **Plain text & tabular**: `.txt`, `.md`, `.log`, `.csv`

## Output Structure

For each input file, an output folder `MD_<name>` is written next to the source document:

```text
document.pdf
MD_document/
├── document.md
└── images/
    └── extracted illustration and embedded document images
```

If multiple input files share the same base name with different extensions (such as `report.doc` and `report.docx`), the extension is appended to the folder name (e.g. `MD_report_doc/` and `MD_report_docx/`) to prevent conflicts.

Images embedded in PDF, Word, or PowerPoint documents are extracted into `MD_<name>/images/`, and the generated Markdown contains relative image links. Conversion continues through a batch if an individual file fails; the process exits with status `1` if any input fails.

## Contributing

Contributions are welcome. Please refer to [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.
