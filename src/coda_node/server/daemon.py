"""Daemon management for the Coda node server.

Provides functionality to run the server as a background daemon process
with PID file tracking, log file redirection, and signal-based shutdown.

The daemon process spawns uvicorn in the background, writes its PID to
``/tmp/coda-node.pid``, and redirects output to
``/tmp/coda-node.log``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

__all__ = [
    "DAEMON_LOG_PATH",
    "DAEMON_PID_PATH",
    "daemon_status",
    "is_daemon_running",
    "read_daemon_pid",
    "start_daemon",
    "stop_daemon",
]

_RUNTIME_DIR = Path(tempfile.gettempdir())
DAEMON_PID_PATH = _RUNTIME_DIR / "coda-node.pid"
DAEMON_LOG_PATH = _RUNTIME_DIR / "coda-node.log"


def read_daemon_pid() -> int | None:
    """Read the daemon PID from the PID file.

    Returns:
        The PID as an integer, or ``None`` if the file does not exist
        or contains invalid content.
    """
    if not DAEMON_PID_PATH.exists():
        return None
    try:
        return int(DAEMON_PID_PATH.read_text().strip())
    except (ValueError, OSError):
        return None


def _process_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        # OSError covers Windows-specific errors like WinError 87
        return False


def is_daemon_running() -> bool:
    """Check if the daemon process is currently running.

    Returns:
        ``True`` if the PID file exists and the process is alive,
        ``False`` otherwise.
    """
    pid = read_daemon_pid()
    if pid is None:
        return False
    return _process_exists(pid)


def daemon_status() -> dict[str, object]:
    """Get detailed status information about the daemon.

    Returns:
        A dictionary containing:
        - ``running``: Whether the daemon is running.
        - ``pid``: The daemon PID (or ``None``).
        - ``pid_file``: Path to the PID file.
        - ``log_file``: Path to the log file.
        - ``log_exists``: Whether the log file exists.
    """
    pid = read_daemon_pid()
    running = pid is not None and _process_exists(pid)
    return {
        "running": running,
        "pid": pid if running else None,
        "pid_file": str(DAEMON_PID_PATH),
        "log_file": str(DAEMON_LOG_PATH),
        "log_exists": DAEMON_LOG_PATH.exists(),
    }


def start_daemon(
    host: str = "0.0.0.0",
    port: int = 8080,
    token: str | None = None,
) -> int:
    """Start the server as a background daemon process.

    Spawns a new Python process running uvicorn with the FastAPI app,
    detached from the current terminal. The process PID is written to
    :data:`DAEMON_PID_PATH` and output is redirected to
    :data:`DAEMON_LOG_PATH`.

    Args:
        host: Bind address for the server.
        port: Bind port for the server.
        token: Optional node token for first-run provisioning.

    Returns:
        The PID of the spawned daemon process.

    Raises:
        RuntimeError: If the daemon is already running.
    """
    if is_daemon_running():
        pid = read_daemon_pid()
        raise RuntimeError(f"Daemon already running (PID {pid})")

    # Clean up stale PID file if process is gone
    if DAEMON_PID_PATH.exists():
        DAEMON_PID_PATH.unlink()

    # Build environment with optional token
    env = os.environ.copy()
    env["CODA_HOST"] = host
    env["CODA_PORT"] = str(port)
    if token:
        env["CODA_NODE_TOKEN"] = token

    # Build the command to run uvicorn directly
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "coda_node.server.app:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]

    # Open log file for output redirection
    log_handle = DAEMON_LOG_PATH.open("a", encoding="utf-8")

    try:
        if os.name == "nt":
            # Windows: use creation flags to detach
            creationflags = 0
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
        else:
            # POSIX: use start_new_session to detach from terminal
            process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
    finally:
        log_handle.close()

    # Write PID file
    DAEMON_PID_PATH.write_text(f"{process.pid}\n")
    if os.name != "nt":
        DAEMON_PID_PATH.chmod(0o644)

    return process.pid


def stop_daemon(timeout: float = 10.0) -> bool:
    """Stop the running daemon process.

    Sends ``SIGTERM`` (or uses ``taskkill`` on Windows) to the daemon
    and waits for it to exit. If the process does not exit within
    *timeout* seconds, sends ``SIGKILL``.

    Args:
        timeout: Seconds to wait for graceful shutdown before force-killing.

    Returns:
        ``True`` if a daemon was found and stopped, ``False`` if no
        daemon was running.
    """
    pid = read_daemon_pid()
    if pid is None:
        return False

    if not _process_exists(pid):
        # Stale PID file, clean up
        DAEMON_PID_PATH.unlink(missing_ok=True)
        return False

    try:
        if os.name == "nt":
            # Windows: use taskkill
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        else:
            # POSIX: send SIGTERM first
            os.kill(pid, signal.SIGTERM)

            # Wait for process to exit
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not _process_exists(pid):
                    break
                time.sleep(0.1)
            else:
                # Process didn't exit, force kill
                # Use getattr for SIGKILL since it doesn't exist on Windows
                sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
                os.kill(pid, sigkill)
                time.sleep(0.5)

        DAEMON_PID_PATH.unlink(missing_ok=True)
        return True

    except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
        DAEMON_PID_PATH.unlink(missing_ok=True)
        return False


def tail_daemon_log(lines: int = 50) -> str:
    """Return the last *lines* of the daemon log file.

    Args:
        lines: Maximum number of lines to return.

    Returns:
        The log tail as a string, or an empty string if the log
        file does not exist.
    """
    if not DAEMON_LOG_PATH.exists():
        return ""
    try:
        all_lines = DAEMON_LOG_PATH.read_text().splitlines()
        return "\n".join(all_lines[-lines:])
    except OSError:
        return ""
