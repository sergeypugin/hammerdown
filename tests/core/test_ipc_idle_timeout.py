import os
import socket
import time
import uuid

import pytest

from hammerdown import IPCCoordinator
from hammerdown.core import ipc


def _unique_test_pipe() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_idle_{uuid.uuid4().hex}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return ("127.0.0.1", sock.getsockname()[1])


def _wait_for_inflight(coordinator: IPCCoordinator) -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with coordinator._delivery_condition:
            if coordinator._inflight_connections:
                return
        time.sleep(0.005)
    pytest.fail("server did not register the accepted connection")


def test_collect_files_returns_after_accepted_idle_client_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    coordinator = IPCCoordinator(pipe_name=_unique_test_pipe())
    assert coordinator.start()
    connection = ipc.Client(coordinator.address, authkey=ipc._read_session_secret())
    try:
        _wait_for_inflight(coordinator)
        started = time.monotonic()
        assert coordinator.collect_files([], assembly_timeout=0.01) == []
        elapsed = time.monotonic() - started
        assert 0.04 <= elapsed < 0.5
        with coordinator._delivery_condition:
            assert coordinator._inflight_connections == 0
    finally:
        connection.close()
        coordinator.stop()


def test_request_received_before_read_timeout_is_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.2)
    coordinator = IPCCoordinator(pipe_name=_unique_test_pipe())
    assert coordinator.start()
    connection = ipc.Client(coordinator.address, authkey=ipc._read_session_secret())
    try:
        _wait_for_inflight(coordinator)
        connection.send({"files": ["before-timeout.pdf"], "options": {}})
        assert connection.recv() == {"status": "ok"}
        assert coordinator.collect_files([], assembly_timeout=0.05) == ["before-timeout.pdf"]
    finally:
        connection.close()
        coordinator.stop()
