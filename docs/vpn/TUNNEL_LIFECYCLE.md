# Tunnel Lifecycle

The node manages an OpenVPN daemon as a subprocess. The full lifecycle
covers profile validation, daemon launch, tunnel detection, and
cleanup.

## Profile Validation

Before writing a VPN profile to disk, `_validate_vpn_profile()` scans
every line for dangerous OpenVPN directives that could execute
arbitrary commands:

```python
_DANGEROUS_OVPN_DIRECTIVES = frozenset({
    "script-security", "up", "down", "client-connect",
    "client-disconnect", "learn-address", "auth-user-pass-verify",
    "tls-verify", "ipchange", "route-up", "route-pre-down", "plugin",
})
```

If any directive is found, a `NodeError` is raised with the
line number, and the profile is rejected. This prevents a compromised
cloud from executing arbitrary code on the node host.

## Profile Storage

Validated profiles are written to disk by `_write_vpn_profile()`:

- Default path: `/tmp/coda-node.ovpn` (configurable via
  `CODA_NODE_VPN_PROFILE_PATH`).
- Permissions: `0600` on POSIX systems.
- The profile received from the cloud is plaintext (the cloud decodes
  base64 before returning it in the connect response).
- If the profile does not contain `reneg-sec`, the directive
  `reneg-sec 0` is appended automatically. This disables TLS
  renegotiation, preventing connection drops on long-lived tunnels.

## Daemon Launch

`_start_openvpn()` starts the OpenVPN daemon with platform-specific
behavior:

### POSIX (Linux/macOS)

```bash
openvpn --config /tmp/coda-node.ovpn \
        --daemon \
        --writepid /tmp/coda-node-openvpn.pid \
        --log /tmp/coda-node-openvpn.log
```

Raises `NodeError` if the command exits with a non-zero return
code.

### Windows

Uses `subprocess.Popen` with `CREATE_NEW_PROCESS_GROUP`,
`DETACHED_PROCESS`, and `CREATE_NO_WINDOW` flags. The PID is written
manually since `--writepid` behaves differently on Windows.

### Prerequisites

The `openvpn` binary must be on `$PATH`. If not found,
`NodeError` is raised with instructions to install OpenVPN or
disable auto VPN.

## Tunnel Detection

After launching OpenVPN, `_wait_for_tunnel()` polls for an active VPN
interface:

- **Poll interval**: 1 second.
- **Timeout**: 30 seconds.
- **Detection**: Uses `detect_tun_interface()` with the configured
  `vpn_interface_hint`.

If the interface does not appear within the timeout:

1. The last 20 lines of the OpenVPN log are captured.
2. The daemon is killed via `kill_openvpn_daemon()`.
3. A `NodeError` is raised with the log tail for debugging.

## Interface Detection

`detect_tun_interface()` in `vpn/guard.py` uses platform-specific
commands:

| Platform | Command | Parser |
|---|---|---|
| macOS | `ifconfig` | `_parse_darwin_tun_interfaces()` — finds the first `utun*`/`tun*` interface with an `inet` address. |
| Linux | `ip -o link show type tun` | Parses the interface name from the output. |
| Windows | `Get-NetAdapter -IncludeHidden \| ConvertTo-Json` | `_parse_windows_tun_interfaces()` — finds adapters with TAP/WinTUN/OpenVPN in the description. |

When a `hint` is provided, only that specific interface is checked
rather than scanning all interfaces.

## Daemon Shutdown

`kill_openvpn_daemon()`:

1. Reads the PID from `OPENVPN_PID_PATH`.
2. Sends `SIGTERM` (POSIX) or runs `taskkill /PID <pid> /T /F`
   (Windows).
3. Removes the PID file.
4. Returns `True` if a process was signalled, `False` if no PID file
   existed.

Silently succeeds if the process is already gone.

## Reconnect Path

On reconnect (`ensure_persisted_vpn()` in `vpn/service.py`):

1. Checks for a persisted config file.
2. If `vpn_required` is `False` (i.e. HTTPS connection mode), returns
   immediately — no VPN profile or daemon is needed.
3. If `node_auto_vpn` is disabled, returns immediately.
4. If the VPN profile file exists and no tunnel is currently active,
   starts the OpenVPN daemon and waits for the interface.
5. If VPN is required but the profile is missing, raises
   `NodeError` telling the operator to re-provision with a new
   token.

## File Locations

| File | Default Path | Purpose |
|---|---|---|
| VPN profile | `/tmp/coda-node.ovpn` | OpenVPN client configuration |
| PID file | `/tmp/coda-node-openvpn.pid` | Managed daemon process ID |
| Log file | `/tmp/coda-node-openvpn.log` | OpenVPN daemon log output |
