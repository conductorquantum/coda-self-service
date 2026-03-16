"""VPN tunnel management, health monitoring, and self-service provisioning.

This package handles the full VPN lifecycle for a Coda-connected node:

* **Preflight** -- detect an active tunnel interface and probe
  connectivity to the cloud endpoints before the server accepts jobs.
* **Background monitoring** -- periodically re-check VPN health and
  transition the service state between READY, DEGRADED, and
  VPN_UNAVAILABLE.
* **Self-service bootstrap** -- given a one-time token, fetch
  credentials and a VPN profile from the Coda cloud, start an OpenVPN
  daemon, and persist everything for future reconnects.
"""

from self_service.vpn.guard import (
    ProbeResult,
    ServiceState,
    VPNGuard,
    VPNStatus,
    detect_tun_interface,
    validate_key_permissions,
)
from self_service.vpn.service import (
    OPENVPN_LOG_PATH,
    OPENVPN_PID_PATH,
    SelfServiceError,
    apply_self_service_bundle,
    connect_settings,
    ensure_persisted_vpn,
    fetch_reconnect_bundle,
    fetch_self_service_bundle,
    kill_openvpn_daemon,
    self_service_settings,
)

__all__ = [
    "OPENVPN_LOG_PATH",
    "OPENVPN_PID_PATH",
    "ProbeResult",
    "SelfServiceError",
    "ServiceState",
    "VPNGuard",
    "VPNStatus",
    "apply_self_service_bundle",
    "connect_settings",
    "detect_tun_interface",
    "ensure_persisted_vpn",
    "fetch_reconnect_bundle",
    "fetch_self_service_bundle",
    "kill_openvpn_daemon",
    "self_service_settings",
    "validate_key_permissions",
]
