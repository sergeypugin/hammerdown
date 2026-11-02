import os
import socket
import threading
import time
import uuid

import pytest

from hammerdown import IPCCoordinator
from hammerdown.core import ipc


def _unique_test_pipe() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_race_{uuid.uuid4().hex}"
    with socket.socket(socket.AF_INET, SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return ("127.0.0.1", sock.getsockname()[1])


class _DelayedConnection:
    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self.closed = threading.Event()

    def recv(self):
        while not self.release.wait(0.01):
            if self.closed.is_set():
                raise OSError("connection closed")
        return {"files": ["delayed.pdf"], "options": {}}

    def close(self) -> None:
        self.closed.set()


def test_collect_files_includes_delivery_accepted_before_quiet_period_ends():
    coordinator = IPCCoordinator()
    release = threading.Event()
    connection = _DelayedConnection(release)

    with coordinator._delivery_condition:
        coordinator._active_connections.add(connection)
        coordinator._inflight_connections = 1

    def deliver() -> None:
        try:
            data = connection.recv()
            request = ipc._deserialize_request(data)
            assert request is not None
            with coordinator._delivery_condition:
                coordinator._incoming_queue.put(request["files"])
                coordinator._delivery_generation += 1
                coordinator._delivery_condition.notify_all()
        finally:
            with coordinator._delivery_condition:
                coordinator._active_connections.discard(connection)
                coordinator._inflight_connections -= 1
                coordinator._delivery_condition.notify_all()

    worker = threading.Thread(target=deliver)
    worker.start()
    result: list[list[str]] = []
    collector = threading.Thread(
        target=lambda: result.append(coordinator.collect_files([], assembly_timeout=0.01))
    )
    collector.start()
    try:
        time.sleep(0.03)
        release.set()
        collector.join(timeout=1)
        assert not collector.is_alive()
        assert result == [["delayed.pdf"]]
    finally:
        release.set()
        collector.join(timeout=1)
        worker.join(timeout=1)
        assert not worker.is_alive()


def test_stop_closes_accepted_idle_connection_before_joining():
    coordinator = IPCCoordinator(pipe_name=_unique_test_pipe())
    assert coordinator.start()
    connection = ipc.Client(coordinator.address, authkey=ipc.IPC_AUTH_KEY)
    deadline = time.monotonic() + 1
    try:
        while time.monotonic() < deadline:
            with coordinator._delivery_condition:
                if coordinator._inflight_connections:
                    break
            time.sleep(0.01)
        else:
            pytest.fail("server did not register the accepted connection")

        started = time.monotonic()
        coordinator.stop()
        assert time.monotonic() - started < 1
        assert coordinator._thread is not None
        assert not coordinator._thread.is_alive()
    finally:
        connection.close()
        coordinator.stop()


def test_collect_files_rejects_non_positive_assembly_timeout():
    coordinator = IPCCoordinator()
    with pytest.raises(ValueError, match="assembly_timeout must be positive"):
        coordinator.collect_files([], assembly_timeout=0)
    with pytest.raises(ValueError, match="assembly_timeout must be positive"):
        coordinator.collect_files([], assembly_timeout=-1)


if __name__ == "__main__":
    pytest.main([__file__])
