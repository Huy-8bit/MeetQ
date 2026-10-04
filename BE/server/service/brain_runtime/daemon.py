from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from redis.asyncio import Redis

from server.config import Settings
from server.events import EventType
from server.service.gateway.room_store import RoomStore
from server.service.brain_runtime.events import RedisEventPublisher
from server.service.brain_runtime.room_manager import RoomInterpreterManager
from server.meeting_modes import DEFAULT_BRSE_OUTPUT_MODE, active_human_participant_count
from server.service.ops.keys import (
    RUNTIME_HEARTBEAT_INTERVAL_SECONDS,
    RUNTIME_HEARTBEAT_KEY,
    RUNTIME_HEARTBEAT_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


def _snapshot_room_languages(snapshot) -> list[str]:
    return list(
        getattr(snapshot.room, "room_languages", None)
        or getattr(snapshot.room, "meeting_languages", None)
        or []
    )


def _is_room_expired(snapshot) -> bool:
    """Check if the room meeting duration has elapsed."""
    from datetime import datetime, timezone
    if snapshot is None:
        return True
    expires_at_str = getattr(snapshot.room, 'expires_at', None)
    if not expires_at_str:
        return False
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
        return datetime.now(timezone.utc) >= expires_at
    except (ValueError, TypeError):
        return False


class InterpreterDaemon:
    def __init__(self, settings: Settings, redis: Redis):
        self.settings = settings
        self.redis = redis
        self.gateway_control_channel = settings.redis_channel_gateway_control
        self.interpreter_events_channel = settings.redis_channel_interpreter_events
        self.room_store = RoomStore(redis, ttl_seconds=settings.room_meeting_duration_seconds + 300)
        self.managers: Dict[str, RoomInterpreterManager] = {}
        self._pubsub = None
        self._started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def _handle_gateway_event(self, message: dict) -> None:
        event_type = message.get("type")
        room_id = message.get("room_id")
        payload = message.get("payload", {})
        if not room_id:
            return

        if event_type == EventType.ROOM_CREATED:
            return

        if event_type == EventType.PARTICIPANT_JOINED:
            snapshot = await self.room_store.get_room_snapshot(room_id)
            if snapshot is None or not snapshot.room.brse_enabled:
                await self._terminate_manager(room_id)
                return
            # Don't spawn runtime for expired rooms
            if _is_room_expired(snapshot):
                await self._terminate_manager(room_id)
                return
            manager = await self._spawn_manager(room_id, snapshot=snapshot)
            if manager is not None:
                await manager.sync_room_context(_snapshot_room_languages(snapshot))
                await manager.sync_participant(payload)
            return

        if event_type == EventType.ROOM_BRSE_UPDATED:
            enabled = bool(payload.get("brse_enabled"))
            if not enabled:
                await self._terminate_manager(room_id)
                return

            snapshot = await self.room_store.get_room_snapshot(room_id)
            if snapshot is None or not snapshot.room.brse_enabled:
                return

            manager = await self._spawn_manager(room_id, snapshot=snapshot)
            if manager is not None:
                await manager.sync_room_context(_snapshot_room_languages(snapshot))
            return

        manager = self.managers.get(room_id)
        if manager is None:
            # Includes relay-mode changes while AI is off: the mode is stored on the room
            # and picked up by _spawn_manager when AI relay is turned back on.
            return

        if event_type == EventType.ROOM_RELAY_MODE_UPDATED:
            output_mode = payload.get("brse_output_mode")
            if isinstance(output_mode, str):
                await manager.set_output_mode(output_mode)
            return

        if event_type == EventType.PARTICIPANT_UPDATED:
            snapshot = await self.room_store.get_room_snapshot(room_id)
            if snapshot is None or not snapshot.room.brse_enabled:
                await self._terminate_manager(room_id)
                return
            await manager.sync_room_context(_snapshot_room_languages(snapshot))
            await manager.sync_participant(payload)
            return

        if event_type == EventType.PARTICIPANT_LEFT:
            participant_id = payload.get("participant_id")
            if participant_id:
                await manager.remove_participant(participant_id)
            snapshot = await self.room_store.get_room_snapshot(room_id)
            if (
                snapshot is None
                or not snapshot.room.brse_enabled
                or active_human_participant_count(snapshot.participants) == 0
            ):
                await self._terminate_manager(room_id)

    async def _spawn_manager(
        self,
        room_id: str,
        *,
        snapshot=None,
    ) -> Optional[RoomInterpreterManager]:
        if room_id in self.managers:
            return self.managers[room_id]

        if snapshot is None:
            snapshot = await self.room_store.get_room_snapshot(room_id)
        if snapshot is None or not snapshot.room.brse_enabled:
            return None

        # Don't spawn runtime for expired rooms
        if _is_room_expired(snapshot):
            logger.info("Room %s is expired; not spawning interpreter manager", room_id)
            return None

        brse_mode = getattr(snapshot.room, "brse_mode", "relay")
        effective_brse_output_mode = getattr(snapshot.room, "brse_output_mode", DEFAULT_BRSE_OUTPUT_MODE)
        audio_routing = getattr(snapshot.room, "audio_routing", None)
        if isinstance(audio_routing, dict):
            requested_brse_output_mode = audio_routing.get(
                "requested_brse_output_mode",
                effective_brse_output_mode,
            )
        else:
            requested_brse_output_mode = getattr(
                audio_routing,
                "requested_brse_output_mode",
                effective_brse_output_mode,
            )
        room_languages = _snapshot_room_languages(snapshot)
        logger.info(
            "Spawning interpreter manager for room %s brse_mode=%s requested_output_mode=%s "
            "effective_output_mode=%s room_languages=%s",
            room_id,
            brse_mode,
            requested_brse_output_mode,
            effective_brse_output_mode,
            room_languages,
        )
        publisher = RedisEventPublisher(self.redis, room_id, self.interpreter_events_channel)
        manager = RoomInterpreterManager(
            room_id,
            self.settings,
            publisher,
            brse_mode=brse_mode,
            brse_output_mode=requested_brse_output_mode,
            room_languages=room_languages,
        )
        self.managers[room_id] = manager

        try:
            await manager.start()
            manager.bootstrap_participants(
                snapshot.participants,
                meeting_languages=room_languages,
            )
            return manager
        except Exception:
            logger.exception("Failed to start interpreter manager for room %s", room_id)
            self.managers.pop(room_id, None)
            return None

    async def _terminate_manager(self, room_id: str) -> None:
        manager = self.managers.pop(room_id, None)
        if manager is None:
            return

        logger.info("Terminating interpreter manager for room %s", room_id)
        await manager.stop()

    async def shutdown(self) -> None:
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
            except Exception:
                logger.exception("Failed to unsubscribe interpreter daemon pubsub")
        for room_id in list(self.managers.keys()):
            await self._terminate_manager(room_id)

    async def _write_heartbeat(self) -> None:
        payload = {
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "started_at": self._started_at,
            "active_room_ids": sorted(self.managers.keys()),
            "active_manager_count": len(self.managers),
        }
        await self.redis.set(
            RUNTIME_HEARTBEAT_KEY,
            json.dumps(payload),
            ex=RUNTIME_HEARTBEAT_TTL_SECONDS,
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await self._write_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Failed to write brain runtime heartbeat", exc_info=True)
            await asyncio.sleep(RUNTIME_HEARTBEAT_INTERVAL_SECONDS)

    async def run(self) -> None:
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(self.gateway_control_channel)
        logger.info("Interpreter daemon listening on %s", self.gateway_control_channel)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except json.JSONDecodeError:
                    logger.error("Failed to decode gateway event JSON")
                    continue
                await self._handle_gateway_event(data)
        except asyncio.CancelledError:
            logger.info("Interpreter daemon cancelled")
            raise
        finally:
            heartbeat_task.cancel()
            await self.shutdown()
