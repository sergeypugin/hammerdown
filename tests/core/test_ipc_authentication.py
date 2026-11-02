import os
import socket
import threading
import uuid
from pathlib import Path

import pytest

from hammerdown import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.core import ipc


def _unique_address() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_auth_{uuid.uuid4().hex}"
    with socket.socket(socket.AF_INET, SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return ("127.0.0.1", sock.getsockname()[1])


@pytest.fixture
def isolated_ipc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    session_file = tmp_path / "session" / "coordinator.secret"
    monkeypatch.setattr(ipc, "IPC_SESSION_FILE", session_file)
    monkeypatch.setattr(ipc, "IPC_LOCK_FILE", tmp_path / "coordinator.lock")
    return session_file


def _start(address: str | tuple[str, int]) -> IPCCoordinator:
    coordinator = IPCCoordinator(pipe_name=address)
    assert coordinator.start()
    return coordinator


def test_secret_is_random_for_each_coordinator_lifecycle(isolated_ipc: Path) -> None:
    address = _unique_address()
    first = _start(address)
    try:
        first_secret = isolated_ipc.read_bytes()
    finally:
        first.stop()
    assert not isolated_ipc.exists()

    second = _start(address)
    try:
        second_secret = isolated_ipc.read_bytes()
    finally:
        second.stop()

    assert len(first_secret) == 32
    assert len(second_secret) == 32
    assert first_secret != second_secret


def test_valid_delegation_discovers_session_secret(isolated_ipc: Path) -> None:
    coordinator = _start(_unique_address())
    try:
        assert try_delegate_to_coordinator(["document.pdf"], {}, pipe_name=coordinator.address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["document.pdf"]
    finally:
        coordinator.stop()


def test_wrong_secret_is_rejected(isolated_ipc: Path) -> None:
    coordinator = _start(_unique_address())
    finished = threading.Event()
    result: list[bool] = []

    def connect_with_wrong_secret() -> None:
        connection = None
        try:
            connection = ipc.Client(coordinator.address, authkey=b"wrong" * 8)
            result.append(True)
        except Exception:
            result.append(False)
        finally:
            if connection is not None:
                connection.close()
            finished.set()

    worker = threading.Thread(target=connect_with_wrong_secret, daemon=True)
    worker.start()
    try:
        assert finished.wait(1), "wrong authentication handshake did not complete"
        assert result == [False]
        assert coordinator.collect_files([], assembly_timeout=0.1) == []
    finally:
        coordinator.stop()


def test_wrong_secret_does_not_stop_server(isolated_ipc: Path) -> None:
    coordinator = _start(_unique_address())
    try:
        connection = None
        try:
            connection = ipc.Client(coordinator.address, authkey=b"wrong" * 8)
        except Exception:
            pass
        finally:
            if connection is not None:
                connection.close()

        assert try_delegate_to_coordinator(["after-wrong-secret.pdf"], {}, pipe_name=coordinator.address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["after-wrong-secret.pdf"]
    finally:
        coordinator.stop()


@pytest.mark.parametrize("contents", [b"", b"not a coordinator secret", b"0" * 31])
def test_missing_or_corrupt_secret_fails_cleanly(
    isolated_ipc: Path, contents: bytes
) -> None:
    address = _unique_address()
    isolated_ipc.parent.mkdir()
    isolated_ipc.write_bytes(contents)
    assert not try_delegate_to_coordinator(["document.pdf"], {}, pipe_name=address, retries=1, retry_delay=0)


def test_missing_secret_fails_cleanly(isolated_ipc: Path) -> None:
    assert not try_delegate_to_coordinator(
        ["document.pdf"], {}, pipe_name=_unique_address(), retries=1, retry_delay=0
    )


def test_stop_removes_owned_secret_and_restart_works(isolated_ipc: Path) -> None:
    address = _unique_address()
    coordinator = _start(address)
    coordinator.stop()
    assert not isolated_ipc.exists()

    restarted = _start(address)
    try:
        assert try_delegate_to_coordinator(["after-restart.pdf"], {}, pipe_name=address)
        assert restarted.collect_files([], assembly_timeout=0.2) == ["after-restart.pdf"]
    finally:
        restarted.stop()


def test_non_owner_cannot_overwrite_owner_secret(isolated_ipc: Path) -> None:
    address = _unique_address()
    owner = _start(address)
    try:
        owner_secret = isolated_ipc.read_bytes()
        contender = IPCCoordinator(pipe_name=address)
        assert not contender.start()
        assert isolated_ipc.read_bytes() == owner_secret
        assert try_delegate_to_coordinator(["owner.pdf"], {}, pipe_name=address)
        assert owner.collect_files([], assembly_timeout=0.2) == ["owner.pdf"]
    finally:
        owner.stop()


def test_session_secret_file_is_private(isolated_ipc: Path) -> None:
    coordinator = _start(_unique_address())
    try:
        if os.name != "nt":
            assert isolated_ipc.stat().st_mode & 0o777 == 0o600
            assert isolated_ipc.parent.stat().st_mode & 0o777 == 0o700
    finally:
        coordinator.stop()


if __name__ == "__main__":
    pytest.main([__file__])
