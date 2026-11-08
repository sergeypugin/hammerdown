import os
import uuid
from pathlib import Path

import pytest

import hammerdown.cli
from hammerdown import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.core import ipc


def _unique_test_pipe() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_test_{uuid.uuid4().hex}"
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return ("127.0.0.1", s.getsockname()[1])


def test_stop_waits_for_server_thread_and_allows_immediate_restart():
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()
    server_thread = coordinator._thread
    assert server_thread is not None

    coordinator.stop()
    assert not server_thread.is_alive()
    coordinator.stop()

    restarted = IPCCoordinator(pipe_name=pipe_address)
    assert restarted.start()
    restarted.stop()


def test_delegated_options_round_trip_with_all_behavior_flags():
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()

    options = {
        "tree": True,
        "all_formats": True,
        "merge": "combined.md",
        "merge_auto": False,
        "include": ["docs/**"],
        "exclude": ["docs/tmp/**"],
        "overwrite": True,
        "skip_existing": False,
        "output": None,
        "stdout": False,
        "confirm": False,
        "include_gitignored": True,
    }
    try:
        assert try_delegate_to_coordinator(["doc.pdf"], options, pipe_name=pipe_address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["doc.pdf"]
        assert coordinator.delegated_options == options
    finally:
        coordinator.stop()


def test_delegated_options_round_trip_preserves_filter_queue():
    options = {
        "include": ["keep*"],
        "exclude": ["*.log"],
        "filter_queue": [("exclude", "*.log"), ("include", "keep*")],
    }

    serialized = ipc._serialize_options(options)

    assert serialized.get("filter_queue") == options["filter_queue"]
    assert serialized["include"] == options["include"]
    assert serialized["exclude"] == options["exclude"]


def test_delegated_options_rejects_malformed_filter_queue():
    with pytest.raises(TypeError, match="filter_queue"):
        ipc._serialize_options({"filter_queue": [("include", 1)]})
    with pytest.raises(TypeError, match="filter_queue"):
        ipc._serialize_options({"filter_queue": [("other", "*.txt")]})


def test_delegated_options_conflict_is_rejected_without_queueing():
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()
    try:
        first = {"tree": True}
        second = {"tree": False}
        assert try_delegate_to_coordinator(["first.txt"], first, pipe_name=pipe_address)
        assert not try_delegate_to_coordinator(["second.txt"], second, pipe_name=pipe_address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["first.txt"]
    finally:
        coordinator.stop()

    serialized = ipc._serialize_options({"output_dir": "out"})
    assert serialized["output"] == "out"
    assert "output_dir" not in serialized


def test_delegated_options_reject_unknown_or_malformed_values():
    with pytest.raises(ValueError, match="unknown delegated option"):
        ipc._serialize_options({"unexpected": True})
    with pytest.raises(TypeError, match="include"):
        ipc._serialize_options({"include": ["ok", 1]})
    with pytest.raises(TypeError, match="tree"):
        ipc._serialize_options({"tree": "yes"})


def test_coordinator_accepts_legacy_file_only_request():
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()

    connection = ipc.Client(pipe_address, authkey=ipc._read_session_secret())
    try:
        connection.send({"files": ["legacy.pdf"]})
        assert connection.recv() == {"status": "ok"}
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["legacy.pdf"]
        assert coordinator.delegated_options == {
            "tree": False,
            "all_formats": False,
            "merge": None,
            "merge_auto": False,
            "include": [],
            "exclude": [],
            "overwrite": False,
            "skip_existing": False,
            "output": None,
            "stdout": False,
            "confirm": False,
            "include_gitignored": False,
        }
    finally:
        connection.close()
        coordinator.stop()


def test_ipc_coordinator_collects_delegated_files():
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()

    try:
        success = try_delegate_to_coordinator(["/path/to/doc2.pdf"], {}, pipe_name=pipe_address)
        assert success

        collected = coordinator.collect_files(["/path/to/doc1.pdf"], assembly_timeout=0.2)
        assert collected == ["/path/to/doc1.pdf", "/path/to/doc2.pdf"]
    finally:
        coordinator.stop()


def test_collect_files_waits_for_quiet_period_after_each_delegate():
    import threading
    import time

    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()

    try:
        assert try_delegate_to_coordinator(["first.pdf"], {}, pipe_name=pipe_address)

        def delegate_later():
            time.sleep(0.1)
            assert try_delegate_to_coordinator(["second.pdf"], {}, pipe_name=pipe_address)

        worker = threading.Thread(target=delegate_later)
        worker.start()
        collected = coordinator.collect_files([], assembly_timeout=0.2)
        worker.join()
        assert collected == ["first.pdf", "second.pdf"]
    finally:
        coordinator.stop()


def test_cli_delegates_to_active_coordinator(tmp_path: Path, monkeypatch):
    pipe_address = _unique_test_pipe()
    monkeypatch.setenv("HAMMERDOWN_IPC_PIPE", pipe_address if isinstance(pipe_address, str) else "")
    if not isinstance(pipe_address, str):
        monkeypatch.setattr("hammerdown.core.ipc._get_address", lambda pipe_name=None: pipe_address)

    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")

    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()

    try:
        assert hammerdown.cli.main(["--coordinator", str(source)]) == 0
        collected = coordinator.collect_files([], assembly_timeout=0.2)
        assert any(str(source) in item for item in collected)
    finally:
        coordinator.stop()


def test_delegate_rejected_after_assembly_closed(monkeypatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    pipe_address = _unique_test_pipe()
    coordinator = IPCCoordinator(pipe_name=pipe_address)
    assert coordinator.start()
    try:
        assert try_delegate_to_coordinator(["first.pdf"], {}, pipe_name=pipe_address)
        coordinator.collect_files([], assembly_timeout=0.05)
        coordinator.close_assembly()
        assert not try_delegate_to_coordinator(["late.pdf"], {}, pipe_name=pipe_address)
    finally:
        coordinator.stop()


def test_delegate_failure_falls_back_to_local_conversion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")

    class DecliningCoordinator:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return False

        def stop(self):
            pass

    monkeypatch.setattr("hammerdown.batch.IPCCoordinator", DecliningCoordinator)
    monkeypatch.setattr("hammerdown.batch.try_delegate_to_coordinator", lambda files, options: False)
    monkeypatch.setattr("builtins.input", lambda *args: "")

    assert hammerdown.cli.main(["--coordinator", str(source)]) == 0
    assert (tmp_path / "hm_notes_txt.md").is_file()
