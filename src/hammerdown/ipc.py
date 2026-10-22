from __future__ import annotations

import logging
import os
import queue
import threading
import time
from multiprocessing.connection import Client, Listener
from typing import Any, Sequence

logger = logging.getLogger("hammerdown")

IPC_PIPE_NAME = r"\\.\pipe\hammerdown_coordinator"
IPC_PORT = 58432
IPC_AUTH_KEY = b"hammerdown-ipc-secret"


def _get_address(pipe_name: str | tuple[str, int] | None = None) -> str | tuple[str, int]:
    if pipe_name:
        return pipe_name
    env_pipe = os.environ.get("HAMMERDOWN_IPC_PIPE")
    if env_pipe:
        return env_pipe
    if os.name == "nt":
        return IPC_PIPE_NAME
    return ("127.0.0.1", IPC_PORT)


def _close_quietly(conn: Any) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def try_delegate_to_coordinator(
    files: Sequence[str],
    options: dict[str, Any],
    pipe_name: str | tuple[str, int] | None = None,
    retries: int = 15,
    retry_delay: float = 0.02,
) -> bool:
    """Hand files to an already running coordinator.

    ``options`` is accepted for call-site compatibility but is not transmitted:
    the receiving instance applies its own command-line options.
    """
    address = _get_address(pipe_name)
    
    for _ in range(retries):
        conn = None
        try:
            conn = Client(address, authkey=IPC_AUTH_KEY)
            conn.send({"files": list(files)})
            response = conn.recv()
            if isinstance(response, dict) and response.get("status") == "ok":
                return True
        except Exception:
            time.sleep(retry_delay)
        finally:
            _close_quietly(conn)

    return False


class IPCCoordinator:
    def __init__(self, pipe_name: str | tuple[str, int] | None = None) -> None:
        self.address = _get_address(pipe_name)
        self.listener: Listener | None = None
        self._incoming_queue: queue.Queue[list[str]] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self.listener = Listener(self.address, authkey=IPC_AUTH_KEY)
            self._running = True
            self._thread = threading.Thread(target=self._server_loop, daemon=True)
            self._thread.start()
            return True
        except Exception:
            return False

    def _server_loop(self) -> None:
        while self._running and self.listener:
            try:
                conn = self.listener.accept()
            except Exception:
                break
            try:
                data = conn.recv()
                files = data.get("files") if isinstance(data, dict) else None
                if isinstance(files, list):
                    new_files = [item for item in files if isinstance(item, str)]
                    if new_files:
                        self._incoming_queue.put(new_files)
                    conn.send({"status": "ok"})
            except Exception:
                logger.debug("Failed to handle coordinator connection", exc_info=True)
            finally:
                _close_quietly(conn)

    def collect_files(self, initial_files: Sequence[str], assembly_timeout: float = 0.35) -> list[str]:
        collected: list[str] = list(initial_files)
        seen = set(collected)
        deadline = time.monotonic() + assembly_timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                batch = self._incoming_queue.get(timeout=remaining)
                for item in batch:
                    if item not in seen:
                        seen.add(item)
                        collected.append(item)
            except queue.Empty:
                break

        return collected

    def stop(self) -> None:
        self._running = False
        if self.listener:
            try:
                self.listener.close()
            except Exception:
                pass
            self.listener = None
