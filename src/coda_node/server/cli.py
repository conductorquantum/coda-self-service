"""Command-line interface for the Coda node runtime.

Provides the ``coda`` (and ``coda-node``) entry points with
subcommands:

* ``start`` -- launch the FastAPI server with optional ``--token`` for
  first-time node provisioning. Use ``--daemon`` to run in the
  background.
* ``stop`` -- stop the daemon if running in background mode.
* ``status`` -- show daemon status and basic runtime info.
* ``doctor`` -- print diagnostic information about the local
  environment (OpenVPN, VPN interface, Redis, executor).
* ``reset`` -- wipe persisted credentials, VPN profiles, and stop any
  managed OpenVPN daemon.
* ``stop-vpn`` -- stop the managed OpenVPN process without resetting
  other state.
* ``logs`` -- show recent daemon log output.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import uvicorn

from coda_node.server.config import (
    PERSISTED_CONFIG_PATH,
    PERSISTED_PRIVATE_KEY_PATH,
    Settings,
)
from coda_node.server.daemon import (
    DAEMON_LOG_PATH,
    DAEMON_PID_PATH,
    daemon_status,
    is_daemon_running,
    start_daemon,
    stop_daemon,
    tail_daemon_log,
)
from coda_node.vpn import (
    OPENVPN_LOG_PATH,
    OPENVPN_PID_PATH,
    detect_tun_interface,
    kill_openvpn_daemon,
)

__all__ = ["main"]

_BANNER_WIDTH = 48


def _configure_logging() -> None:
    """Set up root logger with a human-readable format at INFO level."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``coda`` CLI argument parser with all subcommands."""
    start_parent = argparse.ArgumentParser(add_help=False)
    start_parent.add_argument("-H", "--host")
    start_parent.add_argument("-p", "--port", type=int)
    start_parent.add_argument("-t", "--token", dest="node_token")
    start_parent.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run the server as a background daemon",
    )

    parser = argparse.ArgumentParser(prog="coda")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear persisted runtime state and VPN artifacts",
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser(
        "start", parents=[start_parent], help="Run the FastAPI server"
    )
    subparsers.add_parser("stop", help="Stop the background daemon")
    subparsers.add_parser("status", help="Show daemon status")
    subparsers.add_parser("doctor", help="Print basic runtime checks")
    subparsers.add_parser(
        "reset", help="Clear persisted runtime state and VPN artifacts"
    )
    subparsers.add_parser("stop-vpn", help="Stop the managed OpenVPN process")

    logs_parser = subparsers.add_parser("logs", help="Show recent daemon log output")
    logs_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Number of lines to show (default: 50)",
    )

    return parser


def _apply_overrides(args: argparse.Namespace) -> None:
    """Push CLI flags into environment variables before Settings loads."""
    host = getattr(args, "host", None)
    port = getattr(args, "port", None)
    node_token = getattr(args, "node_token", None)

    if host:
        os.environ["CODA_HOST"] = host
    if port is not None:
        os.environ["CODA_PORT"] = str(port)
    if node_token:
        os.environ["CODA_NODE_TOKEN"] = node_token


def _print_banner(title: str, rows: list[tuple[str, str]]) -> None:
    """Print a bordered banner with a title and key-value rows."""
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
    """Print a single diagnostic status row."""
    print(f"  {'→':<2} {label:<14}{value}")


def _start_mode(token: str) -> str:
    """Return the display name for the startup mode."""
    return "token" if token else "env"


def _read_reset_paths() -> list[Path]:
    """Collect all file paths that should be removed during a reset."""
    paths = {
        PERSISTED_CONFIG_PATH,
        PERSISTED_PRIVATE_KEY_PATH,
        OPENVPN_PID_PATH,
        OPENVPN_LOG_PATH,
        DAEMON_PID_PATH,
        DAEMON_LOG_PATH,
        Path(f"{tempfile.gettempdir()}/coda-node.ovpn"),
    }
    if PERSISTED_CONFIG_PATH.exists():
        try:
            data = json.loads(PERSISTED_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key in ("jwt_private_key_path", "node_vpn_profile_path"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    paths.add(Path(value))
    return sorted(paths)


def _reset() -> int:
    """Stop the daemon and VPN, and remove all persisted runtime files."""
    print("Resetting persisted Coda runtime state...")

    # Stop the daemon if running
    daemon_stopped = stop_daemon()
    print("  Stopped Coda daemon" if daemon_stopped else "  No Coda daemon running")

    # Stop OpenVPN
    vpn_killed = kill_openvpn_daemon()
    print(
        "  Stopped managed OpenVPN daemon"
        if vpn_killed
        else "  No managed VPN process found"
    )

    removed_any = False
    for path in _read_reset_paths():
        if path.exists():
            path.unlink()
            removed_any = True
            print(f"  ✓ Removed {path}")
        else:
            print(f"  - Not found {path}")

    if not removed_any:
        print("  No persisted runtime files found")
    return 0


def _doctor() -> int:
    """Print diagnostic information about the runtime environment."""
    settings = Settings()
    openvpn_bin = shutil.which("openvpn") or shutil.which("openvpn.exe")
    iface = detect_tun_interface(settings.vpn_interface_hint)
    pid_exists = Path(OPENVPN_PID_PATH).exists()

    _print_banner(
        "C O D A  ·  D O C T O R",
        [
            ("WEBAPP", settings.webapp_url),
            ("CONNECT", settings.connect_url),
            ("REDIS", settings.redis_url or "not set"),
        ],
    )
    _print_status("EXECUTOR", settings.executor_factory or "NoopExecutor")
    _print_status("OPENVPN", openvpn_bin or "not found")
    _print_status("VPN IFACE", iface or "not detected")
    _print_status("VPN PID", "present" if pid_exists else "absent")
    return 0


def main() -> None:
    """Entry point for the ``coda`` / ``coda-node`` CLI.

    Parses arguments, dispatches to the appropriate subcommand, and
    raises :class:`SystemExit` with the subcommand's return code.
    """
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args()

    if args.reset or args.command == "reset":
        raise SystemExit(_reset())

    if args.command == "start":
        _apply_overrides(args)
        settings = Settings()
        daemon_mode = getattr(args, "daemon", False)

        if daemon_mode:
            if is_daemon_running():
                status = daemon_status()
                print(f"Daemon already running (PID {status['pid']})")
                raise SystemExit(1)

            _print_banner(
                "C O D A  ·  D A E M O N",
                [
                    ("WEBAPP", settings.webapp_url),
                    ("ENDPOINT", f"{settings.host}:{settings.port}"),
                    ("MODE", _start_mode(settings.node_token)),
                ],
            )
            try:
                pid = start_daemon(
                    host=settings.host,
                    port=settings.port,
                    token=settings.node_token or None,
                )
                print(f"  Started daemon (PID {pid})")
                print(f"  Log file: {DAEMON_LOG_PATH}")
                print()
                print("  Use 'coda stop' to stop the daemon")
                print("  Use 'coda status' to check daemon status")
                print("  Use 'coda logs' to view log output")
            except RuntimeError as exc:
                print(f"  Failed to start daemon: {exc}")
                raise SystemExit(1) from None
            return

        _print_banner(
            "C O D A  ·  N O D E",
            [
                ("WEBAPP", settings.webapp_url),
                ("ENDPOINT", f"{settings.host}:{settings.port}"),
                ("MODE", _start_mode(settings.node_token)),
            ],
        )
        uvicorn.run(
            "coda_node.server.app:app",
            host=settings.host,
            port=settings.port,
            reload=False,
            log_level="warning",
        )
        return

    if args.command == "stop":
        if not is_daemon_running():
            print("No daemon is running")
            raise SystemExit(1)
        status = daemon_status()
        print(f"Stopping daemon (PID {status['pid']})...")
        stopped = stop_daemon()
        if stopped:
            print("  Daemon stopped")
            raise SystemExit(0)
        else:
            print("  Failed to stop daemon")
            raise SystemExit(1)

    if args.command == "status":
        status = daemon_status()
        _print_banner(
            "C O D A  ·  S T A T U S",
            [
                ("DAEMON", "running" if status["running"] else "stopped"),
                ("PID", str(status["pid"]) if status["pid"] else "-"),
                ("PID FILE", str(DAEMON_PID_PATH)),
            ],
        )
        _print_status("LOG FILE", str(DAEMON_LOG_PATH))
        _print_status("LOG EXISTS", "yes" if status["log_exists"] else "no")

        # Also show VPN status if available
        try:
            settings = Settings()
            iface = detect_tun_interface(settings.vpn_interface_hint)
            _print_status("VPN IFACE", iface or "not detected")
        except Exception:
            _print_status("VPN IFACE", "unknown")

        raise SystemExit(0 if status["running"] else 1)

    if args.command == "logs":
        lines = getattr(args, "lines", 50)
        log_output = tail_daemon_log(lines)
        if not log_output:
            print(f"No log file found at {DAEMON_LOG_PATH}")
            raise SystemExit(1)
        print(log_output)
        raise SystemExit(0)

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

    parser.error("a command is required")
