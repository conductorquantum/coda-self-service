# CLI Reference

The `coda` (and `coda-node`) command-line interface provides
subcommands for managing the node runtime, including daemon mode for
running as a background process.

## `coda start`

Start the FastAPI server in foreground or daemon mode.

```
coda start [--token TOKEN] [--host HOST] [--port PORT] [--daemon]
```

| Flag | Env Override | Description |
|---|---|---|
| `--token`, `-t` | `CODA_NODE_TOKEN` | Node token for first-time provisioning. |
| `--host`, `-H` | `CODA_HOST` | Bind address (default: `0.0.0.0`). |
| `--port`, `-p` | `CODA_PORT` | Bind port (default: `8080`). |
| `--daemon`, `-d` | — | Run as a background daemon process. |

CLI flags are injected into environment variables before `Settings` is
constructed, so they take highest precedence.

On startup, a banner is printed showing the webapp URL, bind endpoint,
and startup mode (`token` or `env`).

### Foreground Mode (default)

The server runs under uvicorn with `reload=False` and
`log_level="warning"`. Use Ctrl+C to stop.

### Daemon Mode (`--daemon`)

When `--daemon` is specified, the server spawns as a background process:

- PID is written to `/tmp/coda-node.pid`
- Output is redirected to `/tmp/coda-node.log`
- The command returns immediately after spawning

Use `coda stop` to terminate the daemon.

## `coda stop`

Stop the background daemon process.

```
coda stop
```

Sends `SIGTERM` to the daemon and waits up to 10 seconds for graceful
shutdown. If the process does not exit, sends `SIGKILL`.

Exit code: `0` if daemon was stopped, `1` if no daemon was running.

## `coda status`

Show daemon status and basic runtime info.

```
coda status
```

Displays:

| Field | Description |
|---|---|
| DAEMON | `running` or `stopped` |
| PID | Process ID (if running) |
| PID FILE | Path to PID file |
| LOG FILE | Path to log file |
| LOG EXISTS | Whether log file exists |
| VPN IFACE | Detected VPN interface (if available) |

Exit code: `0` if daemon is running, `1` if stopped.

## `coda logs`

Show recent daemon log output.

```
coda logs [-n LINES]
```

| Flag | Default | Description |
|---|---|---|
| `-n`, `--lines` | `50` | Number of lines to display. |

Reads from `/tmp/coda-node.log`.

Exit code: `0` if log exists, `1` if not found.

## `coda doctor`

Print a diagnostic summary of the local environment.

```
coda doctor
```

Checks and displays:

| Check | Source |
|---|---|
| WEBAPP | `settings.webapp_url` |
| CONNECT | `settings.connect_url` |
| REDIS | `settings.redis_url` |
| EXECUTOR | `settings.executor_factory` or `"NoopExecutor"` |
| OPENVPN | `shutil.which("openvpn")` |
| VPN IFACE | `detect_tun_interface(hint)` |
| VPN PID | Whether `OPENVPN_PID_PATH` exists |

Useful for verifying that OpenVPN is installed, the VPN interface is
active, and configuration is loaded correctly.

## `coda reset`

Clear all persisted runtime state and stop both the daemon and VPN.

```
coda reset
```

Actions:

1. Stops the Coda daemon (if running in background).
2. Stops the managed OpenVPN daemon (if running).
3. Removes all persisted files:
   - `/tmp/coda.config`
   - `/tmp/coda-private-key`
   - `/tmp/coda-node.pid` (daemon PID)
   - `/tmp/coda-node.log` (daemon log)
   - `/tmp/coda-node-openvpn.pid`
   - `/tmp/coda-node-openvpn.log`
   - `/tmp/coda-node.ovpn`
   - Any additional paths referenced in the config file
     (`jwt_private_key_path`, `node_vpn_profile_path`).

After reset, the node must be re-provisioned with a fresh node token.

Also available as a global flag: `coda --reset`.

## `coda stop-vpn`

Stop the managed OpenVPN daemon without clearing credentials.

```
coda stop-vpn
```

Sends `SIGTERM` (POSIX) or `taskkill` (Windows) to the managed
OpenVPN process and removes the PID file. Does not remove the VPN
profile, credentials, or runtime config.

Exit code: `0` if a daemon was stopped, `1` if no managed daemon was
found.

## Entry Points

Both `coda` and `coda-node` are registered as console scripts
in `pyproject.toml` and point to the same function:

```toml
[project.scripts]
coda = "coda_node.server.cli:main"
coda-node = "coda_node.server.cli:main"
```
