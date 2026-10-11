import os
import uuid
from pathlib import Path
import hammerdown.cli
from hammerdown.ipc import IPCCoordinator, try_delegate_to_coordinator


def _unique_test_pipe() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_test_{uuid.uuid4().hex}"
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return ("127.0.0.1", s.getsockname()[1])


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


def test_cli_delegates_to_active_coordinator(tmp_path: Path, monkeypatch):
    pipe_address = _unique_test_pipe()
    monkeypatch.setenv("HAMMERDOWN_IPC_PIPE", pipe_address if isinstance(pipe_address, str) else "")
    if not isinstance(pipe_address, str):
        monkeypatch.setattr("hammerdown.ipc._get_address", lambda pipe_name=None: pipe_address)

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
