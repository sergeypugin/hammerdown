import os
import hammerdown.cli
from pathlib import Path

def test_merge_existing_output_file_is_used_as_output(tmp_path: Path):
    file1 = tmp_path / "doc1.txt"
    file1.write_text("Hello from file 1\n", encoding="utf-8")

    output_file = tmp_path / "existing_output.md"
    output_file.write_text("Existing content\n", encoding="utf-8")

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert hammerdown.cli.main(["--merge", "existing_output.md", str(file1)]) == 0
    finally:
        os.chdir(original_cwd)

    assert output_file.exists()
    assert "Hello from file 1" in output_file.read_text(encoding="utf-8")
    assert not (tmp_path / "hammerdowned.md").exists()
