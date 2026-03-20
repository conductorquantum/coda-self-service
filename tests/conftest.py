"""Shared test fixtures."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

config_module = importlib.import_module("self_service.server.config")
daemon_module = importlib.import_module("self_service.server.daemon")


@pytest.fixture(autouse=True)
def _isolate_persisted_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent tests from reading or writing real persisted state."""
    monkeypatch.setattr(
        config_module, "PERSISTED_CONFIG_PATH", tmp_path / "coda.config"
    )
    monkeypatch.setattr(
        config_module, "PERSISTED_PRIVATE_KEY_PATH", tmp_path / "coda-private-key"
    )


def _force_kill_pid(pid: int) -> None:
    """Forcefully kill a process by PID."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.kill(pid, 9)  # SIGKILL
    except (ProcessLookupError, PermissionError, OSError):
        pass


@pytest.fixture(autouse=True)
def _cleanup_daemon_processes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Forcefully stop any daemon processes after each test."""
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "daemon.log"

    monkeypatch.setattr(daemon_module, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon_module, "DAEMON_LOG_PATH", log_path)

    yield

    # Cleanup: forcefully kill any daemon that was started
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            _force_kill_pid(pid)
        except (ValueError, OSError):
            pass
        finally:
            pid_path.unlink(missing_ok=True)
