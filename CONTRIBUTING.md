# Contributing to hammerdown

We welcome contributions to hammerdown.

Please follow these guidelines:

- write commit messages using the Conventional Commits format: `<type>(<scope>): <description>` (for example, `feat(cli): add format support` or `fix(tests): resolve assertion mismatch`)
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
34	python -m hammerdown.cli document.pdf
```

Checklist before submitting changes:

- all pytest test cases pass without warnings or errors
- golden reference files in `tests/golden/` match outputs in `tests/inputs/`
- markdown outputs have clean line endings without trailing whitespace
- no broken character encodings appear in generated markdown files

## Building executable for testing on Windows

To package and test a standalone Windows executable (`hammerdown.exe`) locally using PyInstaller:

1. Install PyInstaller alongside project dependencies:
  ```sh
  python -m pip install -r requirements.txt pyinstaller
  ```

2. Run PyInstaller build command:
  ```sh
  python -m PyInstaller --noconfirm --clean --onefile --name "hammerdown" --icon "assets/icon.ico" --collect-all pymupdf --collect-all pymupdf4llm --collect-all hammerdown src/hammerdown/cli.py
  ```

3. The generated executable will be saved in `dist/hammerdown.exe`. Test it.

For full technical specifications and processing pipeline architecture, refer to [docs/TECHNICAL.md](docs/TECHNICAL.md).
