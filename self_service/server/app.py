"""FastAPI application for the standalone Coda-connected node server."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI

from self_service.server.auth import sign_token
from self_service.server.config import Settings
from self_service.server.consumer import RedisConsumer
from self_service.server.executor import JobExecutor, load_executor
from self_service.server.webhook import WebhookClient
from self_service.vpn import (
    ServiceState,
    VPNGuard,
    ensure_persisted_vpn,
    kill_openvpn_daemon,
    self_service_settings,
)

logger = logging.getLogger(__name__)


def _derive_technology(native_gate_set: str) -> str:
    parts = native_gate_set.split("_")
    return parts[0] if parts else "unknown"


async def _register_with_coda(settings: Settings) -> None:
    token = sign_token(
        settings.qpu_id,
        settings.jwt_private_key,
        key_id=settings.jwt_key_id,
    )
    payload = {
        "qpu_id": settings.qpu_id,
        "display_name": settings.qpu_display_name,
        "provider": settings.advertised_provider,
        "technology": _derive_technology(settings.native_gate_set),
        "native_gate_set": settings.native_gate_set,
        "num_qubits": settings.num_qubits,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            settings.register_url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()


async def _on_vpn_state_change(state: ServiceState) -> None:
    logger.warning("VPN state changed: %s", state.value)


def create_app(executor: JobExecutor | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = Settings()

        if settings.self_service_token:
            await self_service_settings(settings)
        else:
            await ensure_persisted_vpn(settings)

        guard = VPNGuard(
            probe_targets=settings.vpn_probe_urls,
            interface_hint=settings.vpn_interface_hint,
            check_interval_sec=settings.vpn_check_interval_sec,
            vpn_required=settings.vpn_required,
        )
        vpn_status = await guard.preflight()
        if (
            not vpn_status.ok
            and settings.vpn_required
            and not settings.allow_degraded_startup
        ):
            raise RuntimeError(f"VPN preflight failed: {vpn_status.reason}")

        redis_client = aioredis.from_url(settings.redis_url)
        runner = executor or load_executor(settings)
        webhook = WebhookClient(
            qpu_id=settings.qpu_id,
            jwt_private_key=settings.jwt_private_key,
            jwt_key_id=settings.jwt_key_id,
        )
        consumer = RedisConsumer(
            redis=redis_client,
            runner=runner,
            webhook=webhook,
            qpu_id=settings.qpu_id,
        )

        try:
            await _register_with_coda(settings)
        except Exception:
            logger.exception("Failed to register with coda; will continue startup")

        watch_task = asyncio.create_task(guard.watch(_on_vpn_state_change))
        consumer_task = asyncio.create_task(consumer.consume_loop())

        app.state.settings = settings
        app.state.guard = guard
        app.state.consumer = consumer
        app.state.webhook = webhook

        yield

        consumer.stop()
        guard.stop()
        watch_task.cancel()
        consumer_task.cancel()
        with suppress(asyncio.CancelledError):
            await watch_task
        with suppress(asyncio.CancelledError):
            await consumer_task
        await webhook.close()
        await redis_client.aclose()
        kill_openvpn_daemon()

    app = FastAPI(title="Coda Self-Service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        guard: VPNGuard = app.state.guard
        consumer: RedisConsumer = app.state.consumer
        return {
            "ready": guard.is_ready,
            "vpn_state": guard.state.value,
            "redis_healthy": consumer.redis_healthy,
            "current_job": consumer.current_job_id,
        }

    return app


app = create_app()
