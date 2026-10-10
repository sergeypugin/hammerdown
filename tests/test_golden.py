import glob
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from hammerdown import SUPPORTED_EXTENSIONS


import shutil

import glob
import os
import re
import subprocess
import sys
import shutil
import concurrent.futures
from collections import Counter
from pathlib import Path

from hammerdown import SUPPORTED_EXTENSIONS


def _has_legacy_office_converter() -> bool:
    if shutil.which("soffice") or shutil.which("libreoffice"):
        return True
    if os.name == "nt":
        common_paths = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        if any(p.is_file() for p in common_paths):
            return True
        try:
            import win32com.client
            return True
        except Exception:
            pass
    return False


def _run_single_golden_test(file_path: Path, tmp_path: Path, golden_dir: Path, duplicate_stems: set[str]) -> None:
    stem = file_path.stem
    ext_clean = file_path.suffix.lower().lstrip(".")
    print(f"Testing golden output for: {file_path.name}")

    run_dir = tmp_path / f"{stem}_{ext_clean}"
    run_dir.mkdir(parents=True, exist_ok=True)
    target_input = run_dir / file_path.name
    shutil.copy2(file_path, target_input)

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(Path("src").resolve()), os.environ.get("PYTHONPATH", "")]))}
    cmd = [sys.executable, "-m", "hammerdown.cli", "--force", str(target_input)]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    if result.returncode != 0:
        if "requires LibreOffice or Microsoft" in result.stderr and not _has_legacy_office_converter():
            print(f"Skipping {file_path.name}: legacy office converter not installed in environment")
            return
        assert result.returncode == 0, f"Converter failed for {file_path.name}: {result.stderr}"

    out_md_path = run_dir / f"{stem}_{ext_clean}.md" if ext_clean else run_dir / f"{stem}.md"
    assert out_md_path.is_file(), f"Expected output MD file not found: {out_md_path}"

    generated_content = out_md_path.read_text(encoding="utf-8")

    # Verify images if they are referenced in the markdown
    image_links = re.findall(r"!\[.*?\]\(([^)]+)\)", generated_content)
    for link in image_links:
        if not link.startswith(("http://", "https://", "data:")):
            img_path = run_dir / link
            assert img_path.is_file(), f"Referenced image not found: {img_path}"

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
        return

    golden_content = golden_file_path.read_text(encoding="utf-8")
    assert (
        generated_content == golden_content
    ), f"Golden test failed for {file_path.name}! Output does not match reference."


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

    max_workers = min(len(test_files), os.cpu_count() or 4)
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_single_golden_test, f, tmp_path, golden_dir, duplicate_stems): f
            for f in test_files
        }
        for future in concurrent.futures.as_completed(futures):
            f = futures[future]
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{f.name}: {exc}")

    if errors:
        raise AssertionError("Golden conversion failed for:\n" + "\n".join(errors))


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            test_golden_conversion(Path(tmp_dir))
            print("\nSUCCESS: All golden tests passed!")
        except AssertionError as e:
            print(f"\nFAILURE: {e}")
            sys.exit(1)
