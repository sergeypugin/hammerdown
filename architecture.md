# md-maker Architecture

## Overview

`md-maker` is a cross-platform command-line utility for converting documents (PDF, Word, Excel, PowerPoint, e-books, plain text) into clean Markdown. For each processed document, a output directory `MD_<name>` is created adjacent to the source file, containing the output Markdown file and an `images/` directory for extracted assets.

## Dependencies

- `pymupdf` -- Low-level PDF document parsing and raw raster image extraction by XREF
- `pymupdf4llm` -- PDF layout analysis and Markdown compilation
- `python-docx` -- Microsoft Word document (.docx) text and table parsing
- `openpyxl` -- Microsoft Excel workbook (.xlsx) table extraction
- `python-pptx` -- Microsoft PowerPoint presentation (.pptx) slide and table parsing
- `onnxruntime` -- Runtime engine for model-based layout structure analysis
- Standard library (`argparse`, `pathlib`, `shutil`, `tempfile`, `subprocess`, `tkinter`, `winreg`) -- CLI, file operations, system integration, fallback file selection dialogs

Runtime dependencies are declared in `requirements.txt` and `pyproject.toml`.

## Execution Scenarios

- CLI terminal execution: `md-maker document.pdf`
- Batch file processing: `md-maker file1.pdf file2.docx`
- Drag-and-drop: Passing files as arguments when dropped onto executable
- Interactive fallback: System file picker dialog opened when launched without arguments
- File manager integration: Context menu via Windows Registry for PDF files, Nautilus script on Linux
- Self-installation: `md-maker --install`; Removal: `md-maker --uninstall`

The installation process is fully local and does not require administrator privileges or network requests. Users download the release binary first. On Windows, `--install` copies the application to `%LOCALAPPDATA%\Programs\md-maker` and registers a user-level shell extension for `.pdf`. On Linux, it places a launcher in `~/.local/bin` and a Nautilus script in `~/.local/share/nautilus/scripts`. On macOS, it installs the launcher script in `~/.local/bin`.

## Processing Pipeline

```mermaid
flowchart TD
    U[User] --> CLI[CLI, Drag-and-Drop, or File Picker]
    CLI --> FILES[Input File List]
    FILES --> PATHS[Path Normalization Windows and WSL]
    PATHS --> LOOP[Batch File Loop]
    LOOP --> TYPE{File Type}
    TYPE -->|PDF, EPUB, MOBI, FB2, XPS| PDF[PyMuPDF: Text and Original Images]
    PDF --> MD[PyMuPDF4LLM: Markdown]
    TYPE -->|DOCX, DOC| DOCX[Extract Text and Tables]
    TYPE -->|XLSX, XLS| XLSX[Convert Worksheets to Markdown Tables]
    TYPE -->|PPTX, PPT| PPTX[Extract Slide Content and Tables]
    TYPE -->|TXT, MD, LOG, CSV| COPY[Copy Plain Text Content]
    MD --> OUTPUT[Write MD_name/name.md and images/]
    DOCX --> OUTPUT
    XLSX --> OUTPUT
    PPTX --> OUTPUT
    COPY --> OUTPUT
    OUTPUT --> RESULT[Exit Status Code Reports Batch Result]
```

## Legacy Format Conversion (.doc, .xls, .ppt)

Legacy Microsoft Office formats are handled by converting them to modern formats (`.docx`, `.xlsx`, `.pptx`) in a temporary directory before parsing:
- **LibreOffice / soffice**: Headless conversion attempted on all platforms.
- **COM Automation (Windows)**: `win32com.client` fallback if Microsoft Office is installed.

If neither conversion engine is available, an actionable error is logged.

## Output Structure

```text
documents/
├── document.pdf
└── MD_document/
    ├── document.md
    └── images/
        ├── document_p001_xref105.png
        └── document_p002_xref112.png
```

Original raster images embedded in PDF files are extracted by XREF reference when their dimensions are at least 50 x 50 pixels.

## Build and Release Pipeline

`pyproject.toml` contains Python package metadata and console entry points. Pushing a tag matching `v*` triggers GitHub Actions workflows:
1. Executes unit and integration test suite.
2. Compiles PyInstaller standalone binaries for Windows x64, Linux x64, macOS x64, and macOS ARM64.
3. Generates SHA256 checksums.
4. Publishes assets to GitHub Releases.
