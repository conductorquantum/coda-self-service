"""Tests for the daemon module."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from coda_node.server import daemon

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Daemon tests hang on Windows CI"
)


def test_read_daemon_pid_returns_none_when_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", tmp_path / "nonexistent.pid")
    assert daemon.read_daemon_pid() is None


def test_read_daemon_pid_returns_pid_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("12345\n")
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    assert daemon.read_daemon_pid() == 12345


def test_read_daemon_pid_returns_none_on_invalid_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("not-a-pid\n")
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    assert daemon.read_daemon_pid() is None


def test_is_daemon_running_false_when_no_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", tmp_path / "nonexistent.pid")
    assert daemon.is_daemon_running() is False


def test_is_daemon_running_false_when_process_dead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("99999999\n")
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    assert daemon.is_daemon_running() is False


def test_daemon_status_returns_status_dict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    log_path = tmp_path / "test.log"
    log_path.write_text("some log content")

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", log_path)

    status = daemon.daemon_status()

    assert status["running"] is False
    assert status["pid"] is None
    assert status["pid_file"] == str(pid_path)
    assert status["log_file"] == str(log_path)
    assert status["log_exists"] is True


def test_daemon_status_running_when_process_alive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    log_path = tmp_path / "test.log"
    pid_path.write_text(f"{os.getpid()}\n")

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", log_path)

    status = daemon.daemon_status()

    assert status["running"] is True
    assert status["pid"] == os.getpid()


def test_start_daemon_raises_when_already_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text(f"{os.getpid()}\n")

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", tmp_path / "test.log")

    with pytest.raises(RuntimeError, match="already running"):
        daemon.start_daemon()


def test_start_daemon_cleans_stale_pid_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "test.pid"
    log_path = tmp_path / "test.log"
    pid_path.write_text("99999999\n")

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", log_path)

    mock_popen = MagicMock()
    mock_popen.pid = 54321
    monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=mock_popen))

    pid = daemon.start_daemon()

    assert pid == 54321
    assert pid_path.read_text().strip() == "54321"


def test_stop_daemon_returns_false_when_no_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", tmp_path / "nonexistent.pid")
    assert daemon.stop_daemon() is False


def test_stop_daemon_cleans_up_stale_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("99999999\n")

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)

    result = daemon.stop_daemon()

    assert result is False
    assert not pid_path.exists()


def test_tail_daemon_log_returns_empty_when_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", tmp_path / "nonexistent.log")
    assert daemon.tail_daemon_log() == ""


def test_tail_daemon_log_returns_last_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "test.log"
    lines = [f"line {i}" for i in range(100)]
    log_path.write_text("\n".join(lines))

    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", log_path)

    result = daemon.tail_daemon_log(lines=10)

    assert result == "\n".join(lines[-10:])
