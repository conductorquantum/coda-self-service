"""Tests for the CLI entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from self_service.server import cli


def test_build_parser_supports_start_flags() -> None:
    args = cli._build_parser().parse_args(
        ["start", "--token", "test-token", "-p", "9000"]
    )

    assert args.command == "start"
    assert args.self_service_token == "test-token"
    assert args.port == 9000


def test_build_parser_supports_explicit_start_short_flags() -> None:
    args = cli._build_parser().parse_args(
        ["start", "-t", "test-token", "-H", "127.0.0.1"]
    )

    assert args.command == "start"
    assert args.self_service_token == "test-token"
    assert args.host == "127.0.0.1"


def test_main_runs_server_with_start_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "Settings", MagicMock(return_value=MagicMock(host="0.0.0.0", port=8080))
    )
    mock_run = MagicMock()
    fake_env: dict[str, str] = {}
    monkeypatch.setattr(cli.os, "environ", fake_env)
    monkeypatch.setattr(cli.uvicorn, "run", mock_run)
    monkeypatch.setattr("sys.argv", ["coda", "start", "--token", "token-value"])

    cli.main()
    output = capsys.readouterr().out

    assert fake_env["CODA_SELF_SERVICE_TOKEN"] == "token-value"
    assert "C O D A  ·  N O D E" in output
    assert "MODE" in output
    mock_run.assert_called_once_with(
        "self_service.server.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="warning",
    )
