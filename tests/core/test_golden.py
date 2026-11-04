import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hammerdown import SUPPORTED_EXTENSIONS

LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt"}
pytestmark = pytest.mark.integration


def _has_legacy_office_converter() -> bool:
    if shutil.which("soffice") or shutil.which("libreoffice"):
        return True
    if sys.platform == "darwin":
        mac_path = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if mac_path.is_file():
            return True
    if os.name == "nt":
        common_paths = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        if any(p.is_file() for p in common_paths):
            return True
        try:
            import winreg
            for app in ("WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE"):
                key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{app}"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path):
                        return True
                except OSError:
                    continue
        except ImportError:
            pass
    return False


def _run_single_golden_test(file_path: Path, tmp_path: Path, golden_dir: Path) -> None:
    stem = file_path.stem
    ext_clean = file_path.suffix.lower().lstrip(".")
    print(f"Testing golden output for: {file_path.name}")

    run_dir = tmp_path / f"{stem}_{ext_clean}"
    run_dir.mkdir(parents=True, exist_ok=True)
    target_input = run_dir / file_path.name
    shutil.copy2(file_path, target_input)
    source_links: list[str] = []
    if file_path.suffix.lower() in {".md", ".txt"}:
        source_links = re.findall(r"!\[.*?\]\(([^)]+)\)", file_path.read_text(encoding="utf-8"))
    for link in source_links:
        if link.startswith(("http://", "https://", "data:")):
            continue
        source_resource = file_path.parent / link
        target_resource = run_dir / link
        if source_resource.is_file():
            target_resource.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_resource, target_resource)

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(Path("src").resolve()), os.environ.get("PYTHONPATH", "")]))}
    cmd = [sys.executable, "-m", "hammerdown.cli", str(target_input)]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    if result.returncode != 0:
        assert result.returncode == 0, f"Converter failed for {file_path.name}: {result.stderr}"

    out_md_path = run_dir / f"hm_{stem}_{ext_clean}.md" if ext_clean else run_dir / f"hm_{stem}.md"
    assert out_md_path.is_file(), f"Expected output MD file not found: {out_md_path}"

    generated_content = out_md_path.read_text(encoding="utf-8")

    # Verify images if they are referenced in the markdown
    image_links = re.findall(r"!\[.*?\]\(([^)]+)\)", generated_content)
    for link in image_links:
        if not link.startswith(("http://", "https://", "data:")):
            img_path = run_dir / link
            assert img_path.is_file(), f"Referenced image not found: {img_path}"

    golden_file_path = golden_dir / f"hm_{stem}_{ext_clean}.md" if ext_clean else golden_dir / f"hm_{stem}.md"

    if not golden_file_path.is_file():
        golden_dir.mkdir(parents=True, exist_ok=True)
        golden_file_path.write_text(generated_content, encoding="utf-8")
        print(f"Created new golden reference for {stem}")
        return

    golden_content = golden_file_path.read_text(encoding="utf-8")
    assert (
        generated_content == golden_content
    ), f"Golden test failed for {file_path.name}! Output does not match reference."


def _golden_inputs() -> list[Path]:
    inputs_dir = Path("tests/inputs")
    return sorted(
        f for f in inputs_dir.glob("*.*")
        if f.suffix.lower() in SUPPORTED_EXTENSIONS
        and not f.name.startswith(("~$", "hm_"))
    )


@pytest.mark.parametrize(
    "file_path",
    [
        pytest.param(
            file_path,
            marks=pytest.mark.requires_office
            if file_path.suffix.lower() in LEGACY_OFFICE_EXTENSIONS
            else (),
            id=file_path.name,
        )
        for file_path in _golden_inputs()
    ],
)
def test_golden_conversion(file_path: Path, tmp_path: Path) -> None:
    if file_path.suffix.lower() in LEGACY_OFFICE_EXTENSIONS and not _has_legacy_office_converter():
        pytest.skip("requires Microsoft Office or LibreOffice")

    _run_single_golden_test(file_path, tmp_path, Path("tests/golden"))


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            for file_path in _golden_inputs():
                if file_path.suffix.lower() in LEGACY_OFFICE_EXTENSIONS and not _has_legacy_office_converter():
                    print(f"Skipping {file_path.name}: requires Microsoft Office or LibreOffice")
                    continue
                _run_single_golden_test(file_path, Path(tmp_dir), Path("tests/golden"))
            print("\nSUCCESS: All golden tests passed!")
        except AssertionError as e:
            print(f"\nFAILURE: {e}")
            sys.exit(1)
