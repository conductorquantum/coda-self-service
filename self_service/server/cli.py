"""Small CLI for serving and inspecting the node runtime."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path

import uvicorn

from self_service.server.config import Settings
from self_service.vpn import (
    OPENVPN_PID_PATH,
    _detect_tun_interface,
    kill_openvpn_daemon,
)

_BANNER_WIDTH = 48


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    start_parent = argparse.ArgumentParser(add_help=False)
    start_parent.add_argument("-H", "--host")
    start_parent.add_argument("-p", "--port", type=int)
    start_parent.add_argument("-t", "--token", dest="self_service_token")

    parser = argparse.ArgumentParser(prog="coda")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "start", parents=[start_parent], help="Run the FastAPI server"
    )

    subparsers.add_parser("doctor", help="Print basic runtime checks")
    subparsers.add_parser("stop-vpn", help="Stop the managed OpenVPN process")
    return parser


def _apply_overrides(args: argparse.Namespace) -> None:
    host = getattr(args, "host", None)
    port = getattr(args, "port", None)
    self_service_token = getattr(args, "self_service_token", None)

    if host:
        os.environ["CODA_HOST"] = host
    if port is not None:
        os.environ["CODA_PORT"] = str(port)
    if self_service_token:
        os.environ["CODA_SELF_SERVICE_TOKEN"] = self_service_token


def _print_banner(title: str, rows: list[tuple[str, str]]) -> None:
    print()
    print(f"  ┌{'─' * (_BANNER_WIDTH - 2)}┐")
    print(f"  │{title:^{_BANNER_WIDTH - 2}}│")
    print(f"  └{'─' * (_BANNER_WIDTH - 2)}┘")
    print()
    for label, value in rows:
        print(f"  {label:<14}{value}")
    print()
    print(f"  {'─' * _BANNER_WIDTH}")
    print()


def _print_status(label: str, value: str) -> None:
    print(f"  {'→':<2} {label:<14}{value}")


def _start_mode(token: str) -> str:
    return "token" if token else "env"


def _doctor() -> int:
    settings = Settings()
    openvpn_bin = shutil.which("openvpn") or shutil.which("openvpn.exe")
    iface = _detect_tun_interface(settings.vpn_interface_hint)
    pid_exists = Path(OPENVPN_PID_PATH).exists()

    _print_banner(
        "C O D A  ·  D O C T O R",
        [
            ("WEBAPP", settings.webapp_url),
            ("REGISTER", settings.register_url),
            ("REDIS", settings.redis_url or "not set"),
        ],
    )
    _print_status("EXECUTOR", settings.executor_factory or "NoopExecutor")
    _print_status("OPENVPN", openvpn_bin or "not found")
    _print_status("VPN IFACE", iface or "not detected")
    _print_status("VPN PID", "present" if pid_exists else "absent")
    return 0


def main() -> None:
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "start":
        _apply_overrides(args)
        settings = Settings()
        _print_banner(
            "C O D A  ·  N O D E",
            [
                ("WEBAPP", settings.webapp_url),
                ("ENDPOINT", f"{settings.host}:{settings.port}"),
                ("MODE", _start_mode(settings.self_service_token)),
            ],
        )
        uvicorn.run(
            "self_service.server.app:app",
            host=settings.host,
            port=settings.port,
            reload=False,
            log_level="warning",
        )
        return

    if args.command == "doctor":
        raise SystemExit(_doctor())

    if args.command == "stop-vpn":
        killed = kill_openvpn_daemon()
        print("Stopping Coda VPN service...")
        print(
            "  ✓ Stopped managed OpenVPN daemon"
            if killed
            else "  No managed VPN process found"
        )
        raise SystemExit(0 if killed else 1)
