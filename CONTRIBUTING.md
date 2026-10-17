# Contributing to hammerdown

We welcome contributions to hammerdown.

Please follow these guidelines:

- write commit messages in the Conventional Commits format, for example `feat(cli): add format support` or `fix(tests): resolve assertion mismatch`
- keep changes minimal and focused on the intended feature or fix

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

## Building executable for testing on Windows

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

For full technical specifications and processing pipeline architecture, refer to [docs/TECHNICAL.md](docs/TECHNICAL.md).
