import os
import glob
import subprocess
import sys
from pathlib import Path

def test_golden_conversion():
    inputs_dir = Path("tests/inputs")
    golden_dir = Path("tests/golden")

    # Находим все тестовые файлы
    test_files = list(inputs_dir.glob("*.*"))
    test_files = [f for f in test_files if f.suffix.lower() in ['.pdf', '.docx', '.xlsx']]

    assert len(test_files) > 0, "No test input files found!"

    for file_path in test_files:
        stem = file_path.stem
        print(f"Testing golden output for: {file_path.name}")

        # Запускаем конвертер
        cmd = [sys.executable, "src/converter.py", str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Converter failed for {file_path.name}: {result.stderr}"

        # Путь к сгенерированному файлу
        out_md_path = inputs_dir / f"MD_{stem}" / f"{stem}.md"
        assert out_md_path.is_file(), f"Expected output MD file not found: {out_md_path}"

        # Читаем сгенерированный контент
        generated_content = out_md_path.read_text(encoding="utf-8")

        golden_file_path = golden_dir / f"{stem}.md"

        # Если эталона еще нет — создаем его автоматически при первом запуске
        if not golden_file_path.is_file():
            golden_dir.mkdir(parents=True, exist_ok=True)
            golden_file_path.write_text(generated_content, encoding="utf-8")
            print(f"Created new golden reference for {stem}")
            continue

        golden_content = golden_file_path.read_text(encoding="utf-8")

        # Сверяем с эталоном
        assert generated_content == golden_content, f"Golden test failed for {file_path.name}! Output does not match reference."

if __name__ == "__main__":
    try:
        test_golden_conversion()
        print("\nSUCCESS: All golden tests passed!")
    except AssertionError as e:
        print(f"\nFAILURE: {e}")
        sys.exit(1)
