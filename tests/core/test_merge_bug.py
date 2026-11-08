import os

import hammerdown.cli
from pathlib import Path

import pytest

from hammerdown.core import merge as merge_core
from hammerdown.core.merge import (
    MergeSession,
    append_merged_document,
    initialize_merge_file,
    merge_asset_paths,
)

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


def test_explicit_merge_abort_discards_staging_and_preserves_previous_outputs(tmp_path: Path) -> None:
    source = tmp_path / "doc.txt"
    source.write_text("source\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    target.write_text("previous merge\n", encoding="utf-8")
    assets = tmp_path / "hm_merged_into_merged_images"
    assets.mkdir()
    (assets / "previous.png").write_bytes(b"previous asset")

    owner = MergeSession(target)
    initialize_merge_file(target, [source], tmp_path, owner)
    asset_path, asset_prefix = merge_asset_paths(source, tmp_path, target, owner)
    Path(asset_path).mkdir(parents=True, exist_ok=True)
    (Path(asset_path) / "staged.png").write_bytes(b"staged asset")
    staging_path = owner._state.staging.path

    owner.abort()
    owner.abort()

    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert (assets / "previous.png").read_bytes() == b"previous asset"
    assert not staging_path.exists()
    assert asset_prefix == Path(assets.name)


def test_explicit_merge_finish_preserves_append_order(tmp_path: Path) -> None:
    sources = [tmp_path / f"doc{index}.txt" for index in (1, 2, 3)]
    for index, source in enumerate(sources, start=1):
        source.write_text(f"source {index}\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    owner = MergeSession(target)
    initialize_merge_file(target, sources, tmp_path, owner)

    for index, source in enumerate(sources, start=1):
        _, asset_prefix = merge_asset_paths(source, tmp_path, target, owner)
        append_merged_document(target, source, f"content {index}", tmp_path, asset_prefix, session=owner)

    owner.finish()
    merged = target.read_text(encoding="utf-8")
    assert merged.index("FILE: doc1.txt") < merged.index("FILE: doc2.txt") < merged.index("FILE: doc3.txt")



def test_append_rejects_out_of_order_source_without_advancing_session(tmp_path: Path) -> None:
    sources = [tmp_path / f"doc{index}.txt" for index in (1, 2)]
    for source in sources:
        source.write_text("source\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    owner = MergeSession(target)
    initialize_merge_file(target, sources, tmp_path, owner)

    _, asset_prefix = merge_asset_paths(sources[0], tmp_path, target, owner)
    with pytest.raises(ValueError, match="appended in order"):
        append_merged_document(target, sources[1], "out of order", tmp_path, asset_prefix, session=owner)

    assert owner._state.appended == 0
    append_merged_document(target, sources[0], "first", tmp_path, asset_prefix, session=owner)
    owner.abort()


def test_concurrent_merge_sessions_for_same_target_are_isolated(tmp_path: Path) -> None:
    source = tmp_path / "doc.txt"
    source.write_text("source\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    first = MergeSession(target)
    second = MergeSession(target)
    assert first._state.staging.path != second._state.staging.path

    initialize_merge_file(target, [source], tmp_path, first)
    initialize_merge_file(target, [source], tmp_path, second)
    _, first_prefix = merge_asset_paths(source, tmp_path, target, first)
    _, second_prefix = merge_asset_paths(source, tmp_path, target, second)
    append_merged_document(target, source, "first session", tmp_path, first_prefix, session=first)
    append_merged_document(target, source, "second session", tmp_path, second_prefix, session=second)

    first.finish()
    assert "first session" in target.read_text(encoding="utf-8")
    assert second._state.staging.path.is_dir()
    second.abort()
    assert not second._state.staging.path.exists()


def test_failed_append_preserves_previous_merge_and_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [tmp_path / f"doc{index}.txt" for index in (1, 2, 3)]
    for index, source in enumerate(sources, start=1):
        source.write_text(f"source {index}\n", encoding="utf-8")

    target = tmp_path / "merged.md"
    target.write_text("previous merge\n", encoding="utf-8")
    assets = tmp_path / "hm_merged_into_merged_images"
    assets.mkdir()
    (assets / "previous.png").write_bytes(b"previous asset")

    owner = MergeSession(target)
    initialize_merge_file(target, sources, tmp_path, owner)
    first_asset_path, first_prefix = merge_asset_paths(sources[0], tmp_path, target, owner)
    Path(first_asset_path).mkdir(parents=True, exist_ok=True)
    (Path(first_asset_path) / "one.png").write_bytes(b"staged asset")
    append_merged_document(target, sources[0], "first", tmp_path, first_prefix, session=owner)

    _, second_prefix = merge_asset_paths(sources[1], tmp_path, target, owner)
    original_render = merge_core.render_merged_document

    def fail_second(source, *args, **kwargs):
        if Path(source).resolve() == sources[1].resolve():
            raise OSError("append failed")
        return original_render(source, *args, **kwargs)

    monkeypatch.setattr(merge_core, "render_merged_document", fail_second)
    with pytest.raises(OSError, match="append failed"):
        append_merged_document(target, sources[1], "second", tmp_path, second_prefix, session=owner)

    assert owner._state.target_existed
    assert owner._state.had_error
    assert owner._state.appended == 2
    _, third_prefix = merge_asset_paths(sources[2], tmp_path, target, owner)
    append_merged_document(target, sources[2], "third", tmp_path, third_prefix, session=owner)
    owner.finish()

    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert (assets / "previous.png").read_bytes() == b"previous asset"
    assert not list(tmp_path.glob(".hammerdown-merge-*"))


def test_merge_session_rejects_foreign_holder_of_same_target(tmp_path: Path):
    target = tmp_path / "merged.md"
    target.write_text("previous\n", encoding="utf-8")
    lock_path = target.parent / f".{target.name}.hammerdown-merge.lock"

    foreign = open(lock_path, "w", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(foreign.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(foreign.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(OSError, match="another hammerdown process"):
            MergeSession(target)
    finally:
        if os.name == "nt":
            import msvcrt

            foreign.seek(0)
            msvcrt.locking(foreign.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(foreign.fileno(), fcntl.LOCK_UN)
        foreign.close()

    session = MergeSession(target)
    session.abort()
    assert not lock_path.exists()
