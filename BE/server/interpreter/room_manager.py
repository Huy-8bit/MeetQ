from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set

import livekit.rtc as rtc

from server.config import Settings
from server.interpreter.audio_input import LiveKitAudioInput
from server.interpreter.event_publisher import RedisEventPublisher
from server.interpreter.interpreter_client import InterpreterRealtimeClient
from server.interpreter.livekit_runtime import LiveKitRuntime
from server.interpreter.output_router import OutputRouter

logger = logging.getLogger(__name__)


_SUPPORTED_LANGS = {"vi", "en", "ja"}


@dataclass(frozen=True)
class _RoutingPlan:
    src_lang: str
    tgt_lang: str
    listener_ids: frozenset[str]


@dataclass(frozen=True)
class _RoutingResolution:
    plan: Optional[_RoutingPlan]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_targets: tuple[str, ...] = ()


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
        self.speaker_sources: Dict[str, str] = {}
        self.speaker_targets: Dict[str, str] = {}
        self.transcript_state: Dict[str, Dict[str, Any]] = {}
        self.route_failures: Dict[str, tuple[Any, ...]] = {}
        self._closed = False

    async def start(self) -> None:
        await self.runtime.connect()

    async def stop(self) -> None:
        self._closed = True
        for speaker_id in list(self.active_streams.keys()):
            await self._teardown_speaker(speaker_id, keep_participant=True, drop_stream=True)
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
        await self._teardown_speaker(participant_id, keep_participant=False, drop_stream=True)
        await self._refresh_all_routes()

    def _on_media_connected(self, participant_id: str) -> None:
        asyncio.create_task(self.publisher.publish_media_connected(participant_id))

    def _on_media_disconnected(self, participant_id: str) -> None:
        asyncio.create_task(self._handle_media_disconnected(participant_id))

    def _on_audio_stream(self, participant_id: str, stream: rtc.AudioStream) -> None:
        asyncio.create_task(self._handle_audio_stream(participant_id, stream))

    async def _handle_media_disconnected(self, participant_id: str) -> None:
        await self.publisher.publish_media_disconnected(participant_id)
        await self._teardown_speaker(participant_id, keep_participant=True, drop_stream=True)

    async def _handle_audio_stream(self, participant_id: str, stream: rtc.AudioStream) -> None:
        if self._closed:
            return

        if participant_id in self.active_streams:
            await self._teardown_speaker(participant_id, keep_participant=True, drop_stream=True)

        self.active_streams[participant_id] = stream
        await self._reconcile_speaker(participant_id)

    async def _refresh_all_routes(self) -> None:
        for speaker_id in list(self.active_streams.keys()):
            await self._reconcile_speaker(speaker_id)

    async def _reconcile_speaker(self, speaker_id: str) -> None:
        if self._closed or speaker_id not in self.active_streams:
            return

        resolution = self._build_routing_resolution(speaker_id)
        if resolution.error_code is not None:
            await self._publish_route_failure(
                speaker_id=speaker_id,
                error_code=resolution.error_code,
                message=resolution.error_message or "Interpreter routing failed.",
                target_languages=resolution.error_targets,
            )
            await self._teardown_speaker(speaker_id, keep_participant=True, drop_stream=False)
            return

        self.route_failures.pop(speaker_id, None)
        plan = resolution.plan
        if plan is None:
            await self._teardown_speaker(speaker_id, keep_participant=True, drop_stream=False)
            return

        current_src = self.speaker_sources.get(speaker_id)
        current_tgt = self.speaker_targets.get(speaker_id)
        if current_src != plan.src_lang or current_tgt != plan.tgt_lang:
            await self._reconfigure_speaker_runtime(
                speaker_id=speaker_id,
                plan=plan,
                current_src=current_src,
                current_tgt=current_tgt,
            )
        else:
            await self._ensure_speaker_runtime(speaker_id, plan)
        await self._sync_runtime_listeners(speaker_id, plan)

    def _build_routing_resolution(self, speaker_id: str) -> _RoutingResolution:
        speaker = self.participants.get(speaker_id)
        if speaker is None or not self._is_active_participant(speaker):
            return _RoutingResolution(plan=None)

        speaker_lang = speaker.get("language")
        if speaker_lang not in _SUPPORTED_LANGS:
            target_languages = tuple(sorted(self._listener_target_languages(speaker_id)))
            return _RoutingResolution(
                plan=None,
                error_code="invalid_language",
                error_message=(
                    f"Speaker {speaker_id} does not have a concrete meeting language. "
                    "Interpreter runtime requires explicit vi/en/ja selection."
                ),
                error_targets=target_languages,
            )

        target_languages = sorted(self._listener_target_languages(speaker_id))
        if not target_languages:
            return _RoutingResolution(plan=None)

        if len(target_languages) > 1:
            return _RoutingResolution(
                plan=None,
                error_code="interpreter_unavailable",
                error_message=(
                    f"Speaker {speaker_id} currently has multiple listener target languages "
                    f"({', '.join(target_languages)}). Runtime rebuild is required per target."
                ),
                error_targets=tuple(target_languages),
            )

        tgt_lang = target_languages[0]
        listener_ids = frozenset(self._listener_ids_for_target(speaker_id, tgt_lang))
        if not listener_ids:
            return _RoutingResolution(plan=None)

        return _RoutingResolution(
            plan=_RoutingPlan(
                src_lang=speaker_lang,
                tgt_lang=tgt_lang,
                listener_ids=listener_ids,
            )
        )

    async def _ensure_speaker_runtime(self, speaker_id: str, plan: _RoutingPlan) -> None:
        if speaker_id in self.clients:
            return

        stream = self.active_streams.get(speaker_id)
        if stream is None:
            return

        audio_input = LiveKitAudioInput(
            speaker_id,
            stream,
            sample_rate=getattr(self.settings, "realtime_input_sample_rate", 16000),
            loop=asyncio.get_running_loop(),
        )
        self.active_inputs[speaker_id] = audio_input

        def on_track_failure(listener_id: str, target_lang: str, message: str) -> None:
            asyncio.create_task(
                self._publish_audio_track_failure(
                    speaker_id=speaker_id,
                    listener_id=listener_id,
                    target_lang=target_lang,
                    message=message,
                )
            )

        router = OutputRouter(
            self.runtime.room,
            speaker_id,
            src_lang=plan.src_lang,
            output_sample_rate=getattr(self.settings, "realtime_output_sample_rate", 24000),
            on_track_failure=on_track_failure,
        )
        self.routers[speaker_id] = router

        for listener_id in sorted(plan.listener_ids):
            await router.ensure_listener(listener_id, plan.tgt_lang)

        client = InterpreterRealtimeClient(
            api_key=self.settings.openai_api_key,
            src_lang=plan.src_lang,
            tgt_lang=plan.tgt_lang,
            audio_input=audio_input,
        )
        self._bind_client_callbacks(
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            client=client,
            router=router,
        )

        self.clients[speaker_id] = client
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        client._running = True
        self.tasks[speaker_id] = asyncio.create_task(client._run_with_retry())

    async def _reconfigure_speaker_runtime(
        self,
        *,
        speaker_id: str,
        plan: _RoutingPlan,
        current_src: Optional[str],
        current_tgt: Optional[str],
    ) -> None:
        client = self.clients.get(speaker_id)
        if client is None:
            await self._ensure_speaker_runtime(speaker_id, plan)
            return

        logger.info(
            "Reconfiguring interpreter runtime for %s in room %s: %s -> %s",
            speaker_id,
            self.room_id,
            f"{current_src}->{current_tgt}",
            f"{plan.src_lang}->{plan.tgt_lang}",
        )

        if client._ws is not None and client._assistant_speaking:
            try:
                await client._cancel_response(client._ws)
            except Exception:
                logger.exception("Failed to cancel in-flight interpreter response for %s", speaker_id)

        self.transcript_state.pop(speaker_id, None)

        router = self.routers.pop(speaker_id, None)
        if router is not None:
            await router.shutdown()

        def on_track_failure(listener_id: str, target_lang: str, message: str) -> None:
            asyncio.create_task(
                self._publish_audio_track_failure(
                    speaker_id=speaker_id,
                    listener_id=listener_id,
                    target_lang=target_lang,
                    message=message,
                )
            )

        router = OutputRouter(
            self.runtime.room,
            speaker_id,
            src_lang=plan.src_lang,
            output_sample_rate=getattr(self.settings, "realtime_output_sample_rate", 24000),
            on_track_failure=on_track_failure,
        )
        self.routers[speaker_id] = router

        for listener_id in sorted(plan.listener_ids):
            await router.ensure_listener(listener_id, plan.tgt_lang)

        self._bind_client_callbacks(
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            client=client,
            router=router,
        )
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        await client.update_routing(plan.src_lang, plan.tgt_lang)

    async def _sync_runtime_listeners(self, speaker_id: str, plan: _RoutingPlan) -> None:
        router = self.routers.get(speaker_id)
        if router is None:
            return

        current_listeners = set(router.listener_languages.keys())
        desired_listeners = set(plan.listener_ids)

        for listener_id in current_listeners - desired_listeners:
            await router.remove_listener(listener_id)
        for listener_id in desired_listeners:
            if listener_id not in current_listeners or router.audio_track_name(listener_id) is None:
                await router.ensure_listener(listener_id, plan.tgt_lang)

    async def _publish_route_failure(
        self,
        *,
        speaker_id: str,
        error_code: str,
        message: str,
        target_languages: tuple[str, ...],
    ) -> None:
        failure_key = (error_code, message, target_languages)
        if self.route_failures.get(speaker_id) == failure_key:
            return

        self.route_failures[speaker_id] = failure_key
        logger.warning("Interpreter routing failure for %s in room %s: %s", speaker_id, self.room_id, message)

        await self.publisher.publish_error(
            code=error_code,
            message=message,
            speaker_id=speaker_id,
        )
        for target_lang in target_languages:
            await self.publisher.publish_status(
                speaker_id=speaker_id,
                target_lang=target_lang,
                status="error",
                message=message,
            )

    async def _publish_audio_track_failure(
        self,
        *,
        speaker_id: str,
        listener_id: str,
        target_lang: str,
        message: str,
    ) -> None:
        full_message = (
            f"Interpreter audio track failure for listener {listener_id}: {message}"
        )
        await self.publisher.publish_error(
            code="interpreter_unavailable",
            message=full_message,
            speaker_id=speaker_id,
            target_language=target_lang,
        )
        await self.publisher.publish_status(
            speaker_id=speaker_id,
            target_lang=target_lang,
            status="error",
            message=full_message,
        )

    async def _teardown_speaker(
        self,
        speaker_id: str,
        *,
        keep_participant: bool = True,
        drop_stream: bool = True,
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
            audio_input.stop(close_stream=drop_stream)

        router = self.routers.pop(speaker_id, None)
        if router is not None:
            await router.shutdown()

        self.speaker_sources.pop(speaker_id, None)
        self.speaker_targets.pop(speaker_id, None)
        self.transcript_state.pop(speaker_id, None)
        if drop_stream:
            self.active_streams.pop(speaker_id, None)
        if not keep_participant:
            self.participants.pop(speaker_id, None)
            self.route_failures.pop(speaker_id, None)

    def _bind_client_callbacks(
        self,
        *,
        speaker_id: str,
        src_lang: str,
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
                "src_lang": src_lang,
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
                    "src_lang": src_lang,
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

    def _listener_target_languages(self, speaker_id: str) -> Set[str]:
        speaker_lang = self.participants.get(speaker_id, {}).get("language")
        return {
            payload.get("language")
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id
            and self._is_active_participant(payload)
            and payload.get("language") in _SUPPORTED_LANGS
            and payload.get("language") != speaker_lang
        }

    def _listener_ids_for_target(self, speaker_id: str, target_lang: str) -> Set[str]:
        return {
            participant_id
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id
            and self._is_active_participant(payload)
            and payload.get("language") == target_lang
        }

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
        payload.setdefault("display_name", payload.get("participant_id", "unknown"))
        return payload

    def _is_active_participant(self, payload: Dict[str, Any]) -> bool:
        return payload.get("status") != "disconnected" and payload.get("left_at") is None
