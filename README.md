# md-maker

`md-maker` converts PDF, Word, Excel, PowerPoint, and plain-text documents to Markdown. PDF conversion uses PyMuPDF and PyMuPDF4LLM; source images are extracted into the output folder and Markdown image references are generated.

## Downloads

Release binaries are published for Windows x64, Linux x64, macOS x64, and macOS arm64 on the [GitHub Releases page](https://github.com/sergeypugin/md-maker/releases). The latest release assets can also be downloaded directly:

- Windows x64: [md-maker-windows-x64.exe](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-windows-x64.exe)
- Linux x64: [md-maker-linux-x64](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-linux-x64)
- macOS x64: [md-maker-macos-x64](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-macos-x64)
- macOS arm64: [md-maker-macos-arm64](https://github.com/sergeypugin/md-maker/releases/latest/download/md-maker-macos-arm64)

On Linux and macOS, make the downloaded binary executable before running it:

```sh
chmod +x ./md-maker-linux-x64
./md-maker-linux-x64 --version
```

## Installation

### Standalone release binary

Download the binary for your operating system, then run its built-in installer:

```sh
md-maker --install
```

On Windows, `--install` copies the program to `%LOCALAPPDATA%\Programs\md-maker` and adds a PDF context-menu entry for the current user. On Linux, it installs a Nautilus script and a launcher under `~/.local`. On macOS, it installs the launcher under `~/.local/bin` (the shell command is available there; macOS does not provide a Nautilus-style file-manager script).

Remove the integration and installed files with:

```sh
md-maker --uninstall
```

This installer is local: download the release binary first. It does not fetch software from the network itself. The installation does not require administrator privileges.

### Python package

Python 3.10 or newer is required. Install from a checkout or the Git repository:

```sh
python -m pip install .
```

```sh
python -m pip install "git+https://github.com/sergeypugin/md-maker.git"
```

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

Supported extensions are `.pdf`, `.epub`, `.mobi`, `.fb2`, `.xps`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.txt`, `.md`, `.log`, and `.csv`. Legacy `.doc`, `.xls`, and `.ppt` formats are supported via LibreOffice or Microsoft Office if installed.

For each input file, output is written next to the source:

```text
document.pdf
MD_document/
├── document.md
└── images/
    ├── source images extracted from the PDF
    └── images referenced by the generated Markdown
```

For PDF files, images are written to `MD_<name>/images/`, and the generated Markdown contains relative image links. Conversion continues through a batch if an individual file fails; the process exits with status `1` if any input fails.

## Development

Install dependencies and test tools, then run the suite from the repository root:

```sh
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest
```

Golden outputs live in `tests/golden/` and sample documents in `tests/inputs/`. To publish binaries, push a version tag such as `v0.1.0`. GitHub Actions runs the tests, builds platform-specific single-file executables with PyInstaller, and attaches them to a GitHub Release.
