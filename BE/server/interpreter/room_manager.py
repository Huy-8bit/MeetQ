from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Iterable, Optional, Set

import livekit.rtc as rtc

from server.config import Settings
from server.interpreter.audio_input import LiveKitAudioInput
from server.interpreter.event_publisher import RedisEventPublisher
from server.interpreter.interpreter_client import InterpreterRealtimeClient
from server.interpreter.livekit_runtime import LiveKitRuntime
from server.interpreter.output_router import OutputRouter

logger = logging.getLogger(__name__)


class RoomInterpreterManager:
    def __init__(self, room_id: str, settings: Settings, publisher: RedisEventPublisher):
        self.room_id = room_id
        self.settings = settings
        self.publisher = publisher
        self.runtime = LiveKitRuntime(
            room_id=room_id,
            settings=settings,
            on_media_connected=self._on_media_connected,
            on_media_disconnected=self._on_media_disconnected,
            on_audio_stream=self._on_audio_stream,
        )
        self.participants: Dict[str, Dict[str, Any]] = {}
        self.active_streams: Dict[str, rtc.AudioStream] = {}
        self.active_inputs: Dict[str, LiveKitAudioInput] = {}
        self.routers: Dict[str, OutputRouter] = {}
        self.clients: Dict[str, InterpreterRealtimeClient] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.speaker_targets: Dict[str, str] = {}
        self.transcript_state: Dict[str, Dict[str, Any]] = {}
        self._closed = False

    async def start(self) -> None:
        await self.runtime.connect()

    async def stop(self) -> None:
        self._closed = True
        for speaker_id in list(self.active_streams.keys()):
            await self._teardown_speaker(speaker_id)
        await self.runtime.disconnect()

    def bootstrap_participants(self, participants: Iterable[Any]) -> None:
        for participant in participants:
            payload = self._normalize_participant(participant)
            participant_id = payload.get("participant_id")
            if participant_id:
                self.participants[participant_id] = payload

        if self.active_streams:
            asyncio.create_task(self._refresh_all_routes())

    async def sync_participant(self, participant: Any) -> None:
        payload = self._normalize_participant(participant)
        participant_id = payload.get("participant_id")
        if not participant_id:
            return

        current = self.participants.get(participant_id, {})
        current.update(payload)
        self.participants[participant_id] = current
        await self._refresh_all_routes()

    async def remove_participant(self, participant_id: str) -> None:
        self.participants.pop(participant_id, None)
        await self._teardown_speaker(participant_id)
        await self._refresh_all_routes()

    def _on_media_connected(self, participant_id: str) -> None:
        asyncio.create_task(self.publisher.publish_media_connected(participant_id))

    def _on_media_disconnected(self, participant_id: str) -> None:
        asyncio.create_task(self._handle_media_disconnected(participant_id))

    def _on_audio_stream(self, participant_id: str, stream: rtc.AudioStream) -> None:
        asyncio.create_task(self._handle_audio_stream(participant_id, stream))

    async def _handle_media_disconnected(self, participant_id: str) -> None:
        await self.publisher.publish_media_disconnected(participant_id)
        await self._teardown_speaker(participant_id)

    async def _handle_audio_stream(self, participant_id: str, stream: rtc.AudioStream) -> None:
        if self._closed:
            return

        if participant_id in self.active_streams:
            await self._teardown_speaker(participant_id, keep_participant=True)

        self.active_streams[participant_id] = stream
        await self._ensure_speaker_runtime(participant_id)
        await self._refresh_speaker_route(participant_id)

    async def _refresh_all_routes(self) -> None:
        for speaker_id in list(self.active_streams.keys()):
            await self._refresh_speaker_route(speaker_id)

    async def _ensure_speaker_runtime(self, speaker_id: str) -> None:
        if speaker_id in self.clients or speaker_id not in self.active_streams:
            return

        target_languages = self._target_languages_for_speaker(speaker_id)
        if not target_languages:
            logger.info("No active listeners for speaker %s in room %s", speaker_id, self.room_id)
            return

        target_lang = target_languages[0]
        if len(target_languages) > 1:
            logger.warning(
                "Multiple target languages for speaker %s in room %s; using %s for current runtime",
                speaker_id,
                self.room_id,
                target_lang,
            )
            await self.publisher.publish_error(
                code="interpreter_unavailable",
                message=(
                    f"Multiple target languages active for speaker {speaker_id}; "
                    f"runtime pinned to {target_lang} until track resubscribe."
                ),
                speaker_id=speaker_id,
                target_language=target_lang,
            )

        self.speaker_targets[speaker_id] = target_lang
        audio_input = LiveKitAudioInput(
            speaker_id,
            self.active_streams[speaker_id],
            sample_rate=getattr(self.settings, "realtime_input_sample_rate", 16000),
            loop=asyncio.get_running_loop(),
        )
        audio_input.start()
        self.active_inputs[speaker_id] = audio_input

        router = OutputRouter(
            self.runtime.room,
            speaker_id,
            src_lang="auto",
            output_sample_rate=getattr(self.settings, "realtime_output_sample_rate", 24000),
        )
        self.routers[speaker_id] = router

        client = InterpreterRealtimeClient(
            api_key=self.settings.openai_api_key,
            src_lang="auto",
            tgt_lang=target_lang,
            audio_input=audio_input,
        )
        self._bind_client_callbacks(speaker_id, target_lang, client, router)
        self.clients[speaker_id] = client
        client._running = True
        self.tasks[speaker_id] = asyncio.create_task(client._run_with_retry())

    async def _refresh_speaker_route(self, speaker_id: str) -> None:
        client = self.clients.get(speaker_id)
        if client is None:
            await self._ensure_speaker_runtime(speaker_id)
            client = self.clients.get(speaker_id)
            if client is None:
                return

        current_target = self.speaker_targets.get(speaker_id)
        if current_target is None:
            return

        target_languages = self._target_languages_for_speaker(speaker_id)
        if target_languages and current_target not in target_languages:
            logger.warning(
                "Speaker %s target changed from %s to %s; keeping existing runtime until media reconnect",
                speaker_id,
                current_target,
                target_languages[0],
            )

        desired_listeners = self._listener_ids_for_target(speaker_id, current_target)
        router = self.routers.get(speaker_id)
        if router is None:
            return

        current_listeners = set(router.listener_languages.keys())
        for listener_id in current_listeners - desired_listeners:
            await router.remove_listener(listener_id)
        for listener_id in desired_listeners - current_listeners:
            await router.ensure_listener(listener_id, current_target)

    async def _teardown_speaker(
        self,
        speaker_id: str,
        *,
        keep_participant: bool = True,
    ) -> None:
        client = self.clients.pop(speaker_id, None)
        if client is not None:
            client._running = False

        task = self.tasks.pop(speaker_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Interpreter task cleanup failed for %s", speaker_id)

        audio_input = self.active_inputs.pop(speaker_id, None)
        if audio_input is not None:
            audio_input.stop()

        router = self.routers.pop(speaker_id, None)
        if router is not None:
            await router.shutdown()

        self.active_streams.pop(speaker_id, None)
        self.speaker_targets.pop(speaker_id, None)
        self.transcript_state.pop(speaker_id, None)
        if not keep_participant:
            self.participants.pop(speaker_id, None)

    def _bind_client_callbacks(
        self,
        speaker_id: str,
        target_lang: str,
        client: InterpreterRealtimeClient,
        router: OutputRouter,
    ) -> None:
        def on_transcript_complete(text: str) -> None:
            transcript_id = f"seg_{uuid.uuid4().hex[:12]}"
            self.transcript_state[speaker_id] = {
                "transcript_id": transcript_id,
                "source_text": text,
                "translated_text": "",
                "started_at": time.monotonic(),
                "src_lang": self._effective_src_lang(speaker_id, client),
            }

        def on_text_delta(delta: str) -> None:
            state = self.transcript_state.get(speaker_id)
            if not state:
                return
            state["translated_text"] = f"{state['translated_text']}{delta}"
            asyncio.create_task(self._publish_partial(speaker_id))

        def on_text_done(text: str) -> None:
            state = self.transcript_state.get(speaker_id)
            if state is None:
                state = {
                    "transcript_id": f"seg_{uuid.uuid4().hex[:12]}",
                    "source_text": "",
                    "translated_text": text,
                    "started_at": time.monotonic(),
                    "src_lang": self._effective_src_lang(speaker_id, client),
                }
                self.transcript_state[speaker_id] = state
            else:
                state["translated_text"] = text

            asyncio.create_task(self._publish_final(speaker_id))

        def on_audio_delta(encoded: str) -> None:
            asyncio.create_task(router.capture_base64_audio(target_lang, encoded))

        def on_audio_done() -> None:
            asyncio.create_task(router.flush(target_lang))

        def on_status_change(status: str) -> None:
            if status == "capturing":
                router.clear_queues()
            asyncio.create_task(
                self.publisher.publish_status(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    status=status,
                )
            )

        def on_error(err: Dict[str, Any]) -> None:
            message = err.get("message") or err.get("type") or "Interpreter runtime error"
            asyncio.create_task(
                self.publisher.publish_error(
                    code="interpreter_unavailable",
                    message=message,
                    speaker_id=speaker_id,
                    target_language=target_lang,
                )
            )
            asyncio.create_task(
                self.publisher.publish_status(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    status="error",
                    message=message,
                )
            )

        client.on_transcript_complete = on_transcript_complete
        client.on_text_delta = on_text_delta
        client.on_text_done = on_text_done
        client.on_audio_delta = on_audio_delta
        client.on_audio_done = on_audio_done
        client.on_status_change = on_status_change
        client.on_error = on_error

    async def _publish_partial(self, speaker_id: str) -> None:
        state = self.transcript_state.get(speaker_id)
        target_lang = self.speaker_targets.get(speaker_id)
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None:
            return

        for listener_id in sorted(router.listener_ids_for_language(target_lang)):
            await self.publisher.publish_transcript_partial(
                transcript_id=state["transcript_id"],
                speaker_id=speaker_id,
                speaker_name=self._speaker_name(speaker_id),
                src_lang=state["src_lang"],
                target_id=listener_id,
                target_lang=target_lang,
                source_text=state["source_text"],
                translated_text=state["translated_text"],
                audio_track_name=router.audio_track_name(listener_id),
            )

    async def _publish_final(self, speaker_id: str) -> None:
        state = self.transcript_state.get(speaker_id)
        target_lang = self.speaker_targets.get(speaker_id)
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None:
            return

        latency_ms = int(max(0.0, time.monotonic() - state["started_at"]) * 1000)
        for listener_id in sorted(router.listener_ids_for_language(target_lang)):
            await self.publisher.publish_transcript_final(
                transcript_id=state["transcript_id"],
                speaker_id=speaker_id,
                speaker_name=self._speaker_name(speaker_id),
                src_lang=state["src_lang"],
                target_id=listener_id,
                target_lang=target_lang,
                source_text=state["source_text"],
                translated_text=state["translated_text"],
                audio_track_name=router.audio_track_name(listener_id),
                latency_ms=latency_ms,
            )

        self.transcript_state.pop(speaker_id, None)

    def _target_languages_for_speaker(self, speaker_id: str) -> list[str]:
        speaker = self.participants.get(speaker_id, {})
        speaker_lang = speaker.get("language")
        targets = {
            payload.get("language")
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id and self._is_active_participant(payload)
        }
        return sorted(
            target
            for target in targets
            if target and target != "auto" and target != speaker_lang
        )

    def _listener_ids_for_target(self, speaker_id: str, target_lang: str) -> Set[str]:
        return {
            participant_id
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id
            and self._is_active_participant(payload)
            and payload.get("language") == target_lang
        }

    def _effective_src_lang(self, speaker_id: str, client: InterpreterRealtimeClient) -> str:
        detected = getattr(client, "_last_detected_src", None)
        if detected:
            return detected
        participant_lang = self.participants.get(speaker_id, {}).get("language")
        if participant_lang and participant_lang != "auto":
            return participant_lang
        if client.src_lang != "auto":
            return client.src_lang
        return "auto"

    def _speaker_name(self, speaker_id: str) -> str:
        return self.participants.get(speaker_id, {}).get("display_name", speaker_id)

    def _normalize_participant(self, participant: Any) -> Dict[str, Any]:
        if hasattr(participant, "model_dump"):
            payload = participant.model_dump()
        elif isinstance(participant, dict):
            payload = dict(participant)
        else:
            payload = dict(vars(participant))

        payload.setdefault("status", "connected")
        payload.setdefault("language", "auto")
        payload.setdefault("display_name", payload.get("participant_id", "unknown"))
        return payload

    def _is_active_participant(self, payload: Dict[str, Any]) -> bool:
        return payload.get("status") != "disconnected" and payload.get("left_at") is None
