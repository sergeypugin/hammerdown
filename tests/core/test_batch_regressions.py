from __future__ import annotations

import argparse
from pathlib import Path

import hammerdown.batch as batch


def _batch_args(*files: str, coordinator: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        files=list(files),
        include=[],
        exclude=[],
        overwrite=False,
        skip_existing=False,
        output_dir=None,
        merge=None,
        merge_auto=False,
        tree=False,
        all_formats=False,
        stdout=False,
        confirm=False,
        include_gitignored=False,
        coordinator=coordinator,
        context_worker=False,
        right_click=False,
    )


def test_google_download_staging_survives_discovery_and_conversion(tmp_path: Path, monkeypatch):
    url = "https://docs.google.com/document/d/staged-document/edit"
    staged_paths: list[Path] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(batch, "is_google_drive_url", lambda value: value == url)

    def fake_download(value: str, target_dir: str | Path) -> Path:
        assert value == url
        staged = Path(target_dir) / "downloaded.txt"
        staged.write_text("downloaded content\n", encoding="utf-8")
        staged_paths.append(staged)
        return staged

    monkeypatch.setattr(batch, "download_google_url", fake_download)

    assert batch.run_batch(_batch_args(url)) == 0
    assert (tmp_path / "hm_downloaded_txt.md").read_text(encoding="utf-8") == "downloaded content\n"
    assert staged_paths
    assert not staged_paths[0].exists()


def test_google_download_does_not_use_async_handoff(tmp_path: Path, monkeypatch):
    url = "https://docs.google.com/document/d/staged-document/edit"
    staged_paths: list[Path] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(batch, "is_google_drive_url", lambda value: value == url)

    def fake_download(value: str, target_dir: str | Path) -> Path:
        assert value == url
        staged = Path(target_dir) / "downloaded.txt"
        staged.write_text("downloaded content\n", encoding="utf-8")
        staged_paths.append(staged)
        return staged

    class FakeCoordinator:
        def start(self) -> bool:
            return True

        def collect_files(self, initial_files, assembly_timeout: float = 2.0):
            assert initial_files
            return initial_files

        def stop(self) -> None:
            pass

    def unexpected_handoff(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Google staging files must be converted before temporary cleanup")

    monkeypatch.setattr(batch, "download_google_url", fake_download)
    monkeypatch.setattr(batch, "IPCCoordinator", FakeCoordinator)
    monkeypatch.setattr(batch, "hand_off_to_windows_terminal", unexpected_handoff)
    monkeypatch.setattr("builtins.input", lambda: "")

    assert batch.run_batch(_batch_args(url, coordinator=True)) == 0
    assert (tmp_path / "hm_downloaded_txt.md").read_text(encoding="utf-8") == "downloaded content\n"
    assert staged_paths
    assert not staged_paths[0].exists()


def test_coordinator_rescan_replaces_missing_file_error(tmp_path: Path, monkeypatch):
    source = tmp_path / "appeared.txt"

    class FakeCoordinator:
        def __init__(self) -> None:
            self.started = False

        def start(self) -> bool:
            self.started = True
            return True

        def collect_files(self, initial_files, assembly_timeout: float = 2.0):
            assert initial_files == []
            source.write_text("appeared during collection\n", encoding="utf-8")
            return []

        def stop(self) -> None:
            pass

    monkeypatch.setattr(batch, "IPCCoordinator", FakeCoordinator)
    monkeypatch.setattr(batch, "hand_off_to_windows_terminal", lambda *args: False)
    monkeypatch.setattr("builtins.input", lambda: "")

    assert batch.run_batch(_batch_args(str(source), coordinator=True)) == 0
    assert (tmp_path / "hm_appeared_txt.md").read_text(encoding="utf-8") == "appeared during collection\n"
