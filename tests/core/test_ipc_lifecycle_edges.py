import os
import threading
import uuid
from pathlib import Path

from hammerdown import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.core import ipc


def _unique_test_pipe() -> str | tuple[str, int]:
    if os.name == "nt":
        return rf"\\.\pipe\hammerdown_lifecycle_{uuid.uuid4().hex}"
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return ("127.0.0.1", server.getsockname()[1])


def test_start_twice_preserves_running_session() -> None:
    coordinator = IPCCoordinator(pipe_name=_unique_test_pipe())
    assert coordinator.start()
    first_secret = coordinator._authkey
    first_listener = coordinator.listener
    first_thread = coordinator._thread

    try:
        assert not coordinator.start()
        assert coordinator._authkey == first_secret
        assert coordinator.listener is first_listener
        assert coordinator._thread is first_thread
        assert first_thread is not None and first_thread.is_alive()
        assert try_delegate_to_coordinator(["still-running.txt"], {}, pipe_name=coordinator.address)
        assert coordinator.collect_files([], assembly_timeout=0.2) == ["still-running.txt"]
    finally:
        coordinator.stop()


def test_terminal_accept_error_stops_and_cleans_up(monkeypatch, tmp_path: Path) -> None:
    session_file = tmp_path / "coordinator.session"
    lock_file = tmp_path / "coordinator.lock"
    monkeypatch.setattr(ipc, "IPC_SESSION_FILE", session_file)
    monkeypatch.setattr(ipc, "IPC_LOCK_FILE", lock_file)

    class FailingListener:
        def __init__(self, address, authkey) -> None:
            self.accept_calls = 0
            self.closed = threading.Event()

        def accept(self):
            self.accept_calls += 1
            raise OSError("listener permanently failed")

        def close(self) -> None:
            self.closed.set()

    listeners: list[FailingListener] = []

    def make_listener(address, authkey):
        listener = FailingListener(address, authkey)
        listeners.append(listener)
        return listener

    monkeypatch.setattr(ipc, "Listener", make_listener)
    coordinator = IPCCoordinator(pipe_name=_unique_test_pipe())
    assert coordinator.start()
    server_thread = coordinator._thread
    assert server_thread is not None

    waiter_started = threading.Event()
    waiter_released = threading.Event()

    def wait_for_failure() -> None:
        with coordinator._delivery_condition:
            waiter_started.set()
            while coordinator._running:
                coordinator._delivery_condition.wait()
        waiter_released.set()

    waiter = threading.Thread(target=wait_for_failure)
    waiter.start()
    assert waiter_started.wait(1)
    server_thread.join(1)
    waiter.join(1)

    assert not server_thread.is_alive()
    assert waiter_released.is_set()
    assert listeners[0].accept_calls == 1
    assert listeners[0].closed.is_set()
    assert not coordinator._running
    assert coordinator.listener is None
    assert coordinator._lock_file is None
    assert not session_file.exists()

    assert coordinator.start()
    coordinator.stop()
    assert len(listeners) == 2
    assert listeners[1].accept_calls == 1
    assert all(listener.closed.is_set() for listener in listeners)
    assert not session_file.exists()
    assert coordinator._lock_file is None
    assert lock_file.is_file()
