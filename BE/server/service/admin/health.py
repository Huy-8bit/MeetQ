"""Infrastructure health for the admin portal, from real probes only."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from server.service.admin import metrics
from server.service.admin.schemas import HealthComponent, SystemHealth
from server.service.ops.keys import RUNTIME_HEARTBEAT_TTL_SECONDS


async def _redis_ok(redis: Any) -> bool:
    try:
        return bool(await asyncio.wait_for(redis.ping(), timeout=2))
    except Exception:
        return False


async def system_health(
    *,
    redis: Any,
    live_service: Any,
    history_service: Any,
    inspector: Optional[Any],
) -> SystemHealth:
    redis_ok, heartbeat, mongo_ok, livekit_ok = await asyncio.gather(
        _redis_ok(redis),
        live_service.heartbeat(),
        history_service.ping() if history_service.available else asyncio.sleep(0, result=None),
        inspector.ping() if inspector is not None else asyncio.sleep(0, result=None),
    )
    now = metrics.utc_now()
    components = [
        HealthComponent(
            key="redis",
            label="Redis (live room state)",
            status="healthy" if redis_ok else "down",
            detail=None if redis_ok else "Ping failed",
        )
    ]

    if heartbeat is None:
        runtime = HealthComponent(
            key="brain_runtime",
            label="BRSE runtime",
            status="down",
            detail=f"No heartbeat in the last {RUNTIME_HEARTBEAT_TTL_SECONDS}s",
        )
    else:
        beat_at = metrics.parse_dt(heartbeat.get("at"))
        age = (now - beat_at).total_seconds() if beat_at else None
        count = heartbeat.get("active_manager_count")
        runtime = HealthComponent(
            key="brain_runtime",
            label="BRSE runtime",
            status="healthy",
            detail=f"{count} room runtime(s) · heartbeat {int(age)}s ago" if age is not None else None,
        )
    components.append(runtime)

    if not history_service.available:
        components.append(
            HealthComponent(key="mongo", label="MongoDB (history)", status="unknown", detail="Not configured")
        )
    else:
        components.append(
            HealthComponent(
                key="mongo",
                label="MongoDB (history)",
                status="healthy" if mongo_ok else "down",
                detail=None if mongo_ok else "Ping failed",
            )
        )

    if inspector is None:
        components.append(HealthComponent(key="livekit", label="LiveKit", status="unknown", detail="Not configured"))
    else:
        components.append(
            HealthComponent(
                key="livekit",
                label="LiveKit",
                status="healthy" if livekit_ok else "down",
                detail=None if livekit_ok else "Server API unreachable",
            )
        )

    statuses = {component.key: component.status for component in components}
    if statuses["redis"] == "down" or statuses["brain_runtime"] == "down":
        overall = "down"
    elif any(status in ("down", "degraded") for status in statuses.values()):
        overall = "degraded"
    else:
        overall = "healthy"
    return SystemHealth(checked_at=metrics.iso(now), overall=overall, components=components)
