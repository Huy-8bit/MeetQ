from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Optional

from redis.asyncio import Redis

from server.config import Settings
from server.events import EventType
from server.gateway.room_store import RoomStore
from server.interpreter.event_publisher import RedisEventPublisher
from server.interpreter.room_manager import RoomInterpreterManager
from server.meeting_modes import active_human_participant_count

logger = logging.getLogger(__name__)


class InterpreterDaemon:
    def __init__(self, settings: Settings, redis: Redis):
        self.settings = settings
        self.redis = redis
        self.gateway_control_channel = settings.redis_channel_gateway_control
        self.interpreter_events_channel = settings.redis_channel_interpreter_events
        self.room_store = RoomStore(redis, ttl_seconds=settings.room_token_ttl_seconds)
        self.managers: Dict[str, RoomInterpreterManager] = {}
        self._pubsub = None

    async def _handle_gateway_event(self, message: dict) -> None:
        event_type = message.get("type")
        room_id = message.get("room_id")
        payload = message.get("payload", {})
        if not room_id:
            return

        if event_type == EventType.ROOM_CREATED:
            return

        if event_type == EventType.PARTICIPANT_JOINED:
            manager = await self._spawn_manager(room_id)
            if manager is not None:
                await manager.sync_participant(payload)
            return

        manager = self.managers.get(room_id)
        if manager is None:
            return

        if event_type == EventType.PARTICIPANT_UPDATED:
            await manager.sync_participant(payload)
            return

        if event_type == EventType.PARTICIPANT_LEFT:
            participant_id = payload.get("participant_id")
            if participant_id:
                await manager.remove_participant(participant_id)
            snapshot = await self.room_store.get_room_snapshot(room_id)
            if snapshot is None or active_human_participant_count(snapshot.participants) == 0:
                await self._terminate_manager(room_id)

    async def _spawn_manager(self, room_id: str) -> Optional[RoomInterpreterManager]:
        if room_id in self.managers:
            return self.managers[room_id]

        logger.info("Spawning interpreter manager for room %s", room_id)
        publisher = RedisEventPublisher(self.redis, room_id, self.interpreter_events_channel)
        manager = RoomInterpreterManager(room_id, self.settings, publisher)
        self.managers[room_id] = manager

        try:
            await manager.start()
            snapshot = await self.room_store.get_room_snapshot(room_id)
            if snapshot is not None:
                manager.bootstrap_participants(snapshot.participants)
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

    async def run(self) -> None:
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(self.gateway_control_channel)
        logger.info("Interpreter daemon listening on %s", self.gateway_control_channel)

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
            await self.shutdown()
