from __future__ import annotations

import os
import socket
import threading
import time
import uuid

from hammerdown import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.core import ipc


def _unique_address() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_frame_restart_{uuid.uuid4().hex}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return ("127.0.0.1", sock.getsockname()[1])


def test_old_collector_is_invalidated_across_restart(monkeypatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    address = _unique_address()
    coordinator = IPCCoordinator(pipe_name=address)
    assert coordinator.start()
    old_result: list[list[str]] = []
    old_collector = threading.Thread(
        target=lambda: old_result.append(coordinator.collect_files([], assembly_timeout=0.1))
    )
    old_collector.start()

    try:
        time.sleep(0.02)
        coordinator.stop()
        assert coordinator.start()
        assert try_delegate_to_coordinator(["after-restart.txt"], {}, pipe_name=address)

        old_collector.join(timeout=1)
        assert not old_collector.is_alive()
        assert old_result == [[]]
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["after-restart.txt"]
    finally:
        old_collector.join(timeout=1)
        coordinator.stop()
def test_partial_authenticated_frame_cannot_hold_server_past_read_deadline(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    coordinator = IPCCoordinator(pipe_name=_unique_address())
    assert coordinator.start()
    connection = ipc.Client(coordinator.address, authkey=ipc._read_session_secret())
    try:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with coordinator._delivery_condition:
                if coordinator._inflight_connections:
                    break
            time.sleep(0.005)
        else:
            raise AssertionError("server did not register the authenticated connection")

        started = time.monotonic()
        assert coordinator.collect_files([], assembly_timeout=0.01) == []
        assert time.monotonic() - started < 0.5
        with coordinator._delivery_condition:
            assert coordinator._inflight_connections == 0
    finally:
        connection.close()
        coordinator.stop()


def test_stop_and_restart_drop_old_delivery_state(monkeypatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    address = _unique_address()
    coordinator = IPCCoordinator(pipe_name=address)
    assert coordinator.start()
    try:
        assert try_delegate_to_coordinator(["before-restart.txt"], {"tree": True}, pipe_name=address)
        coordinator.stop()

        assert coordinator.start()
        assert coordinator.collect_files([], assembly_timeout=0.05) == []
        assert coordinator.delegated_options is None
        assert try_delegate_to_coordinator(["after-restart.txt"], {}, pipe_name=address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["after-restart.txt"]
    finally:
        coordinator.stop()


def test_partial_frame_does_not_prevent_later_valid_request(monkeypatch) -> None:
    monkeypatch.setattr(ipc, "IPC_REQUEST_READ_TIMEOUT", 0.05)
    coordinator = IPCCoordinator(pipe_name=_unique_address())
    assert coordinator.start()
    partial = ipc.Client(coordinator.address, authkey=ipc._read_session_secret())
    try:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with coordinator._delivery_condition:
                if coordinator._inflight_connections:
                    break
            time.sleep(0.005)
        else:
            raise AssertionError("server did not register the partial-frame connection")

        assert try_delegate_to_coordinator(["valid-after-partial.txt"], {}, pipe_name=coordinator.address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["valid-after-partial.txt"]
    finally:
        partial.close()
        coordinator.stop()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
