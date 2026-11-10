from __future__ import annotations

import contextlib
import logging
import os
import queue
import secrets
import tempfile
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict, cast


logger = logging.getLogger("hammerdown")

IPC_PIPE_NAME = r"\\.\pipe\hammerdown_coordinator"
IPC_PORT = 58432
IPC_LOCK_FILE = Path(tempfile.gettempdir()) / "hammerdown_coordinator.lock"
IPC_SESSION_FILE = Path.home() / ".hammerdown" / "coordinator.session"
IPC_REQUEST_READ_TIMEOUT = 1.0
_SESSION_SECRET_SIZE = 32


class DelegatedOptions(TypedDict):
    tree: bool
    all_formats: bool
    merge: str | None
    merge_auto: bool
    include: list[str]
    exclude: list[str]
    overwrite: bool
    skip_existing: bool
    yes: bool
    no: bool
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
    "yes": False,
    "no": False,
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


def _read_session_secret() -> bytes | None:
    try:
        secret = IPC_SESSION_FILE.read_bytes()
    except OSError:
        return None
    if len(secret) != _SESSION_SECRET_SIZE:
        return None
    return secret


def _write_session_secret(secret: bytes) -> None:
    directory = IPC_SESSION_FILE.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    fd, temporary_name = tempfile.mkstemp(prefix=f".{IPC_SESSION_FILE.name}.", dir=directory)
    try:
        with os.fdopen(fd, "wb") as session:
            session.write(secret)
            session.flush()
            os.fsync(session.fileno())
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            pass
        os.replace(temporary_name, IPC_SESSION_FILE)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _remove_session_secret(secret: bytes | None) -> None:
    if secret is None or _read_session_secret() != secret:
        return
    try:
        IPC_SESSION_FILE.unlink()
    except OSError:
        pass


def _get_auth_key() -> bytes | None:
    return _read_session_secret()


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
            authkey = _get_auth_key()
            if authkey is None:
                time.sleep(retry_delay)
                continue
            conn = Client(address, authkey=authkey)
            conn.send(request)
            response = conn.recv()
            if isinstance(response, dict):
                if response.get("status") == "ok":
                    return True
                if response.get("reason") in {
                    "coordinator is busy",
                    "coordinator options conflict with the active request",
                }:
                    return False
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
        self._delivery_condition = threading.Condition()
        self._inflight_connections = 0
        self._delivery_generation = 0
        self._lifecycle_generation = 0
        self._active_connections: set[Any] = set()
        self._delegated_options: DelegatedOptions | None = None
        self._assembly_open = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._authkey: bytes | None = None

    def start(self) -> bool:
        with self._delivery_condition:
            if self._running and self.listener is not None and self._thread is not None and self._thread.is_alive():
                return False
            self._reset_delivery_state_locked()

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
            self._authkey = secrets.token_bytes(_SESSION_SECRET_SIZE)
            _write_session_secret(self._authkey)
            self.listener = Listener(self.address, authkey=self._authkey)
            self._running = True
            with self._delivery_condition:
                self._assembly_open = True
            self._thread = threading.Thread(target=self._server_loop, daemon=True)
            self._thread.start()
            return True
        except Exception:
            if self.listener is not None:
                try:
                    self.listener.close()
                except Exception:
                    pass
                self.listener = None
            _remove_session_secret(self._authkey)
            self._authkey = None
            self._release_lock()
            return False

    def close_assembly(self) -> None:
        """Stop accepting delegated files; the owner is converting on its own.

        Delegated launches then receive a busy rejection and convert locally
        instead of having their files silently dropped at shutdown.
        """
        with self._delivery_condition:
            self._assembly_open = False

    def set_initial_options(self, options: Mapping[str, Any]) -> None:
        normalized = _serialize_options(options)
        if self._delegated_options is None:
            self._delegated_options = normalized
        elif self._delegated_options != normalized:
            raise ValueError("coordinator options conflict with the active request")

    def _reset_delivery_state_locked(self) -> None:
        self._incoming_queue = queue.Queue()
        self._lifecycle_generation += 1
        self._delegated_options = None
        self._assembly_open = False

    def _fail_from_server_thread(self) -> None:
        with self._delivery_condition:
            self._running = False
            self._reset_delivery_state_locked()
            listener = self.listener
            self.listener = None
            active_connections = list(self._active_connections)
            self._active_connections.clear()
            self._inflight_connections = 0
            self._delivery_condition.notify_all()

        _close_quietly(listener)
        for conn in active_connections:
            _close_quietly(conn)
        _remove_session_secret(self._authkey)
        self._authkey = None
        self._release_lock()

    def _server_loop(self) -> None:
        while self._running and self.listener:
            try:
                conn = self.listener.accept()
            except AuthenticationError:
                if self._running:
                    logger.debug("Rejected unauthenticated coordinator connection", exc_info=True)
                    continue
                break
            except Exception:
                if not self._running:
                    break
                logger.debug("Failed to accept coordinator connection", exc_info=True)
                self._fail_from_server_thread()
                break
            with self._delivery_condition:
                if not self._running:
                    _close_quietly(conn)
                    break
                self._active_connections.add(conn)
                self._inflight_connections += 1
            try:
                request_deadline = time.monotonic() + IPC_REQUEST_READ_TIMEOUT
                data: Any = None
                read_result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

                def read_request() -> None:
                    try:
                        read_result.put((True, conn.recv()))
                    except Exception as error:
                        read_result.put((False, error))

                # Connection.recv() can block after poll() reports a partial
                # multiprocessing frame. Keep that operation off the server
                # thread so the deadline remains enforceable on every transport.
                reader = threading.Thread(target=read_request, daemon=True)
                reader.start()
                while True:
                    with self._delivery_condition:
                        if not self._running:
                            return
                    remaining = request_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        received, value = read_result.get(timeout=min(0.05, remaining))
                    except queue.Empty:
                        continue
                    if received:
                        data = value
                    break
                if data is None:
                    _close_quietly(conn)
                    continue
                request = _deserialize_request(data)
                if request is None:
                    continue
                new_files = request["files"]
                if new_files:
                    with self._delivery_condition:
                        assembly_open = self._assembly_open
                    if not assembly_open:
                        conn.send({"status": "error", "reason": "coordinator is busy"})
                        continue
                    if self._delegated_options is not None and self._delegated_options != request["options"]:
                        conn.send({"status": "error", "reason": "coordinator options conflict with the active request"})
                        continue
                    self._delegated_options = request["options"]
                    with self._delivery_condition:
                        self._incoming_queue.put(new_files)
                        self._delivery_generation += 1
                        self._delivery_condition.notify_all()
                conn.send({"status": "ok"})
            except Exception:
                logger.debug("Failed to handle coordinator connection", exc_info=True)
            finally:
                with self._delivery_condition:
                    self._active_connections.discard(conn)
                    self._inflight_connections -= 1
                    self._delivery_condition.notify_all()
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
        if assembly_timeout <= 0:
            raise ValueError("assembly_timeout must be positive")
        collected: list[str] = list(initial_files)
        seen = set(collected)
        deadline = time.monotonic() + assembly_timeout
        with self._delivery_condition:
            delivery_generation = self._delivery_generation
            lifecycle_generation = self._lifecycle_generation

        while True:
            with self._delivery_condition:
                if self._lifecycle_generation != lifecycle_generation:
                    return collected
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._delivery_condition:
                    while self._inflight_connections:
                        self._delivery_condition.wait()
                    if self._lifecycle_generation != lifecycle_generation:
                        return collected
                    if self._delivery_generation != delivery_generation:
                        delivery_generation = self._delivery_generation
                        deadline = time.monotonic() + assembly_timeout
                        continue
                break
            try:
                batch = self._incoming_queue.get(timeout=remaining)
                with self._delivery_condition:
                    if self._lifecycle_generation != lifecycle_generation:
                        return collected
                    for item in batch:
                        if item not in seen:
                            seen.add(item)
                            collected.append(item)
                    delivery_generation = self._delivery_generation
                deadline = time.monotonic() + assembly_timeout
            except queue.Empty:
                with self._delivery_condition:
                    while self._inflight_connections:
                        self._delivery_condition.wait()
                    if self._lifecycle_generation != lifecycle_generation:
                        return collected
                    if self._delivery_generation != delivery_generation:
                        delivery_generation = self._delivery_generation
                        deadline = time.monotonic() + assembly_timeout
                        continue
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

    def _wake_listener(self) -> None:
        conn = None
        try:
            authkey = self._authkey
            if authkey is not None:
                conn = Client(self.address, authkey=authkey)
        except Exception:
            pass
        finally:
            _close_quietly(conn)

    def stop(self) -> None:
        with self._delivery_condition:
            self._running = False
            self._reset_delivery_state_locked()
            active_connections = list(self._active_connections)
            for conn in active_connections:
                _close_quietly(conn)
        listener = self.listener
        thread = self._thread

        # A local connection wakes accept() consistently on sockets and named
        # pipes. The challenge handshake can stall when the server thread is
        # already shutting down, so the waker runs bounded and the listener
        # close below aborts both the pending accept and a half-open challenge.
        if listener is not None and thread is not threading.current_thread() and thread is not None:
            with self._delivery_condition:
                has_active_connections = bool(self._active_connections)
            if not has_active_connections:
                waker = threading.Thread(target=self._wake_listener, daemon=True)
                waker.start()
                waker.join(timeout=2.0)

        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass
            self.listener = None

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("coordinator server thread did not stop cleanly")

        _remove_session_secret(self._authkey)
        self._authkey = None
        self._release_lock()
