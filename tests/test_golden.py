import glob
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from hammerdown import SUPPORTED_EXTENSIONS


import shutil

def test_golden_conversion(tmp_path: Path):
    inputs_dir = Path("tests/inputs")
    golden_dir = Path("tests/golden")

    test_files = [
        f for f in inputs_dir.glob("*.*")
        if f.suffix.lower() in SUPPORTED_EXTENSIONS and not f.name.startswith("~$")
    ]
    assert len(test_files) > 0, "No test input files found"

    stems = Counter(f.stem for f in test_files)
    duplicate_stems = {stem for stem, count in stems.items() if count > 1}

    for file_path in test_files:
        stem = file_path.stem
        ext_clean = file_path.suffix.lower().lstrip(".")
        print(f"Testing golden output for: {file_path.name}")

        run_dir = tmp_path / f"{stem}_{ext_clean}"
        run_dir.mkdir(parents=True, exist_ok=True)
        target_input = run_dir / file_path.name
        shutil.copy2(file_path, target_input)

        cmd = [sys.executable, "-m", "hammerdown.cli", "--force", str(target_input)]
        result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert result.returncode == 0, f"Converter failed for {file_path.name}: {result.stderr}"

        out_md_path = run_dir / f"{stem}_{ext_clean}.md" if ext_clean else run_dir / f"{stem}.md"
        assert out_md_path.is_file(), f"Expected output MD file not found: {out_md_path}"

        generated_content = out_md_path.read_text(encoding="utf-8")

        specific_golden = golden_dir / f"{stem}_{ext_clean}.md"
        if specific_golden.is_file():
            golden_file_path = specific_golden
        elif stem in duplicate_stems:
            golden_file_path = specific_golden
        else:
            golden_file_path = golden_dir / f"{stem}.md"

        if not golden_file_path.is_file():
            golden_dir.mkdir(parents=True, exist_ok=True)
            golden_file_path.write_text(generated_content, encoding="utf-8")
            print(f"Created new golden reference for {stem}")
            continue

        golden_content = golden_file_path.read_text(encoding="utf-8")
        assert (
            generated_content == golden_content
        ), f"Golden test failed for {file_path.name}! Output does not match reference."


if __name__ == "__main__":
    try:
        test_golden_conversion()
        print("\nSUCCESS: All golden tests passed!")
    except AssertionError as e:
        print(f"\nFAILURE: {e}")
        sys.exit(1)
