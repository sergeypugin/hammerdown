from __future__ import annotations

import contextlib
import logging
import os
import queue
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict, cast


logger = logging.getLogger("hammerdown")

IPC_PIPE_NAME = r"\\.\pipe\hammerdown_coordinator"
IPC_PORT = 58432
IPC_AUTH_KEY = b"hammerdown-ipc-secret"
IPC_LOCK_FILE = Path(tempfile.gettempdir()) / "hammerdown_coordinator.lock"


class DelegatedOptions(TypedDict):
    tree: bool
    all_formats: bool
    merge: str | None
    merge_auto: bool
    include: list[str]
    exclude: list[str]
    overwrite: bool
    skip_existing: bool
    output: str | None
    stdout: bool
    confirm: bool
    include_gitignored: bool


class DelegatedOptionsWithQueue(DelegatedOptions, total=False):
    filter_queue: list[tuple[str, str]]


class DelegatedRequest(TypedDict):
    files: list[str]
    options: DelegatedOptionsWithQueue


_OPTION_DEFAULTS: DelegatedOptions = {
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
_OPTION_KEYS = frozenset((*_OPTION_DEFAULTS, "filter_queue"))


def _serialize_options(options: Mapping[str, Any] | None) -> DelegatedOptionsWithQueue:
    """Validate and normalize options before they cross the process boundary."""
    raw = dict(options or {})
    if "output_dir" in raw:
        if "output" in raw and raw["output"] != raw["output_dir"]:
            raise ValueError("delegated options cannot contain conflicting output and output_dir")
        raw["output"] = raw.pop("output_dir")
    unknown = set(raw) - _OPTION_KEYS
    if unknown:
        raise ValueError(f"unknown delegated option(s): {', '.join(sorted(unknown))}")

    result: DelegatedOptionsWithQueue = cast(DelegatedOptionsWithQueue, dict(_OPTION_DEFAULTS))
    result["include"] = list(result["include"])
    result["exclude"] = list(result["exclude"])
    for key, value in raw.items():
        if key == "filter_queue":
            if not isinstance(value, (list, tuple)):
                raise TypeError("delegated option 'filter_queue' must be a sequence of kind/pattern pairs")
            queue: list[tuple[str, str]] = []
            for item in value:
                if (
                    not isinstance(item, (list, tuple))
                    or len(item) != 2
                    or item[0] not in {"include", "exclude"}
                    or not isinstance(item[1], str)
                ):
                    raise TypeError(
                        "delegated option 'filter_queue' must contain include/exclude kind/pattern pairs"
                    )
                queue.append((item[0], item[1]))
            result["filter_queue"] = queue
        elif key in {"include", "exclude"}:
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
                raise TypeError(f"delegated option {key!r} must be a sequence of strings")
            result[key] = list(value)
        elif key in {"merge", "output"}:
            if value is not None and not isinstance(value, str):
                raise TypeError(f"delegated option {key!r} must be a string or None")
            result[key] = value
        elif not isinstance(value, bool):
            raise TypeError(f"delegated option {key!r} must be a boolean")
        else:
            result[key] = value
    return result


def _deserialize_request(data: Any) -> DelegatedRequest | None:
    if not isinstance(data, dict):
        return None
    files = data.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        return None
    try:
        options = _serialize_options(data.get("options"))
    except (TypeError, ValueError):
        return None
    return {"files": files, "options": options}


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
    retries: int = 50,
    retry_delay: float = 0.04,
) -> bool:
    """Hand files and behavior-affecting options to an already running coordinator.

    The ``output_dir`` input name remains accepted for current call sites; it is
    serialized as the canonical ``output`` field.
    """
    request: DelegatedRequest = {"files": list(files), "options": _serialize_options(options)}
    address = _get_address(pipe_name)
    
    for _ in range(retries):
        conn = None
        try:
            conn = Client(address, authkey=IPC_AUTH_KEY)
            conn.send(request)
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
        self._delegated_options: DelegatedOptions | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        # Acquire file lock to prevent race condition when multiple processes
        # try to become the coordinator simultaneously
        self._lock_file = open(IPC_LOCK_FILE, "w")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            return False
        
        try:
            self.listener = Listener(self.address, authkey=IPC_AUTH_KEY)
            self._running = True
            self._thread = threading.Thread(target=self._server_loop, daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._release_lock()
            return False

    def set_initial_options(self, options: Mapping[str, Any]) -> None:
        normalized = _serialize_options(options)
        if self._delegated_options is None:
            self._delegated_options = normalized
        elif self._delegated_options != normalized:
            raise ValueError("coordinator options conflict with the active request")

    def _server_loop(self) -> None:
        while self._running and self.listener:
            try:
                conn = self.listener.accept()
            except Exception:
                break
            try:
                data = conn.recv()
                request = _deserialize_request(data)
                if request is None:
                    continue
                new_files = request["files"]
                if new_files:
                    if self._delegated_options is not None and self._delegated_options != request["options"]:
                        conn.send({"status": "error", "reason": "coordinator options conflict with the active request"})
                        continue
                    self._delegated_options = request["options"]
                    self._incoming_queue.put(new_files)
                conn.send({"status": "ok"})
            except Exception:
                logger.debug("Failed to handle coordinator connection", exc_info=True)
            finally:
                _close_quietly(conn)

    @property
    def delegated_options(self) -> DelegatedOptionsWithQueue | None:
        """Options from the most recently accepted delegated request."""
        if self._delegated_options is None:
            return None
        result = {
            **self._delegated_options,
            "include": list(self._delegated_options["include"]),
            "exclude": list(self._delegated_options["exclude"]),
        }
        if "filter_queue" in self._delegated_options:
            result["filter_queue"] = list(self._delegated_options["filter_queue"])
        return cast(DelegatedOptionsWithQueue, result)

    def collect_files(self, initial_files: Sequence[str], assembly_timeout: float = 2.0) -> list[str]:
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
                deadline = time.monotonic() + assembly_timeout
            except queue.Empty:
                break

        return collected

    def _release_lock(self) -> None:
        if hasattr(self, "_lock_file") and self._lock_file:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

    def stop(self) -> None:
        self._running = False
        if self.listener:
            try:
                self.listener.close()
            except Exception:
                pass
            self.listener = None
        self._release_lock()
