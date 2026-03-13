"""VPN monitoring and self-service bootstrap exports."""

from self_service.vpn.guard import (
    ProbeResult,
    ServiceState,
    VPNGuard,
    VPNStatus,
    _detect_tun_interface,
    _parse_darwin_tun_interfaces,
    _parse_windows_tun_interfaces,
    _probe_target,
    _resolve_host,
    validate_key_permissions,
)
from self_service.vpn.service import (
    OPENVPN_LOG_PATH,
    OPENVPN_PID_PATH,
    SelfServiceError,
    apply_self_service_bundle,
    ensure_persisted_vpn,
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
    "_detect_tun_interface",
    "_parse_darwin_tun_interfaces",
    "_parse_windows_tun_interfaces",
    "_probe_target",
    "_resolve_host",
    "apply_self_service_bundle",
    "ensure_persisted_vpn",
    "fetch_self_service_bundle",
    "kill_openvpn_daemon",
    "self_service_settings",
    "validate_key_permissions",
]
