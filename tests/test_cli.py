"""Tests for the CLI entrypoint."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import uvicorn

from coda_node.server import cli
from coda_node.server import config as config_module
from coda_node.server import daemon as daemon_module


def test_build_parser_supports_start_flags() -> None:
    args = cli._build_parser().parse_args(
        ["start", "--token", "test-token", "-p", "9000"]
    )

    assert args.command == "start"
    assert args.node_token == "test-token"
    assert args.port == 9000


def test_build_parser_supports_explicit_start_short_flags() -> None:
    args = cli._build_parser().parse_args(
        ["start", "-t", "test-token", "-H", "127.0.0.1"]
    )

    assert args.command == "start"
    assert args.node_token == "test-token"
    assert args.host == "127.0.0.1"


def test_build_parser_supports_top_level_reset_flag() -> None:
    args = cli._build_parser().parse_args(["--reset"])

    assert args.reset is True
    assert args.command is None


def test_main_runs_server_with_start_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "Settings", MagicMock(return_value=MagicMock(host="0.0.0.0", port=8080))
    )
    mock_run = MagicMock()
    fake_env: dict[str, str] = {}
    monkeypatch.setattr(os, "environ", fake_env)
    monkeypatch.setattr(uvicorn, "run", mock_run)
    monkeypatch.setattr("sys.argv", ["coda", "start", "--token", "token-value"])

    cli.main()
    output = capsys.readouterr().out

    assert fake_env["CODA_NODE_TOKEN"] == "token-value"
    assert "C O D A  ·  N O D E" in output
    assert "MODE" in output
    mock_run.assert_called_once_with(
        "coda_node.server.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="warning",
    )


def test_main_resets_persisted_runtime_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "coda.config"
    key_path = tmp_path / "coda-private-key"
    profile_path = tmp_path / "custom.ovpn"
    pid_path = tmp_path / "coda.pid"
    log_path = tmp_path / "coda.log"

    config_path.write_text(
        json.dumps(
            {
                "jwt_private_key_path": str(key_path),
                "node_vpn_profile_path": str(profile_path),
            }
        )
    )
    key_path.write_text("private-key")
    profile_path.write_text("client")
    pid_path.write_text("1234")
    log_path.write_text("log")

    monkeypatch.setattr(cli, "PERSISTED_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli, "PERSISTED_PRIVATE_KEY_PATH", key_path)
    monkeypatch.setattr(cli, "OPENVPN_PID_PATH", pid_path)
    monkeypatch.setattr(cli, "OPENVPN_LOG_PATH", log_path)
    monkeypatch.setattr(cli, "kill_openvpn_daemon", MagicMock(return_value=True))
    monkeypatch.setattr("sys.argv", ["coda", "--reset"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "Resetting persisted Coda runtime state..." in output
    assert not config_path.exists()
    assert not key_path.exists()
    assert not profile_path.exists()
    assert not pid_path.exists()
    assert not log_path.exists()


def test_doctor_loads_persisted_runtime_without_recursing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "coda.config"
    key_path = tmp_path / "coda-private-key"
    key_path.write_text(
        "-----BEGIN PRIVATE KEY-----\npersisted\n-----END PRIVATE KEY-----\n"
    )
    config_path.write_text(
        json.dumps(
            {
                "jwt_private_key_path": str(key_path),
                "jwt_key_id": "persisted-key-id",
                "webapp_url": "https://persisted.example.test",
                "connect_path": "/api/internal/qpu/connect",
                "redis_url": "rediss://default:token@persisted:6379",
            }
        )
    )
    if os.name != "nt":
        key_path.chmod(0o600)
        config_path.chmod(0o600)

    monkeypatch.setattr(config_module, "PERSISTED_CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "PERSISTED_PRIVATE_KEY_PATH", key_path)
    monkeypatch.setenv("CODA_JWT_PRIVATE_KEY", "")
    monkeypatch.setenv("CODA_JWT_KEY_ID", "")
    monkeypatch.delenv("CODA_NODE_TOKEN", raising=False)
    monkeypatch.delenv("CODA_WEBAPP_URL", raising=False)
    monkeypatch.delenv("CODA_REDIS_URL", raising=False)
    monkeypatch.setattr(shutil, "which", MagicMock(return_value=None))
    monkeypatch.setattr(cli, "detect_tun_interface", MagicMock(return_value=None))

    assert cli._doctor() == 0

    output = capsys.readouterr().out
    assert "C O D A  ·  D O C T O R" in output
    assert "https://persisted.example.test" in output
    assert "/api/internal/qpu/connect" in output


def test_build_parser_supports_daemon_flag() -> None:
    args = cli._build_parser().parse_args(["start", "--daemon"])

    assert args.command == "start"
    assert args.daemon is True


def test_build_parser_supports_daemon_short_flag() -> None:
    args = cli._build_parser().parse_args(["start", "-d", "-p", "9000"])

    assert args.command == "start"
    assert args.daemon is True
    assert args.port == 9000


def test_build_parser_supports_stop_command() -> None:
    args = cli._build_parser().parse_args(["stop"])
    assert args.command == "stop"


def test_build_parser_supports_status_command() -> None:
    args = cli._build_parser().parse_args(["status"])
    assert args.command == "status"


def test_build_parser_supports_logs_command() -> None:
    args = cli._build_parser().parse_args(["logs", "-n", "100"])
    assert args.command == "logs"
    assert args.lines == 100


def test_start_daemon_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pid_path = tmp_path / "coda.pid"
    log_path = tmp_path / "coda.log"

    monkeypatch.setattr(daemon_module, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(daemon_module, "DAEMON_LOG_PATH", log_path)
    monkeypatch.setattr(cli, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(cli, "DAEMON_LOG_PATH", log_path)
    mock_start_daemon = MagicMock(return_value=12345)
    monkeypatch.setattr(
        cli,
        "Settings",
        MagicMock(
            return_value=MagicMock(
                host="127.0.0.1",
                port=9000,
                node_token="test-token",
                webapp_url="https://test.example.com",
            )
        ),
    )
    monkeypatch.setattr(cli, "is_daemon_running", MagicMock(return_value=False))
    monkeypatch.setattr(cli, "start_daemon", mock_start_daemon)
    monkeypatch.setattr("sys.argv", ["coda", "start", "--daemon"])

    cli.main()

    output = capsys.readouterr().out
    assert "C O D A  ·  D A E M O N" in output
    assert "Started daemon (PID 12345)" in output
    mock_start_daemon.assert_called_once_with(
        host="127.0.0.1",
        port=9000,
        token="test-token",
    )


def test_stop_command_when_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "is_daemon_running", MagicMock(return_value=True))
    monkeypatch.setattr(cli, "daemon_status", MagicMock(return_value={"pid": 12345}))
    monkeypatch.setattr(cli, "stop_daemon", MagicMock(return_value=True))
    monkeypatch.setattr("sys.argv", ["coda", "stop"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Stopping daemon (PID 12345)" in output
    assert "Daemon stopped" in output


def test_stop_command_when_not_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "is_daemon_running", MagicMock(return_value=False))
    monkeypatch.setattr("sys.argv", ["coda", "stop"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "No daemon is running" in output


def test_status_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pid_path = tmp_path / "coda.pid"
    monkeypatch.setattr(cli, "DAEMON_PID_PATH", pid_path)
    monkeypatch.setattr(
        cli,
        "daemon_status",
        MagicMock(
            return_value={
                "running": True,
                "pid": 12345,
                "log_exists": True,
            }
        ),
    )
    monkeypatch.setattr(
        cli,
        "Settings",
        MagicMock(
            return_value=MagicMock(
                vpn_interface_hint=None,
            )
        ),
    )
    monkeypatch.setattr(cli, "detect_tun_interface", MagicMock(return_value="utun5"))
    monkeypatch.setattr("sys.argv", ["coda", "status"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "C O D A  ·  S T A T U S" in output
    assert "running" in output
    assert "12345" in output


def test_logs_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "tail_daemon_log", MagicMock(return_value="log line 1\nlog line 2")
    )
    monkeypatch.setattr("sys.argv", ["coda", "logs"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "log line 1" in output
    assert "log line 2" in output


def test_reset_stops_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "coda.config"
    key_path = tmp_path / "coda-private-key"
    daemon_pid_path = tmp_path / "coda-daemon.pid"
    daemon_log_path = tmp_path / "coda-daemon.log"

    config_path.write_text("{}")
    key_path.write_text("key")
    daemon_pid_path.write_text("1234")
    daemon_log_path.write_text("log")

    monkeypatch.setattr(cli, "PERSISTED_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli, "PERSISTED_PRIVATE_KEY_PATH", key_path)
    monkeypatch.setattr(cli, "DAEMON_PID_PATH", daemon_pid_path)
    monkeypatch.setattr(cli, "DAEMON_LOG_PATH", daemon_log_path)
    monkeypatch.setattr(cli, "OPENVPN_PID_PATH", tmp_path / "openvpn.pid")
    monkeypatch.setattr(cli, "OPENVPN_LOG_PATH", tmp_path / "openvpn.log")
    mock_stop_daemon = MagicMock(return_value=True)
    monkeypatch.setattr(cli, "stop_daemon", mock_stop_daemon)
    monkeypatch.setattr(cli, "kill_openvpn_daemon", MagicMock(return_value=False))
    monkeypatch.setattr("sys.argv", ["coda", "reset"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Stopped Coda daemon" in output
    mock_stop_daemon.assert_called_once()
