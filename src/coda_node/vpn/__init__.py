"""VPN tunnel management, health monitoring, and node provisioning.

This package handles the full VPN lifecycle for a Coda-connected node:

* **Preflight** -- detect an active tunnel interface and probe
  connectivity to the cloud endpoints before the server accepts jobs.
* **Background monitoring** -- periodically re-check VPN health and
  transition the service state between READY, DEGRADED, and
  VPN_UNAVAILABLE.
* **Self-service provisioning** -- given a one-time token, fetch
  credentials and a VPN profile from the Coda cloud, start an OpenVPN
  daemon, and persist everything for future reconnects.
"""

from coda_node.vpn.guard import (
    ProbeResult,
    ServiceState,
    VPNGuard,
    VPNStatus,
    detect_tun_interface,
    validate_key_permissions,
)
from coda_node.vpn.service import (
    OPENVPN_LOG_PATH,
    OPENVPN_PID_PATH,
    NodeError,
    apply_node_bundle,
    connect_settings,
    ensure_persisted_vpn,
    fetch_reconnect_bundle,
    fetch_node_bundle,
    kill_openvpn_daemon,
    node_settings,
)

__all__ = [
    "OPENVPN_LOG_PATH",
    "OPENVPN_PID_PATH",
    "ProbeResult",
    "NodeError",
    "ServiceState",
    "VPNGuard",
    "VPNStatus",
    "apply_node_bundle",
    "connect_settings",
    "detect_tun_interface",
    "ensure_persisted_vpn",
    "fetch_reconnect_bundle",
    "fetch_node_bundle",
    "kill_openvpn_daemon",
    "node_settings",
    "validate_key_permissions",
]
