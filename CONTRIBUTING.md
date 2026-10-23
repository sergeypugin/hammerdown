# Contributing to hammerdown

We welcome contributions to hammerdown.

Please follow these guidelines:

- write commit messages in the Conventional Commits format, for example `feat(cli): add format support` or `fix(tests): resolve assertion mismatch`
- keep changes minimal and focused on the intended feature or fix

## Setting up an environment

Clone the repository, then create a virtual environment and install the project with its development tools. Every command below assumes the environment is active.

```sh
python -m venv venv
```

Activate it:

```sh
# Windows (cmd or PowerShell)
venv\Scripts\activate

# Linux and macOS
source venv/bin/activate
```

Install dependencies and the package itself:

```sh
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
hammerdown --install
```

`python -m venv venv` creates an isolated interpreter in `venv/`, so the project's dependencies never leak into your system Python and two projects can require different versions of the same library. The directory is listed in `.gitignore`: it is local to your machine and is recreated from `requirements.txt` on any other checkout. Delete and recreate it whenever dependency pinning gets confusing.

`requirements.txt` holds the runtime dependencies plus `pytest`, `pytest-xdist` and `pyright`. `python -m pip install -e .` installs the project in editable mode, so the `hammerdown` command resolves to your working copy and picks up edits immediately. The editable install also creates `src/hammerdown.egg-info/`, a generated metadata directory that is ignored by git: never edit it by hand.

`python`, not `python3`, is used in all documented commands. On Windows the `python` launcher always exists while `python3` often does not; on Linux both usually point at the same interpreter. This is about the executable name, not about the language version: the supported version range is declared once in `pyproject.toml` (`requires-python = ">=3.10"`) and checked by `pyrightconfig.json`.

The `hammerdown` command now points at your local `src/`, so edits are picked up immediately. Re-run `hammerdown --install` after changing the set of supported formats so the context menu reflects the new extensions.

The `pyright` configuration points at `./venv`, so run checks through that environment:

```sh
python -m pyright
```

## Running tests and verification

Before submitting a pull request or pushing changes, verify that the test suite passes and existing behavior remains intact:

1. Install required dependencies and test runner:

```sh
python -m pip install -r requirements.txt pytest
```

2. Run the automated test suite:

```sh
python -m pytest
```

3. Run golden comparison tests specifically:

```sh
python tests/test_golden.py
```

4. Test direct document conversion manually:

```sh
python -m hammerdown.cli document.pdf
```

5. Run the static type checker (the project keeps `pyright` at zero errors and zero warnings):

```sh
python -m pyright
```

Checklist before submitting changes:

- all pytest test cases pass without warnings or errors
- `python -m pyright` reports no errors and no warnings
- golden reference files in `tests/golden/` match outputs in `tests/inputs/`
- markdown outputs have clean line endings without trailing whitespace
- no broken character encodings appear in generated markdown files

## Adding support for another platform

The converter and the `hammerdown` command work anywhere Python runs. Only the file-manager
integration is platform-bound: `hammerdown --install` and `hammerdown --uninstall` refuse to run
on a system that has no adapter, because a wrong guess about someone's desktop can break existing
file associations and there is no reliable way to detect or undo the damage afterwards.

Supported adapters today: Windows, macOS and Linux distributions. FreeBSD, OpenBSD, illumos and
other systems are unsupported: the CLI works, the context menu does not. If you want a menu entry
on your system, write an adapter and send a pull request.

### Where the pieces live

```text
src/hammerdown/
├── core/
│   ├── platform_utils.py        # is_windows / is_macos / is_linux helpers
│   ├── ipc.py                   # named-pipe coordinator for multi-file selections
│   └── windows_console.py       # Windows-only console attach; no-op elsewhere
├── parsers/
│   └── math/
│       ├── __init__.py          # OMML and MathML to LaTeX conversion
│       ├── symbols.json         # character to LaTeX command catalog
│       └── symbols.pdf          # source reference the catalog is aligned with
├── integrations/
│   ├── __init__.py              # install/uninstall dispatch, supported-platform gate
│   ├── _common.py               # shared launcher and cleanup helpers
│   ├── windows.py               # registry verbs, SendTo shortcuts
│   ├── windows_terminal.py      # hands a collected selection to Windows Terminal
│   ├── macos.py                 # Finder Quick Action and droplet
│   └── linux.py                 # XDG desktop entries, KDE menus, file-manager scripts
├── batch/__init__.py            # run_batch, coordinator wiring, hand-off to the adapter
└── cli.py                       # argument parsing and early console bootstrap
```

### What an adapter has to provide

An adapter is one module in `src/hammerdown/integrations/` named after the system, for example
`freebsd.py`. It exposes two functions and writes only inside the user's home directory or a
user-scoped registry:

```python
def _install_<os>(command: str, home_dir: Path | None = None) -> None: ...
def _uninstall_<os>(home_dir: Path | None = None) -> None: ...
```

`command` is the already quoted command line that launches hammerdown on this machine, for example
`"/usr/local/bin/python3" "/home/user/.local/share/hammerdown/hammerdown_runner.py"`. Do not build
it yourself: `_installed_command()` in `integrations/__init__.py` already handles frozen binaries and
`pip` installs. Every platform appends its own file list placeholder, so keep `command` as a string
prefix and add the selection marker in the descriptor you generate.

Reuse the helpers from `integrations/_common.py`:

- `_install_launcher(command, home)` writes an executable shim into `~/.local/bin`
- `_quote_if_needed(value)` quotes a path only when it contains a space
- `_remove_install_dir(path)` removes the program directory during uninstall

`home_dir` exists for tests: the test suite passes a temporary directory instead of the real home
and asserts the files that were created and removed.

### Wiring it up

1. `src/hammerdown/core/platform_utils.py`: add a predicate such as `is_freebsd()` that checks
   `sys.platform`, next to the existing `is_windows`, `is_macos` and `is_linux` helpers
2. `src/hammerdown/integrations/__init__.py`: include the predicate in `_platform_is_supported()`
   and dispatch to the new module in `install()` and `uninstall()`
3. `src/hammerdown/integrations/<os>.py`: implement `_install_<os>` and `_uninstall_<os>`
4. `tests/test_integrations.py`: add an install/uninstall round trip against a temporary directory
   that asserts every created file and that uninstall removes it
5. `README.md`: add the system to the supported platforms table

Do not import a platform module at the top of `integrations/__init__.py`. Keep the import inside the
dispatch branch so that an adapter for one OS never gets imported on another.

### Detecting a desktop environment

Linux is a useful reference because it covers several environments at once: it installs XDG entries,
KDE ServiceMenus and scripts for Nautilus, Nemo and Caja from one module, and each part is guarded
by the directory it writes into. Follow the same rule: probe for the environment with
`shutil.which()` or an existing config directory, skip quietly when a probe fails, and never fail
the whole installation because one optional file manager is missing.

### Windows-specific parts

Three modules are Windows-only and must stay out of other adapters:

- `core/windows_console.py` binds an Explorer launch to the parent console; it returns immediately
  on other systems
- `integrations/windows_terminal.py` opens the collected selection in Windows Terminal and falls
  back to a plain console when `wt.exe` is unavailable
- `integrations/windows.py` writes registry verbs and uses `MultiSelectModel=Player` with an IPC
  coordinator, because a static shell verb has no way to require two or more selected files

On Windows, a windowed launcher collects the selection invisibly, then starts one visible worker in
Windows Terminal. The worker receives `--context-worker`, which keeps it out of the coordinator path
in `run_batch`, so the selection is converted exactly once.

`pip` installs and frozen binaries reach the same behaviour from different entry points: a
`pip` install uses `pythonw.exe` as the invisible coordinator and re-executes `python.exe` for the
visible worker, while a frozen build uses the same executable for both roles.

## Building executable for testing on Windows

`hammerdown.spec` is the PyInstaller build recipe. A `.spec` file is executable Python: PyInstaller runs it and takes the resulting `Analysis`, `PYZ` and `EXE` objects as the instructions for the build. It replaces the long command line you would otherwise type, and unlike a command line it can fetch data at build time.

Three things in it are worth knowing:

- `collect_all("package")` copies a dependency's data files, binaries and hidden imports. PyInstaller cannot always detect these statically, so each native dependency (`pymupdf`, `onnxruntime`, `tiktoken`, `regex`, `rich`) is listed explicitly
- the script pre-seeds the `tiktoken` cache under `build/tiktoken-cache` and bakes it into the executable. Without it the first run would have to download the BPE table, which breaks offline use
- `HAMMERDOWN_EXECUTABLE` and `HAMMERDOWN_CONSOLE` are read from the environment, so one spec produces differently named binaries for each platform and can optionally keep a visible console

`build/` and `dist/` are PyInstaller output: `build/` holds intermediate analysis and cache files, `dist/` holds the final executable. Both are git-ignored and safe to delete; a clean build recreates them.

To package and test a standalone Windows executable locally using PyInstaller:

1. Install PyInstaller alongside project dependencies:
  ```sh
  python -m pip install -r requirements.txt pyinstaller
  ```

2. Run the PyInstaller build from the spec file:
  ```sh
  python -m PyInstaller --noconfirm --clean hammerdown.spec
  ```

3. The generated executable is saved in `dist/`. Test it.

`hammerdown.spec` already collects `pymupdf`, `pymupdf4llm`, `onnxruntime`, `tiktoken`, `regex`, `rich`, and the `hammerdown` package, and pre-seeds the tiktoken cache. The `HAMMERDOWN_EXECUTABLE` environment variable controls the output executable name, which the release workflow sets per platform (for example `hammerdown-windows-x64`).

The build entry point is `src/hammerdown/__main__.py`, not `cli.py`: PyInstaller executes the entry script as a top-level `__main__` module, so relative imports inside it fail. `__main__.py` imports `hammerdown.cli` absolutely and `pathex=["src"]` makes the package importable in the frozen app. Keep it that way when adding new packages.

On Windows the executable is built as a GUI-subsystem application (`console=False`). That is what lets Explorer start one process per selected file without flashing a console window for each; the process attaches to the parent terminal when one exists and stays silent otherwise. To build a Windows executable that always opens a console for debugging, set `HAMMERDOWN_CONSOLE=1`:

```sh
HAMMERDOWN_CONSOLE=1 python -m PyInstaller --noconfirm --clean hammerdown.spec
```

The setting is a Windows PE-subsystem switch and has no effect on Linux or macOS builds, which stay console applications.

For full technical specifications and processing pipeline architecture, refer to [docs/TECHNICAL.md](docs/TECHNICAL.md).
