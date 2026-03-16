"""Tests for the daemon module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from self_service.server import daemon


def test_read_daemon_pid_returns_none_when_no_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "nonexistent.pid"
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.read_daemon_pid() is None


def test_read_daemon_pid_returns_pid_from_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("12345\n")
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.read_daemon_pid() == 12345


def test_read_daemon_pid_returns_none_on_invalid_content(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("not-a-pid\n")
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.read_daemon_pid() is None


def test_is_daemon_running_false_when_no_pid_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "nonexistent.pid"
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.is_daemon_running() is False


def test_is_daemon_running_false_when_process_dead(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("99999999\n")  # Unlikely to be a real process
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.is_daemon_running() is False


def test_daemon_status_returns_status_dict(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    log_path = tmp_path / "test.log"
    log_path.write_text("some log content")

    with (
        patch.object(daemon, "DAEMON_PID_PATH", pid_path),
        patch.object(daemon, "DAEMON_LOG_PATH", log_path),
    ):
        status = daemon.daemon_status()

    assert status["running"] is False
    assert status["pid"] is None
    assert status["pid_file"] == str(pid_path)
    assert status["log_file"] == str(log_path)
    assert status["log_exists"] is True


def test_daemon_status_running_when_process_alive(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    log_path = tmp_path / "test.log"
    pid_path.write_text(f"{os.getpid()}\n")  # Current process is definitely running

    with (
        patch.object(daemon, "DAEMON_PID_PATH", pid_path),
        patch.object(daemon, "DAEMON_LOG_PATH", log_path),
    ):
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
    pid_path.write_text("99999999\n")  # Dead process

    monkeypatch.setattr(daemon, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_PATH", log_path)

    mock_popen = MagicMock()
    mock_popen.pid = 54321

    with patch("subprocess.Popen", return_value=mock_popen):
        pid = daemon.start_daemon()

    assert pid == 54321
    assert pid_path.read_text().strip() == "54321"


def test_stop_daemon_returns_false_when_no_pid_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "nonexistent.pid"
    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        assert daemon.stop_daemon() is False


def test_stop_daemon_cleans_up_stale_pid_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("99999999\n")  # Dead process

    with patch.object(daemon, "DAEMON_PID_PATH", pid_path):
        result = daemon.stop_daemon()

    assert result is False
    assert not pid_path.exists()


def test_tail_daemon_log_returns_empty_when_no_file(tmp_path: Path) -> None:
    log_path = tmp_path / "nonexistent.log"
    with patch.object(daemon, "DAEMON_LOG_PATH", log_path):
        assert daemon.tail_daemon_log() == ""


def test_tail_daemon_log_returns_last_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "test.log"
    lines = [f"line {i}" for i in range(100)]
    log_path.write_text("\n".join(lines))

    with patch.object(daemon, "DAEMON_LOG_PATH", log_path):
        result = daemon.tail_daemon_log(lines=10)

    assert result == "\n".join(lines[-10:])
