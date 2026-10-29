# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> [!NOTE]
> **Note on historical releases:** Some early releases (v0.1.0–v1.2.1, v3.0.4, v3.1.0-pre1, v3.1.1) have only auto-generated "Full Changelog" notes on GitHub.
>
> [!CAUTION]
> **Broken PyPI releases:** v3.1.0 through v3.1.4 published on PyPI had a packaging configuration issue in `pyproject.toml` missing `core`, `batch`, and `ui` subpackages (causing `ModuleNotFoundError: No module named 'hammerdown.core'`). **v3.2.0 is the first fully working PyPI release in the 3.x series** — please upgrade via `pip install --upgrade hammerdown`.

---

## [3.2.0] - 2026-10-29

### Fixed
- **PyPI wheel package**: use automatic package discovery `[tool.setuptools.packages.find]` in `pyproject.toml` so subpackages (`core`, `batch`, `ui`) are properly included in PyPI wheel builds (resolves `ModuleNotFoundError: No module named 'hammerdown.core'`)

### Added
- **CLI `--upgrade` flag**: add `--upgrade` as a supported CLI alias for `--update`
- **Merge & stdout error blocks**: when a file fails conversion during `--merge` or `--stdout`, an explicit failure block `[!] File conversion failed: <reason>` is rendered directly inside the merged output under the file's section header instead of omitting the section completely

---

## [3.1.4] - 2026-10-24

> [!CAUTION]
> **Broken PyPI package (remains on PyPI)** — `pyproject.toml` omitted `core/`, `batch/`, and `ui/` subpackages from wheel builds. Standalone Windows executable worked, but `pip install hammerdown` failed with `ModuleNotFoundError: No module named 'hammerdown.core'`. Use v3.1.5+.

### Fixed
- **Windows executable**: explicitly bundle `symbols.json` in PyInstaller build (was missing in v3.1.2/v3.1.3, causing `FileNotFoundError: [Errno 2] No such file or directory: 'hammerdown/parsers/math/symbols.json'` on math parser import)
- **Test reliability**: use dynamic `__version__` instead of hardcoded value in CLI test (`tests/core/test_cli.py`)

### Changed
- CI: cache apt packages to speed up LibreOffice installation on subsequent runs
- CI: fix `git tag -l 'v*'` pattern for auto-bump job (was failing with `fatal: 'v*' is not a valid tag name`)

---

## [3.1.3] - 2026-10-24

> [!CAUTION]
> **Broken release (deleted from GitHub Releases, remains on PyPI)** — first attempt to include `symbols.json`, but incomplete. Windows executable fails with `FileNotFoundError`. Use v3.1.4+.

### Fixed
- Remove temporary test files left in repository

### Changed
- Build: explicitly include `symbols.json` in PyInstaller datas (first attempt)

---

## [3.1.2] - 2026-10-24

> [!CAUTION]
> **Broken release (deleted from GitHub Releases, remains on PyPI)** — missing `symbols.json` in Windows executable. Use v3.1.4+.

### Fixed
- Test: fix version assertion and import path in tests after reorganization

---

## [3.1.1] - 2026-10-24

> [!CAUTION]
> **Broken PyPI package (remains on PyPI)** — `pyproject.toml` omitted `core/`, `batch/`, and `ui/` subpackages from wheel builds. Fails with `ModuleNotFoundError: No module named 'hammerdown.core'`. Use v3.2.0+.

> [!NOTE]
> Release notes were auto-generated only (no manual entry).

### Changed
- CI: fix `git tag` pattern for v* matching (use `-l` flag)
- CI: cache apt packages to speed up LibreOffice install
- Docs: remove historical `bug_report_improving.md` (merged branch)

---

## [3.1.0] - 2026-10-24

> [!CAUTION]
> **Broken PyPI package (remains on PyPI)** — `pyproject.toml` omitted `core/`, `batch/`, and `ui/` subpackages from wheel builds after source reorganization. Fails with `ModuleNotFoundError: No module named 'hammerdown.core'`. Use v3.2.0+.

### Added
- **Google Drive/Google Docs support**: fetch public documents, sheets, slides via URL; download and convert to Markdown with images
- **Google Drive HTML export (ZIP) support**: parse exported HTML archives with embedded images
- **`--merge-auto` flag**: automatically merge multiple input files into single `hammerdowned.md` next to first file
- **Windows "Hammer down and merge" context menu verb**: distinct orange icon, creates merged output
- **No-arguments CLI output**: shows description, version, and supported formats table
- **Math formula conversion**: new `hammerdown/parsers/math/` subpackage with `symbols.json` mapping

### Fixed
- **IPC race condition**: file lock (`msvcrt`/`fcntl`) prevents dropped files on simultaneous right-click conversions
- **Google Drive URL false positives**: reject folder URLs, shared drives, generic view pages
- **Temp directory cleanup**: `try/finally` wrapper prevents leaked staging dirs on exceptions
- **Output directory path traversal**: files outside input roots placed directly under output root (no `ValueError`)
- **Windows SendTo Unicode handling**: removed quotes around `%1` in registry command
- **CLI mutual exclusion**: `--merge-auto` properly rejects combinations with `--merge`, `--output-dir`, `--overwrite`, `--skip-existing`, `--stdout`
- **Single-file `--stdout`**: clean output for piping (no progress UI)

### Changed
- **Major refactor**: reorganize source into `core/`, `batch/`, `ui/`, `parsers/` packages
- **Windows binary**: GUI-subsystem executable (`console=False`) with `AllocConsole` fallback
- **Windows Terminal handoff**: frozen GUI binary → IPC coordinator → `wt.exe -w new new-tab` worker
- **Test reorganization**: tests split into `core/`, `integrations/`, `google/`, `office/`, `output/`, `ui/`
- **Documentation refresh**: `ARCHITECTURE.md`, `PERFORMANCE.md`, `TECHNICAL.md`, `CONTRIBUTING.md`, `README.md` updated to match codebase
- **Icons moved** to `assets/` folder with dark red/orange variants for context menu verbs

---

## [3.1.0-pre1] - 2026-10-23

> [!NOTE]
> Prerelease. Release notes were auto-generated only.

### Added
- Google Docs/Drive file link support (HTML export via ZIP)
- Google Docs/Drive export download and ignore cache

---

## [3.0.4] - 2026-10-11

> [!NOTE]
> Release notes were auto-generated only.

### Fixed
- **Windows**: show context verb for mixed selections and allocate one console

### Changed
- CI: treat plain tags as stable and suffixed tags as prereleases

---

## [3.0.3] - 2026-10-11

### Fixed
- **Dependencies**: cap `pymupdf` and `pymupdf4llm` below 2.0
- **UI**: separate queue columns and show elapsed time with estimate

---

## [3.0.1] - 2026-10-11

### Fixed
- **Tests**: make legacy Office checks platform-aware
- **Documentation**: align docs with actual parser and UI behavior

---

## [3.0.0] - 2026-10-11

### Added
- **Batch conversion with interactive terminal UI**: live progress table, status indicators, error reporting
- **Merge mode (`--merge`)**: combine multiple documents into single Markdown file with namespaced assets
- **Streaming stdout pipeline (`--stdout`)**: pipe converted output directly, clean single-file output
- **Preflight token estimation**: estimate token counts before conversion

### Changed
- **Breaking**: finalized 3.0.0 CLI and terminal UI
- **Refactor**: split oversized modules, harden runtime paths
- **UI**: compact batch progress table, dynamic in-place queue with custom hex colors
- **Build**: bundle tiktoken data in standalone builds

### Fixed
- Keyboard interruption handling
- Batch summary and error output refinement
- Terminal handling and live rendering stabilization
- Rich live panel fixed size, duplicate final frames prevention

---

## [2.0.4] - 2026-10-11

### Added
- Complete format estimations for all 16 supported document formats (duration, token count)

### Changed
- UX refinements for batch operations
- Clean terminal progress display

---

## [2.0.3] - 2026-10-11

### Changed
- Version bump with complete format estimations

---

## [2.0.2] - 2026-10-11

### Changed
- Version bump with complete format estimations

---

## [2.0.1] - 2026-10-11

### Added
- Complete format estimations for all supported formats

### Changed
- Documentation updated for 2.0.0 release

---

## [2.0.0] - 2026-10-11

### Added
- **Cross-platform file manager integration**: Windows (registry verbs, SendTo), macOS (Finder Quick Action, droplet), Linux (XDG desktop entries, KDE ServiceMenus, Nautilus/Nemo/Caja scripts)
- **Single-instance coordination on Windows**: named-pipe IPC coordinator for multi-file selections
- **Streamlined output conventions**: consistent naming, image folder structure

### Changed
- Major architecture overhaul for platform adapters
- Windows: `MultiSelectModel=Player` with IPC coordinator

---

## [1.5.2] - 2026-10-11

### Fixed
- **CLI Update Integration**: `hammerdown --update` enforces `--no-cache-dir` during pip upgrades, auto-re-runs integration installation

---

## [1.5.1] - 2026-10-10

### Fixed
- **Square context menu icon**: removed rounded corners (`rx="112"`) from `assets/logo.svg`, regenerated `icon.ico` for clean square display in Windows File Explorer dark theme

---

## [1.5.0] - 2026-10-10

### Added
- **In-place text source overwrite (`-w` / `--overwrite`)**: plain-text formats (`.txt`, `.md`, `.log`, `.csv`) can overwrite source files

---

## [1.4.0] - 2026-10-10

### Added
- **Real-time Progress Tracking**: interactive progress bar displaying progress by pages, slides, sheets
- **GFM LaTeX Math Fixes**: improved math formula rendering

---

## [1.3.2] - 2026-10-10

### Fixed
- **Windows File Dialog**: resolved issue where canceling native PowerShell file picker opened secondary Tkinter dialog
- **Time Estimation**: improvements

---

## [1.3.1] - 2026-10-10

### Changed
- **Isolated Image Folders**: extracted images/charts stored in document-specific subfolders `hammerdown_images_<stem>_<ext>/`

---

## [1.3.0] - 2026-10-10

### Added
- **Public Python API**: exposed dedicated converters and helpers (`convert_docx`, `convert_pdf_or_ebook`, `convert_odt`, `convert_xlsx`, `convert_csv`, etc.)

---

## [1.2.1] - 2026-10-09

> [!NOTE]
> Early development release. Release notes were auto-generated only.

*No detailed notes available (auto-generated changelog only)*

---

## [1.2.0] - 2026-10-09

> [!NOTE]
> Early development release. Release notes were auto-generated only.

*No detailed notes available (auto-generated changelog only)*

---

## [1.1.0] - 2026-10-09

> [!NOTE]
> Early development release. Release notes were auto-generated only.

*No detailed notes available (auto-generated changelog only)*

---

## [1.0.0] - 2026-10-08

> [!NOTE]
> Early development release (renamed from md-maker). Release notes were auto-generated only.

*Initial release*

---

## [0.1.0] - 2026-10-08

> [!NOTE]
> Early development release. Release notes were auto-generated only.

*Initial md-maker release*