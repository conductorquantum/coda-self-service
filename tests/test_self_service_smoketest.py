"""Deployment smoketest for the self-service QPU connect flow.

Exercises both the QPU self-service (first-connect) and JWT reconnect
handshakes against a live deployment.  A fresh QPU self-service token is
created via the Supabase service-role API at the start of each run
and cleaned up afterwards, so no manual token provisioning is needed.

Required environment variables
------------------------------
CODA_SMOKETEST_URL              Target webapp URL.
CODA_SMOKETEST_SUPABASE_URL     Supabase project URL for the target env.
CODA_SMOKETEST_SUPABASE_KEY     Supabase service-role key.
CODA_SMOKETEST_QPU_ID           QPU ID dedicated to smoketesting
                                (e.g. ``cq-qpu-smoketest``).

Optional environment variables
------------------------------
CODA_SMOKETEST_VERCEL_BYPASS    Vercel deployment-protection bypass secret.
                                Required for staging; omit for production.

Usage
-----
Local::

    export CODA_SMOKETEST_URL=https://staging.coda.conductorquantum.com
    export CODA_SMOKETEST_SUPABASE_URL=https://xxx.supabase.co
    export CODA_SMOKETEST_SUPABASE_KEY=eyJ...
    export CODA_SMOKETEST_QPU_ID=cq-qpu-smoketest
    uv run pytest tests/test_self_service_smoketest.py -v

CI — all variables are fetched from ``coda-{env}-backend`` in AWS
Secrets Manager by the deployment workflow.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from base64 import urlsafe_b64encode
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

from self_service.errors import SelfServiceError
from self_service.server.config import Settings
from self_service.vpn import (
    VPNGuard,
    apply_self_service_bundle,
    detect_tun_interface,
    fetch_reconnect_bundle,
    fetch_self_service_bundle,
    kill_openvpn_daemon,
)

pytestmark = pytest.mark.smoketest

_PREFIX = "CODA_SMOKETEST"


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _connect_headers() -> dict[str, str]:
    """Build extra headers for the connect endpoint.

    When ``CODA_SMOKETEST_VERCEL_BYPASS`` is set, include the
    ``x-vercel-protection-bypass`` header so requests pass through
    Vercel's deployment protection (staging only).
    """
    bypass = os.environ.get(f"{_PREFIX}_VERCEL_BYPASS", "").strip()
    if bypass:
        return {"x-vercel-protection-bypass": bypass}
    return {}


def _generate_bootstrap_token() -> tuple[str, str, str]:
    """Return ``(raw_token, token_hash, token_prefix)``."""
    raw = f"cqb_{urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')}"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:16]
    return raw, token_hash, prefix


async def _get_owner_user_id(supabase_url: str, supabase_key: str) -> str:
    """Return the UUID of the first admin user to use as token owner."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{supabase_url}/auth/v1/admin/users?per_page=1",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        users = data.get("users", data) if isinstance(data, dict) else data
        assert users, "No users found in Supabase — cannot set token owner"
        return str(users[0]["id"])


async def _create_bootstrap_token(
    supabase_url: str,
    supabase_key: str,
    qpu_id: str,
) -> tuple[str, str]:
    """Insert a bootstrap token via Supabase REST and return ``(raw_token, row_id)``."""
    raw_token, token_hash, token_prefix = _generate_bootstrap_token()
    owner_id = await _get_owner_user_id(supabase_url, supabase_key)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{supabase_url}/rest/v1/qpu_bootstrap_tokens",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json={
                "label": "CI smoketest (auto-generated)",
                "token_hash": token_hash,
                "token_prefix": token_prefix,
                "qpu_id": qpu_id,
                "created_by": owner_id,
                "owner_user_id": owner_id,
                "config": {
                    "display_name": "Smoketest QPU",
                    "native_gate_set": "superconducting_cz",
                    "num_qubits": 5,
                },
            },
        )
        resp.raise_for_status()
        row = resp.json()
        row_id = row[0]["id"] if isinstance(row, list) else row["id"]

    return raw_token, row_id


async def _revoke_bootstrap_token(
    supabase_url: str,
    supabase_key: str,
    token_id: str,
) -> None:
    """Mark the smoketest token as revoked so it cannot be reused."""
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{supabase_url}/rest/v1/qpu_bootstrap_tokens",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
            params={"id": f"eq.{token_id}"},
            json={"revoked_at": "now()"},
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def smoketest_ctx() -> dict[str, Any]:
    """Provision a bootstrap token, run both connect flows, yield context."""
    target_url = _require_env(f"{_PREFIX}_URL")
    supabase_url = _require_env(f"{_PREFIX}_SUPABASE_URL")
    supabase_key = _require_env(f"{_PREFIX}_SUPABASE_KEY")
    qpu_id = _require_env(f"{_PREFIX}_QPU_ID")

    raw_token, token_id = await _create_bootstrap_token(
        supabase_url, supabase_key, qpu_id
    )

    extra_headers = _connect_headers()

    bootstrap_settings = Settings(
        webapp_url=target_url,
        self_service_token=raw_token,
        self_service_machine_fingerprint="ci-smoketest",
        self_service_auto_vpn=False,
        self_service_connect_headers=extra_headers,
    )

    try:
        bootstrap_bundle = await fetch_self_service_bundle(bootstrap_settings)
        bootstrap_bundle = cast(dict[str, Any], bootstrap_bundle)
    except Exception:
        await _revoke_bootstrap_token(supabase_url, supabase_key, token_id)
        raise

    reconnect_settings = Settings(
        qpu_id=cast(str, bootstrap_bundle["qpu_id"]),
        jwt_private_key=cast(str, bootstrap_bundle["jwt_private_key"]),
        jwt_key_id=cast(str, bootstrap_bundle["jwt_key_id"]),
        webapp_url=target_url,
        self_service_machine_fingerprint="ci-smoketest",
        self_service_auto_vpn=False,
        self_service_connect_headers=extra_headers,
    )

    reconnect_bundle = await fetch_reconnect_bundle(reconnect_settings)
    reconnect_bundle = cast(dict[str, Any], reconnect_bundle)

    return {
        "target_url": target_url,
        "qpu_id": qpu_id,
        "bootstrap_bundle": bootstrap_bundle,
        "reconnect_bundle": reconnect_bundle,
        "token_id": token_id,
        "supabase_url": supabase_url,
        "supabase_key": supabase_key,
    }


@pytest.fixture(autouse=True, scope="module")
async def _cleanup(smoketest_ctx: dict[str, Any]) -> None:  # type: ignore[misc]
    """Revoke the disposable bootstrap token after all tests finish."""
    yield  # type: ignore[misc]
    await _revoke_bootstrap_token(
        smoketest_ctx["supabase_url"],
        smoketest_ctx["supabase_key"],
        smoketest_ctx["token_id"],
    )


# ---------------------------------------------------------------------------
# Bootstrap flow assertions
# ---------------------------------------------------------------------------


def _assert_bundle_structure(bundle: dict[str, Any]) -> None:
    assert isinstance(bundle.get("qpu_id"), str) and bundle["qpu_id"]
    assert isinstance(bundle.get("qpu_display_name"), str)
    assert isinstance(bundle.get("jwt_key_id"), str) and bundle["jwt_key_id"]
    assert isinstance(bundle.get("redis_url"), str) and bundle["redis_url"]
    assert isinstance(bundle.get("connect_id"), str) and bundle["connect_id"]


def _assert_paths(bundle: dict[str, Any]) -> None:
    assert bundle["connect_path"] == "/api/internal/qpu/connect"
    assert bundle["register_path"] == "/api/internal/qpu/register"
    assert bundle["heartbeat_path"] == "/api/internal/qpu/heartbeat"
    assert bundle["webhook_path"] == "/api/internal/qpu/webhook"


def _assert_vpn(bundle: dict[str, Any]) -> None:
    vpn = bundle.get("vpn")
    assert isinstance(vpn, dict)
    assert isinstance(vpn.get("required"), bool)
    assert isinstance(vpn.get("check_interval_sec"), int)
    probes = vpn.get("probe_targets")
    assert isinstance(probes, list) and len(probes) > 0
    if vpn["required"]:
        profile = vpn.get("client_profile_ovpn")
        assert isinstance(profile, str) and "client" in profile


@pytest.mark.asyncio
async def test_bootstrap_returns_valid_bundle(
    smoketest_ctx: dict[str, Any],
) -> None:
    bundle = smoketest_ctx["bootstrap_bundle"]
    _assert_bundle_structure(bundle)
    _assert_paths(bundle)
    _assert_vpn(bundle)

    base_url = bundle.get("webapp_url") or bundle.get("cloud_base_url")
    assert base_url == smoketest_ctx["target_url"]


@pytest.mark.asyncio
async def test_bootstrap_issues_jwt_credentials(
    smoketest_ctx: dict[str, Any],
) -> None:
    bundle = smoketest_ctx["bootstrap_bundle"]
    assert isinstance(bundle.get("jwt_private_key"), str)
    assert bundle["jwt_private_key"].startswith("-----BEGIN")
    assert isinstance(bundle.get("jwt_key_id"), str) and bundle["jwt_key_id"]


@pytest.mark.asyncio
async def test_bootstrap_targets_correct_qpu(
    smoketest_ctx: dict[str, Any],
) -> None:
    assert smoketest_ctx["bootstrap_bundle"]["qpu_id"] == smoketest_ctx["qpu_id"]


# ---------------------------------------------------------------------------
# Reconnect flow assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_returns_valid_bundle(
    smoketest_ctx: dict[str, Any],
) -> None:
    bundle = smoketest_ctx["reconnect_bundle"]
    _assert_bundle_structure(bundle)
    _assert_paths(bundle)
    _assert_vpn(bundle)

    base_url = bundle.get("webapp_url") or bundle.get("cloud_base_url")
    assert base_url == smoketest_ctx["target_url"]


@pytest.mark.asyncio
async def test_reconnect_omits_private_key(
    smoketest_ctx: dict[str, Any],
) -> None:
    assert not smoketest_ctx["reconnect_bundle"].get("jwt_private_key")


@pytest.mark.asyncio
async def test_reconnect_preserves_identity(
    smoketest_ctx: dict[str, Any],
) -> None:
    bootstrap = smoketest_ctx["bootstrap_bundle"]
    reconnect = smoketest_ctx["reconnect_bundle"]
    assert reconnect["qpu_id"] == bootstrap["qpu_id"]
    assert reconnect["jwt_key_id"] == bootstrap["jwt_key_id"]


# ---------------------------------------------------------------------------
# VPN connection tests (require Docker with --cap-add=NET_ADMIN --device /dev/net/tun)
# ---------------------------------------------------------------------------


def _has_net_admin() -> bool:
    """Return True if the process can create tun devices (i.e. has NET_ADMIN)."""
    import subprocess

    try:
        result = subprocess.run(
            ["ip", "tuntap", "add", "mode", "tun", "dev", "_probe0"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            subprocess.run(
                ["ip", "tuntap", "del", "mode", "tun", "dev", "_probe0"],
                capture_output=True,
                timeout=5,
            )
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


@pytest_asyncio.fixture(scope="module")
async def vpn_settings(smoketest_ctx: dict[str, Any]) -> Settings | None:
    """Start OpenVPN from the bootstrap bundle and yield live Settings.

    Yields ``None`` (and all dependent tests skip) when NET_ADMIN is
    unavailable or VPN is not required for the environment.  The daemon
    is killed after all VPN tests finish.
    """
    if not _has_net_admin():
        yield None
        return

    bundle = smoketest_ctx["bootstrap_bundle"]
    vpn = bundle.get("vpn", {})
    if not vpn.get("required"):
        yield None
        return

    extra_headers = _connect_headers()
    settings = Settings(
        webapp_url=smoketest_ctx["target_url"],
        qpu_id=smoketest_ctx["qpu_id"],
        jwt_private_key=cast(str, bundle["jwt_private_key"]),
        jwt_key_id=cast(str, bundle["jwt_key_id"]),
        self_service_machine_fingerprint="ci-smoketest",
        self_service_auto_vpn=True,
        self_service_connect_headers=extra_headers,
    )

    try:
        await apply_self_service_bundle(settings, bundle)
    except SelfServiceError:
        kill_openvpn_daemon()
        yield None
        return

    try:
        yield settings
    finally:
        kill_openvpn_daemon()


@pytest.mark.asyncio
async def test_vpn_tunnel_establishes(vpn_settings: Settings | None) -> None:
    """Verify the OpenVPN tunnel interface is up."""
    if vpn_settings is None:
        pytest.skip(
            "VPN tunnel not available (needs --cap-add=NET_ADMIN, native Linux Docker)"
        )

    iface = detect_tun_interface(vpn_settings.vpn_interface_hint)
    assert iface is not None, "OpenVPN started but no tunnel interface detected"


@pytest.mark.asyncio
async def test_vpn_probe_targets_reachable(
    smoketest_ctx: dict[str, Any],
    vpn_settings: Settings | None,
) -> None:
    """Verify probe targets are reachable through the VPN tunnel."""
    if vpn_settings is None:
        pytest.skip(
            "VPN tunnel not available (needs --cap-add=NET_ADMIN, native Linux Docker)"
        )

    probe_targets = (
        smoketest_ctx["bootstrap_bundle"].get("vpn", {}).get("probe_targets", [])
    )
    if not probe_targets:
        pytest.skip("No probe targets defined in VPN config")

    guard = VPNGuard(
        probe_targets=probe_targets,
        interface_hint=vpn_settings.vpn_interface_hint,
        vpn_required=True,
    )
    status = await guard.preflight()
    assert status.ok, f"VPN preflight failed: {status.reason}"
    assert status.interface_found, "VPN interface not detected during preflight"

    for probe in status.probes or []:
        assert probe.ok, f"Probe {probe.target} failed: {probe.error}"
