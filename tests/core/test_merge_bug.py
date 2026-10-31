import os
import hammerdown.cli
from pathlib import Path

def test_merge_existing_output_file_is_treated_as_source_bug(tmp_path: Path):
    file1 = tmp_path / "doc1.txt"
    file1.write_text("Hello from file 1\n", encoding="utf-8")

    # This is the file we want to merge INTO, but it already exists
    output_file = tmp_path / "existing_output.md"
    output_file.write_text("Existing content\n", encoding="utf-8")

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        # Due to the convenience heuristic for --merge without output filename,
        # an existing file with a supported extension passed as the first argument
        # is treated as a source file, and the output defaults to hammerdowned.md.
        assert hammerdown.cli.main(["--merge", "existing_output.md", str(file1)]) == 0
    finally:
        os.chdir(original_cwd)

    # Documented behavior: it is treated as a source file, and hammerdowned.md is produced.
    assert (tmp_path / "hammerdowned.md").exists()
