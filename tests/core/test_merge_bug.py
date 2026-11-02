import os
import gc
import hammerdown.cli
from pathlib import Path

import pytest

from hammerdown.core import merge as merge_core
from hammerdown.core.merge import _MERGE_SESSIONS, append_merged_document, initialize_merge_file, merge_asset_paths

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


def test_failed_append_preserves_previous_merge_and_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [tmp_path / f"doc{index}.txt" for index in (1, 2, 3)]
    for index, source in enumerate(sources, start=1):
        source.write_text(f"source {index}\n", encoding="utf-8")

    target = tmp_path / "merged.md"
    target.write_text("previous merge\n", encoding="utf-8")
    assets = tmp_path / "hm_merged_into_merged_images"
    assets.mkdir()
    (assets / "previous.png").write_bytes(b"previous asset")

    initialize_merge_file(target, sources, tmp_path)
    first_handle, first_prefix = merge_asset_paths(sources[0], tmp_path, target)
    Path(first_handle).mkdir(parents=True, exist_ok=True)
    (Path(first_handle) / "one.png").write_bytes(b"staged asset")
    append_merged_document(target, sources[0], "first", tmp_path, first_prefix)

    second_handle, second_prefix = merge_asset_paths(sources[1], tmp_path, target)
    original_render = merge_core.render_merged_document

    def fail_second(source, *args, **kwargs):
        if Path(source).resolve() == sources[1].resolve():
            raise OSError("append failed")
        return original_render(source, *args, **kwargs)

    monkeypatch.setattr(merge_core, "render_merged_document", fail_second)
    with pytest.raises(OSError, match="append failed"):
        append_merged_document(target, sources[1], "second", tmp_path, second_prefix)

    assert _MERGE_SESSIONS[target.resolve()].target_existed
    assert _MERGE_SESSIONS[target.resolve()].had_error
    assert _MERGE_SESSIONS[target.resolve()].appended == 2
    third_handle, third_prefix = merge_asset_paths(sources[2], tmp_path, target)
    append_merged_document(target, sources[2], "third", tmp_path, third_prefix)
    del first_handle, second_handle, third_handle
    gc.collect()

    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert (assets / "previous.png").read_bytes() == b"previous asset"
    assert not list(tmp_path.glob(".hammerdown-merge-*"))
