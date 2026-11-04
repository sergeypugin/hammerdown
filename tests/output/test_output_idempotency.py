from __future__ import annotations

import base64

import hashlib
from pathlib import Path
import pytest

import hammerdown.batch as batch
import hammerdown.core as core

import hammerdown.core.output as output
from hammerdown.cli import main


Mode = str


def _image_uri(value: str, extension: str = "png") -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"data:image/{extension};base64,{encoded}"


def _markdown_with_images(count: int, extension: str = "png") -> str:
    return "\n".join(
        f"![image {index}]({_image_uri(f'image-{index}', extension)})"
        for index in range(1, count + 1)
    ) + "\n"


def _run(
    source: Path,
    tmp_path: Path,
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip_existing: bool = False,
) -> int:
    monkeypatch.chdir(tmp_path)
    arguments: list[str] = []
    if skip_existing:
        arguments.append("--skip-existing")
    if mode == "merge":
        arguments.extend(["--merge", str(tmp_path / "merged.md")])
    elif mode == "tree":
        arguments.append("--tree")
    arguments.append(str(source))
    return main(arguments)


def _output_paths(source: Path, tmp_path: Path, mode: Mode) -> tuple[Path, Path]:
    if mode == "direct":
        return (
            tmp_path / "hm_source_md.md",
            tmp_path / "hm_images_source_md",
        )
    if mode == "merge":
        return (
            tmp_path / "merged.md",
            tmp_path / "hm_merged_into_merged_images",
        )
    return (
        tmp_path / "hammerdowned.md",
        tmp_path / "hm_merged_into_hammerdowned_images",
    )


def _snapshot(path: Path) -> dict[str, str]:
    paths = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
    snapshot: dict[str, str] = {}
    if path.is_dir():
        snapshot["."] = "directory"
    for item in paths:
        if item.is_file():
            relative = "." if item == path else item.relative_to(path).as_posix()
            snapshot[relative] = hashlib.sha256(item.read_bytes()).hexdigest()
        elif item.is_dir() and item != path:
            snapshot[item.relative_to(path).as_posix()] = "directory"
    return snapshot


def _combined_snapshot(markdown: Path, assets: Path) -> tuple[dict[str, str], dict[str, str]]:
    return _snapshot(markdown), _snapshot(assets)


@pytest.mark.parametrize("mode", ["direct", "merge", "tree"])
def test_successful_rerun_removes_stale_assets(
    tmp_path: Path,
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(3), encoding="utf-8")

    assert _run(source, tmp_path, mode, monkeypatch) == 0
    markdown, assets = _output_paths(source, tmp_path, mode)
    assert markdown.is_file()
    assert len(list(assets.rglob("*.png"))) == 3

    source.write_text(_markdown_with_images(1), encoding="utf-8")
    assert _run(source, tmp_path, mode, monkeypatch) == 0
    assert [path.name for path in assets.rglob("*.png")] == ["embedded_img_1.png"]
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "embedded_img_2.png" not in markdown_text
    if mode != "direct":
        assert markdown_text.count("FILE: source.md") == 1

    source.write_text(_markdown_with_images(0), encoding="utf-8")
    assert _run(source, tmp_path, mode, monkeypatch) == 0
    assert not list(assets.rglob("*.png"))
    assert not assets.exists()
    if mode != "direct":
        assert markdown.read_text(encoding="utf-8").count("FILE: source.md") == 1
    assert not list(tmp_path.glob(".hammerdown-merge-*"))


def test_skip_existing_merge_does_not_create_merge_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(1), encoding="utf-8")
    target = tmp_path / "merged.md"
    target.write_text("existing merge\n", encoding="utf-8")

    def unexpected_session(*_args: object, **_kwargs: object):
        raise AssertionError("skip-existing must not create a merge session")

    monkeypatch.setattr(batch, "MergeSession", unexpected_session)
    monkeypatch.chdir(tmp_path)

    assert main(["--merge", str(target), "--skip-existing", str(source)]) == 0
    assert target.read_text(encoding="utf-8") == "existing merge\n"
    assert not list(tmp_path.glob(".hammerdown-merge-*"))


def test_merge_session_construction_failure_cleans_up_ui_and_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("content\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    calls: list[str] = []

    class FakeUI:
        can_redraw = True

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.skipped_files: list[tuple[str, str]] = []

        def print_ignore_files(self, *_args: object, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            calls.append("ui-start")

        def stop(self) -> None:
            calls.append("ui-stop")

    class FakeCoordinator:
        def start(self) -> bool:
            calls.append("coordinator-start")
            return True

        def collect_files(self, files: list[str], assembly_timeout: float) -> list[str]:
            return files

        def stop(self) -> None:
            calls.append("coordinator-stop")

    def fail_session(*_args: object, **_kwargs: object):
        raise OSError("intentional staging failure")

    monkeypatch.setattr(batch, "BatchUI", FakeUI)
    monkeypatch.setattr(batch, "IPCCoordinator", FakeCoordinator)
    monkeypatch.setattr(batch, "hand_off_to_windows_terminal", lambda *_args: False)
    monkeypatch.setattr(batch, "_ensure_console_window", lambda: None)
    monkeypatch.setattr(batch, "MergeSession", fail_session)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OSError, match="intentional staging failure"):
        main(["--coordinator", "--merge", str(target), str(source)])

    assert "ui-start" in calls
    assert "ui-stop" in calls
    assert "coordinator-start" in calls
    assert "coordinator-stop" in calls
    assert not list(tmp_path.glob(".hammerdown-merge-*"))


def test_successful_rerun_removes_previous_asset_extensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(1, "jpeg"), encoding="utf-8")

    assert _run(source, tmp_path, "direct", monkeypatch) == 0
    assets = tmp_path / "hm_images_source_md"
    assert (assets / "embedded_img_1.jpeg").is_file()

    source.write_text(_markdown_with_images(1, "png"), encoding="utf-8")
    assert _run(source, tmp_path, "direct", monkeypatch) == 0
    assert (assets / "embedded_img_1.png").is_file()
    assert not (assets / "embedded_img_1.jpeg").exists()


@pytest.mark.parametrize("mode", ["direct", "merge", "tree"])
def test_skip_existing_preserves_markdown_and_asset_hashes(
    tmp_path: Path,
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(3), encoding="utf-8")

    assert _run(source, tmp_path, mode, monkeypatch) == 0
    markdown, assets = _output_paths(source, tmp_path, mode)
    before = _combined_snapshot(markdown, assets)

    source.write_text(_markdown_with_images(1), encoding="utf-8")
    assert _run(source, tmp_path, mode, monkeypatch, skip_existing=True) == 0
    assert _combined_snapshot(markdown, assets) == before


@pytest.mark.parametrize("mode", ["direct", "merge", "tree"])
def test_failed_rerun_preserves_previous_valid_markdown_and_assets(
    tmp_path: Path,
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(3), encoding="utf-8")

    assert _run(source, tmp_path, mode, monkeypatch) == 0
    markdown, assets = _output_paths(source, tmp_path, mode)
    before = _combined_snapshot(markdown, assets)

    def fail_conversion(*_args: object, **_kwargs: object) -> tuple[str | None, int]:
        raise RuntimeError("intentional conversion failure")

    monkeypatch.setitem(core.CONVERTERS, ".md", fail_conversion)
    source.write_text(_markdown_with_images(1), encoding="utf-8")

    assert _run(source, tmp_path, mode, monkeypatch) == 1
    assert _combined_snapshot(markdown, assets) == before


def test_converter_exception_cleans_staged_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(1), encoding="utf-8")

    def fail_after_writing_assets(path: str, out_dir: str, **_kwargs: object) -> tuple[str | None, int]:
        assets = Path(out_dir) / "hm_images_source_md"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "partial.png").write_bytes(b"partial")
        raise RuntimeError("intentional conversion failure")

    monkeypatch.setitem(core.CONVERTERS, ".md", fail_after_writing_assets)

    assert _run(source, tmp_path, "direct", monkeypatch) == 1
    assert not (tmp_path / "hm_source_md.md").exists()
    assert not (tmp_path / "hm_images_source_md").exists()
    assert not list(tmp_path.glob(".hammerdown-*"))


def test_none_markdown_preserves_previous_merge_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(3), encoding="utf-8")

    assert _run(source, tmp_path, "merge", monkeypatch) == 0
    markdown, assets = _output_paths(source, tmp_path, "merge")
    before = _combined_snapshot(markdown, assets)

    def return_no_markdown(path: str, out_dir: str, **_kwargs: object) -> tuple[str | None, int]:
        staged_assets = Path(out_dir) / "hm_images_source_md"
        staged_assets.mkdir(parents=True, exist_ok=True)
        (staged_assets / "partial.png").write_bytes(b"partial")
        return None, 1

    monkeypatch.setitem(core.CONVERTERS, ".md", return_no_markdown)
    assert _run(source, tmp_path, "merge", monkeypatch) == 1
    assert _combined_snapshot(markdown, assets) == before
    assert not list(tmp_path.glob(".hammerdown-merge-*"))
    assert not list(tmp_path.glob(".hammerdown-*"))


@pytest.mark.parametrize("mode", ["direct", "merge", "tree"])
def test_replace_failure_restores_previous_markdown_and_assets(
    tmp_path: Path,
    mode: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(1), encoding="utf-8")
    assert _run(source, tmp_path, mode, monkeypatch) == 0
    markdown, assets = _output_paths(source, tmp_path, mode)
    before = _combined_snapshot(markdown, assets)

    real_replace = output.os.replace
    installs = 0

    def fail_asset_install(source_path: str | Path, target_path: str | Path) -> None:
        nonlocal installs
        if (
            Path(source_path).name == assets.name
            and Path(source_path).parent.name.startswith(".hammerdown-")
        ):
            installs += 1
            if installs == 1:
                raise OSError("intentional asset install failure")
        real_replace(source_path, target_path)

    monkeypatch.setattr(output.os, "replace", fail_asset_install)
    assert _run(source, tmp_path, mode, monkeypatch) == 1
    assert _combined_snapshot(markdown, assets) == before
    assert not list(tmp_path.glob("*.hammerdown-backup-*"))
    assert not list(tmp_path.glob(".hammerdown-*"))
    assert not list(tmp_path.glob(".hammerdown-merge-*"))


def test_batch_conversion_exception_aborts_merge_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(_markdown_with_images(1), encoding="utf-8")
    target = tmp_path / "merged.md"
    target.write_text("previous merge\n", encoding="utf-8")
    assets = tmp_path / "hm_merged_into_merged_images"
    assets.mkdir()
    (assets / "previous.png").write_bytes(b"previous asset")

    def raise_conversion(*_args: object, **_kwargs: object) -> tuple[str | None, int]:
        raise RuntimeError("intentional conversion exception")

    monkeypatch.setattr(batch, "convert_file", raise_conversion)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="intentional conversion exception"):
        main(["--merge", str(target), str(source)])

    assert not list(tmp_path.glob(".hammerdown-merge-*"))
    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert (assets / "previous.png").read_bytes() == b"previous asset"
    assert not list(tmp_path.glob(".hammerdown-*"))


def test_stdout_conversion_does_not_create_output_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("stdout content\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = core.convert_file(source, stdout=True)

    assert result.success
    assert result.markdown == "stdout content\n"
    assert not list(tmp_path.glob("hm_*.md"))
    assert not list(tmp_path.glob("hm_images_*"))
