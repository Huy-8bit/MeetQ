from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Set

import livekit.rtc as rtc

from server.config import Settings
from server.interpreter.audio_input import LiveKitAudioInput
from server.interpreter.event_publisher import RedisEventPublisher
from server.interpreter.interpreter_client import InterpreterRealtimeClient
from server.interpreter.livekit_runtime import LiveKitRuntime
from server.interpreter.meeting_config import (
    INTERPRETER_INPUT_QUEUE_MAXSIZE,
    INTERPRETER_INPUT_WARMUP_CHUNKS,
)
from server.interpreter.output_router import OutputRouter
from server.meeting_modes import (
    BRSE_PARTICIPANT_ID,
    DEFAULT_ROOM_MEETING_LANGUAGES,
    SUPPORTED_MEETING_LANGUAGES,
    build_relay_language_map,
    is_active_human_participant,
    relay_target_language,
)

logger = logging.getLogger(__name__)


_SUPPORTED_LANGS = set(SUPPORTED_MEETING_LANGUAGES)
_SUPPORTED_LANGS_MESSAGE = ", ".join(SUPPORTED_MEETING_LANGUAGES)
_INPUT_QUEUE_MAXSIZE = INTERPRETER_INPUT_QUEUE_MAXSIZE
_INPUT_WARMUP_CHUNKS = INTERPRETER_INPUT_WARMUP_CHUNKS


@dataclass(frozen=True)
class _RoutingPlan:
    src_lang: str
    tgt_lang: str
    audience_ids: frozenset[str]


@dataclass(frozen=True)
class _RoutingResolution:
    plan: Optional[_RoutingPlan]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_target_lang: Optional[str] = None


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
        self.speaker_audiences: Dict[str, frozenset[str]] = {}
        self.speaker_generations: Dict[str, int] = {}
        self.transcript_state: Dict[str, Dict[str, Any]] = {}
        self.route_failures: Dict[str, tuple[Any, ...]] = {}
        self.meeting_languages: tuple[str, str] = DEFAULT_ROOM_MEETING_LANGUAGES
        self._meeting_languages_ready = False
        self._closed = False

    async def start(self) -> None:
        await self.runtime.connect()

    async def stop(self) -> None:
        self._closed = True
        speaker_ids = set().union(
            self.active_streams,
            self.active_inputs,
            self.routers,
            self.clients,
            self.tasks,
            self.speaker_sources,
            self.speaker_targets,
            self.speaker_audiences,
            self.speaker_generations,
            self.transcript_state,
        )
        for speaker_id in list(speaker_ids):
            await self._teardown_speaker(speaker_id, keep_participant=True, drop_stream=True)
        self.participants.clear()
        self.active_streams.clear()
        self.active_inputs.clear()
        self.routers.clear()
        self.clients.clear()
        self.tasks.clear()
        self.speaker_sources.clear()
        self.speaker_targets.clear()
        self.speaker_audiences.clear()
        self.speaker_generations.clear()
        self.transcript_state.clear()
        self.route_failures.clear()
        await self.runtime.disconnect()

    def bootstrap_participants(
        self,
        participants: Iterable[Any],
        meeting_languages: Optional[Iterable[str]] = None,
    ) -> None:
        self._set_meeting_languages(meeting_languages)
        for participant in participants:
            payload = self._normalize_participant(participant)
            participant_id = payload.get("participant_id")
            if participant_id:
                self.participants[participant_id] = payload

        if self.active_streams:
            asyncio.create_task(self._refresh_all_routes())

    async def sync_room_context(self, meeting_languages: Optional[Iterable[str]]) -> None:
        if not self._set_meeting_languages(meeting_languages):
            return
        if self.active_streams:
            await self._refresh_all_routes()

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
                message=resolution.error_message or "BRSE relay routing failed.",
                target_lang=resolution.error_target_lang,
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

        self.speaker_audiences[speaker_id] = plan.audience_ids
        await self._publish_runtime_status(
            speaker_id=speaker_id,
            target_lang=plan.tgt_lang,
            status="idle",
        )

    def _build_routing_resolution(self, speaker_id: str) -> _RoutingResolution:
        speaker = self.participants.get(speaker_id)
        if speaker is None or not self._is_active_human_participant(speaker):
            return _RoutingResolution(plan=None)

        if not self._meeting_languages_ready:
            return _RoutingResolution(
                plan=None,
                error_code="missing_room_language_context",
                error_message=(
                    f"Room {self.room_id} does not have a valid meeting_languages pair yet. "
                    "BRSE relay is paused until the room-level language context is available."
                ),
            )

        speaker_lang = speaker.get("language")
        if speaker_lang not in _SUPPORTED_LANGS:
            return _RoutingResolution(
                plan=None,
                error_code="invalid_language",
                error_message=(
                    f"Speaker {speaker_id} does not have a concrete meeting language. "
                    f"BRSE relay requires an explicit platform-supported language: {_SUPPORTED_LANGS_MESSAGE}."
                ),
            )

        if speaker_lang not in self.meeting_languages:
            return _RoutingResolution(
                plan=None,
                error_code="invalid_language",
                error_message=(
                    f"Speaker {speaker_id} uses language {speaker_lang}, but room meeting_languages "
                    f"is {self.meeting_languages[0]}-{self.meeting_languages[1]}."
                ),
            )

        relay_map = build_relay_language_map(self.meeting_languages)
        target_lang = relay_target_language(speaker_lang, relay_map)
        if target_lang is None:
            return _RoutingResolution(
                plan=None,
                error_code="unsupported_bridge_language",
                error_message=(
                    f"Speaker {speaker_id} uses language {speaker_lang}, but current BRSE relay "
                    "mapping only supports deterministic room-level bridge targets."
                ),
            )

        audience_ids = frozenset(self._audience_ids_for_target(speaker_id, target_lang))
        logger.info(
            "BRSE route chosen room=%s speaker=%s speaker_language=%s target_language=%s "
            "meeting_pair=%s-%s audience_ids=%s",
            self.room_id,
            speaker_id,
            speaker_lang,
            target_lang,
            self.meeting_languages[0],
            self.meeting_languages[1],
            ",".join(sorted(audience_ids)) or "-",
        )
        return _RoutingResolution(
            plan=_RoutingPlan(
                src_lang=speaker_lang,
                tgt_lang=target_lang,
                audience_ids=audience_ids,
            )
        )

    async def _ensure_speaker_runtime(self, speaker_id: str, plan: _RoutingPlan) -> None:
        if speaker_id in self.clients:
            return

        stream = self.active_streams.get(speaker_id)
        if stream is None:
            return

        logger.info(
            "Starting BRSE relay runtime for speaker=%s room=%s route=%s->%s audience=%d",
            speaker_id,
            self.room_id,
            plan.src_lang,
            plan.tgt_lang,
            len(plan.audience_ids),
        )

        audio_input = LiveKitAudioInput(
            speaker_id,
            stream,
            sample_rate=getattr(self.settings, "realtime_input_sample_rate", 16000),
            loop=asyncio.get_running_loop(),
            queue_maxsize=_INPUT_QUEUE_MAXSIZE,
            warmup_chunks=_INPUT_WARMUP_CHUNKS,
        )
        self.active_inputs[speaker_id] = audio_input

        def on_track_failure(target_lang: str, message: str) -> None:
            asyncio.create_task(
                self._publish_audio_track_failure(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    message=message,
                )
            )

        router = OutputRouter(
            self.runtime.room,
            brse_participant_id=BRSE_PARTICIPANT_ID,
            brse_livekit_identity=self.runtime.livekit_identity,
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            output_sample_rate=getattr(self.settings, "realtime_output_sample_rate", 24000),
            on_track_failure=on_track_failure,
        )
        self.routers[speaker_id] = router
        await router.ensure_track()

        client = InterpreterRealtimeClient(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_realtime_model,
            src_lang=plan.src_lang,
            tgt_lang=plan.tgt_lang,
            meeting_languages=list(self.meeting_languages),
            audio_input=audio_input,
        )
        generation = self._next_speaker_generation(speaker_id)
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        self.speaker_audiences[speaker_id] = plan.audience_ids
        self._bind_client_callbacks(
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            generation=generation,
            client=client,
            router=router,
        )

        self.clients[speaker_id] = client
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
            "Reconfiguring BRSE relay runtime for %s in room %s: %s -> %s",
            speaker_id,
            self.room_id,
            f"{current_src}->{current_tgt}",
            f"{plan.src_lang}->{plan.tgt_lang}",
        )

        if client._ws is not None and client._assistant_speaking:
            try:
                await client._cancel_response(client._ws)
            except Exception:
                logger.exception("Failed to cancel in-flight BRSE relay response for %s", speaker_id)

        self.transcript_state.pop(speaker_id, None)

        router = self.routers.pop(speaker_id, None)
        if router is not None:
            await router.shutdown()

        def on_track_failure(target_lang: str, message: str) -> None:
            asyncio.create_task(
                self._publish_audio_track_failure(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    message=message,
                )
            )

        router = OutputRouter(
            self.runtime.room,
            brse_participant_id=BRSE_PARTICIPANT_ID,
            brse_livekit_identity=self.runtime.livekit_identity,
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            output_sample_rate=getattr(self.settings, "realtime_output_sample_rate", 24000),
            on_track_failure=on_track_failure,
        )
        self.routers[speaker_id] = router
        await router.ensure_track()

        generation = self._next_speaker_generation(speaker_id)
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        self.speaker_audiences[speaker_id] = plan.audience_ids
        self._bind_client_callbacks(
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            generation=generation,
            client=client,
            router=router,
        )
        client.meeting_languages = list(self.meeting_languages)
        await client.update_routing(plan.src_lang, plan.tgt_lang)

    async def _publish_route_failure(
        self,
        *,
        speaker_id: str,
        error_code: str,
        message: str,
        target_lang: Optional[str],
    ) -> None:
        failure_key = (error_code, message, target_lang)
        if self.route_failures.get(speaker_id) == failure_key:
            return

        self.route_failures[speaker_id] = failure_key
        logger.warning("BRSE relay routing failure for %s in room %s: %s", speaker_id, self.room_id, message)

        await self.publisher.publish_error(
            code=error_code,
            message=message,
            speaker_id=speaker_id,
            target_language=target_lang,
            brse_livekit_identity=self.runtime.livekit_identity,
        )
        if target_lang is not None:
            await self._publish_runtime_status(
                speaker_id=speaker_id,
                target_lang=target_lang,
                status="error",
                message=message,
            )

    async def _publish_audio_track_failure(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        message: str,
    ) -> None:
        full_message = f"BRSE relay audio track failure: {message}"
        await self.publisher.publish_error(
            code="interpreter_unavailable",
            message=full_message,
            speaker_id=speaker_id,
            target_language=target_lang,
            brse_livekit_identity=self.runtime.livekit_identity,
        )
        await self._publish_runtime_status(
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
                logger.exception("BRSE relay task cleanup failed for %s", speaker_id)

        audio_input = self.active_inputs.pop(speaker_id, None)
        if audio_input is not None:
            audio_input.stop(close_stream=drop_stream)

        router = self.routers.pop(speaker_id, None)
        if router is not None:
            await router.shutdown()

        self.speaker_sources.pop(speaker_id, None)
        self.speaker_targets.pop(speaker_id, None)
        self.speaker_audiences.pop(speaker_id, None)
        self.speaker_generations.pop(speaker_id, None)
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
        generation: int,
        client: InterpreterRealtimeClient,
        router: OutputRouter,
    ) -> None:
        def is_current_callback() -> bool:
            current = (
                self.speaker_generations.get(speaker_id) == generation
                and self.speaker_sources.get(speaker_id) == src_lang
                and self.speaker_targets.get(speaker_id) == target_lang
                and self.routers.get(speaker_id) is router
            )
            if not current:
                logger.debug(
                    "Dropping stale BRSE callback room=%s speaker=%s route=%s->%s generation=%s",
                    self.room_id,
                    speaker_id,
                    src_lang,
                    target_lang,
                    generation,
                )
            return current

        def on_input_transcript_delta(delta: str) -> None:
            if not delta or not is_current_callback():
                return
            state = self._ensure_transcript_state(
                speaker_id=speaker_id,
                src_lang=src_lang,
                target_lang=target_lang,
                generation=generation,
            )
            state["source_text"] = f"{state['source_text']}{delta}"
            asyncio.create_task(
                self._publish_source_partial(
                    speaker_id,
                    state["utterance_id"],
                    generation,
                )
            )

        def on_transcript_complete(text: str) -> None:
            if not is_current_callback():
                return
            state = self._ensure_transcript_state(
                speaker_id=speaker_id,
                src_lang=src_lang,
                target_lang=target_lang,
                generation=generation,
            )
            state["source_text"] = text
            if text:
                logger.info(
                    "BRSE source transcript completed room=%s speaker=%s utterance=%s "
                    "route=%s->%s chars=%d generation=%d",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    len(text),
                    generation,
                )
                asyncio.create_task(
                    self._publish_source_final(
                        speaker_id,
                        state["utterance_id"],
                        generation,
                    )
                )

        def on_text_delta(delta: str) -> None:
            if not delta or not is_current_callback():
                return
            state = self._ensure_transcript_state(
                speaker_id=speaker_id,
                src_lang=src_lang,
                target_lang=target_lang,
                generation=generation,
            )
            state["brse_text"] = f"{state['brse_text']}{delta}"
            asyncio.create_task(
                self._publish_partial(
                    speaker_id,
                    state["utterance_id"],
                    generation,
                )
            )

        def on_text_done(text: str) -> None:
            if not is_current_callback():
                return
            state = self.transcript_state.get(speaker_id)
            if (
                state is None
                or state.get("generation") != generation
                or state.get("src_lang") != src_lang
                or state.get("target_lang") != target_lang
            ):
                state = self._ensure_transcript_state(
                    speaker_id=speaker_id,
                    src_lang=src_lang,
                    target_lang=target_lang,
                    generation=generation,
                )
            final_text = text or state["brse_text"].strip()
            state["brse_text"] = final_text
            if final_text:
                asyncio.create_task(
                    self._publish_final(
                        speaker_id,
                        state["utterance_id"],
                        generation,
                    )
                )

        def on_audio_delta(encoded: str) -> None:
            if not encoded or not is_current_callback():
                return
            asyncio.create_task(
                self._capture_audio_delta(
                    speaker_id=speaker_id,
                    generation=generation,
                    router=router,
                    encoded=encoded,
                )
            )

        def on_audio_done() -> None:
            if not is_current_callback():
                return
            asyncio.create_task(
                self._flush_audio(
                    speaker_id=speaker_id,
                    generation=generation,
                    router=router,
                )
            )

        def on_status_change(status: str) -> None:
            if not is_current_callback():
                return
            if status == "capturing":
                previous = self.transcript_state.pop(speaker_id, None)
                if previous is not None:
                    logger.info(
                        "BRSE relay utterance reset room=%s speaker=%s previous_utterance=%s "
                        "route=%s->%s generation=%d",
                        self.room_id,
                        speaker_id,
                        previous.get("utterance_id"),
                        src_lang,
                        target_lang,
                        generation,
                    )
                router.clear_queue()
            asyncio.create_task(
                self._publish_runtime_status(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    status=status,
                )
            )

        def on_error(err: Dict[str, Any]) -> None:
            if not is_current_callback():
                return
            message = err.get("message") or err.get("type") or "BRSE relay runtime error"
            asyncio.create_task(
                self.publisher.publish_error(
                    code="interpreter_unavailable",
                    message=message,
                    speaker_id=speaker_id,
                    target_language=target_lang,
                    brse_livekit_identity=self.runtime.livekit_identity,
                )
            )
            asyncio.create_task(
                self._publish_runtime_status(
                    speaker_id=speaker_id,
                    target_lang=target_lang,
                    status="error",
                    message=message,
                )
            )

        client.on_input_transcript_delta = on_input_transcript_delta
        client.on_transcript_complete = on_transcript_complete
        client.on_text_delta = on_text_delta
        client.on_text_done = on_text_done
        client.on_audio_delta = on_audio_delta
        client.on_audio_done = on_audio_done
        client.on_status_change = on_status_change
        client.on_error = on_error

    async def _capture_audio_delta(
        self,
        *,
        speaker_id: str,
        generation: int,
        router: OutputRouter,
        encoded: str,
    ) -> None:
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        ok = await router.capture_base64_audio(encoded)
        if not ok:
            logger.debug(
                "BRSE relay audio delta was not captured room=%s speaker=%s generation=%d",
                self.room_id,
                speaker_id,
                generation,
            )

    async def _flush_audio(
        self,
        *,
        speaker_id: str,
        generation: int,
        router: OutputRouter,
    ) -> None:
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        await router.flush()

    async def _publish_source_partial(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not state["source_text"]:
            return

        await self.publisher.publish_source_transcript_partial(
            transcript_id=state["source_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            text=state["source_text"],
            created_at=state["created_at"],
        )

    async def _publish_source_final(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not state["source_text"]:
            return

        await self.publisher.publish_source_transcript_final(
            transcript_id=state["source_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            text=state["source_text"],
            created_at=state["created_at"],
        )

    async def _publish_partial(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        target_lang = state.get("target_lang") if state is not None else None
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None:
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return

        await self.publisher.publish_relay_transcript_partial(
            transcript_id=state["relay_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            target_lang=target_lang,
            source_text=state["source_text"],
            brse_text=state["brse_text"],
            created_at=state["created_at"],
            brse_livekit_identity=self.runtime.livekit_identity,
            audio_track_name=router.audio_track_name(),
            audience_participant_ids=sorted(self.speaker_audiences.get(speaker_id, frozenset())),
        )

    async def _publish_final(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        target_lang = state.get("target_lang") if state is not None else None
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None or not state["brse_text"]:
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return

        latency_ms = int(max(0.0, time.monotonic() - state["started_at"]) * 1000)
        logger.info(
            "BRSE relay final room=%s speaker=%s utterance=%s route=%s->%s "
            "source_chars=%d relay_chars=%d latency_ms=%d audience=%d generation=%d",
            self.room_id,
            speaker_id,
            state["utterance_id"],
            state["src_lang"],
            target_lang,
            len(state["source_text"]),
            len(state["brse_text"]),
            latency_ms,
            len(self.speaker_audiences.get(speaker_id, frozenset())),
            generation,
        )
        await self.publisher.publish_relay_transcript_final(
            transcript_id=state["relay_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            target_lang=target_lang,
            source_text=state["source_text"],
            brse_text=state["brse_text"],
            created_at=state["created_at"],
            brse_livekit_identity=self.runtime.livekit_identity,
            audio_track_name=router.audio_track_name(),
            audience_participant_ids=sorted(self.speaker_audiences.get(speaker_id, frozenset())),
            latency_ms=latency_ms,
        )

        if self.transcript_state.get(speaker_id) is state:
            self.transcript_state.pop(speaker_id, None)

    async def _publish_runtime_status(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        status: str,
        message: Optional[str] = None,
    ) -> None:
        router = self.routers.get(speaker_id)
        source_language = self.speaker_sources.get(speaker_id)
        audience_ids = sorted(self.speaker_audiences.get(speaker_id, frozenset()))
        audio_track = router.track_descriptor() if router is not None else None
        audio_track_name = None
        if audio_track is not None and audio_track.get("track_available"):
            audio_track_name = audio_track.get("track_name")

        await self.publisher.publish_status(
            speaker_id=speaker_id,
            source_language=source_language,
            target_lang=target_lang,
            status=status,
            message=message,
            brse_livekit_identity=self.runtime.livekit_identity,
            audience_participant_ids=audience_ids,
            audio_track_name=audio_track_name,
            audio_track=audio_track,
        )

    def _audience_ids_for_target(self, speaker_id: str, target_lang: str) -> Set[str]:
        return {
            participant_id
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id
            and self._is_active_human_participant(payload)
            and payload.get("language") == target_lang
        }

    def _speaker_name(self, speaker_id: str) -> str:
        return self.participants.get(speaker_id, {}).get("display_name", speaker_id)

    def _next_speaker_generation(self, speaker_id: str) -> int:
        generation = self.speaker_generations.get(speaker_id, 0) + 1
        self.speaker_generations[speaker_id] = generation
        return generation

    def _runtime_generation_matches(
        self,
        speaker_id: str,
        generation: int,
        router: OutputRouter,
    ) -> bool:
        return (
            self.speaker_generations.get(speaker_id) == generation
            and self.routers.get(speaker_id) is router
        )

    def _transcript_state_for_publish(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> Optional[Dict[str, Any]]:
        state = self.transcript_state.get(speaker_id)
        if state is None:
            return None
        if state.get("utterance_id") != utterance_id or state.get("generation") != generation:
            logger.debug(
                "Dropping stale BRSE transcript publish room=%s speaker=%s requested_utterance=%s "
                "current_utterance=%s requested_generation=%d current_generation=%s",
                self.room_id,
                speaker_id,
                utterance_id,
                state.get("utterance_id"),
                generation,
                state.get("generation"),
            )
            return None
        return state

    def _ensure_transcript_state(
        self,
        *,
        speaker_id: str,
        src_lang: str,
        target_lang: str,
        generation: int,
    ) -> Dict[str, Any]:
        state = self.transcript_state.get(speaker_id)
        if (
            state is not None
            and state.get("generation") == generation
            and state.get("src_lang") == src_lang
            and state.get("target_lang") == target_lang
        ):
            return state

        utterance_id = f"seg_{uuid.uuid4().hex[:12]}"
        state = {
            "utterance_id": utterance_id,
            "source_transcript_id": f"{utterance_id}::source",
            "relay_transcript_id": f"{utterance_id}::relay::{target_lang}",
            "source_text": "",
            "brse_text": "",
            "started_at": time.monotonic(),
            "created_at": self._now_str(),
            "src_lang": src_lang,
            "target_lang": target_lang,
            "generation": generation,
        }
        self.transcript_state[speaker_id] = state
        logger.info(
            "BRSE relay utterance opened room=%s speaker=%s utterance=%s route=%s->%s generation=%d",
            self.room_id,
            speaker_id,
            utterance_id,
            src_lang,
            target_lang,
            generation,
        )
        return state

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _normalize_participant(self, participant: Any) -> Dict[str, Any]:
        if hasattr(participant, "model_dump"):
            payload = participant.model_dump()
        elif isinstance(participant, dict):
            payload = dict(participant)
        else:
            payload = dict(vars(participant))

        payload.setdefault("status", "connected")
        payload.setdefault("display_name", payload.get("participant_id", "unknown"))
        payload.setdefault("kind", "human")
        payload.setdefault("is_virtual", False)
        return payload

    def _is_active_human_participant(self, payload: Dict[str, Any]) -> bool:
        return is_active_human_participant(payload)

    def _set_meeting_languages(self, meeting_languages: Optional[Iterable[str]]) -> bool:
        if meeting_languages is None:
            return self._mark_meeting_languages_not_ready("missing meeting_languages")

        pair = [lang for lang in meeting_languages if isinstance(lang, str)]
        if len(pair) != 2 or pair[0] == pair[1]:
            return self._mark_meeting_languages_not_ready(
                f"invalid meeting_languages={pair!r}"
            )
        if any(lang not in _SUPPORTED_LANGS for lang in pair):
            return self._mark_meeting_languages_not_ready(
                f"unsupported meeting_languages={pair!r}"
            )

        normalized = (pair[0], pair[1])
        changed = normalized != self.meeting_languages or not self._meeting_languages_ready

        self.meeting_languages = normalized
        self._meeting_languages_ready = True
        if changed:
            logger.info(
                "Room %s BRSE meeting language context set to %s-%s",
                self.room_id,
                normalized[0],
                normalized[1],
            )
        return changed

    def _mark_meeting_languages_not_ready(self, reason: str) -> bool:
        was_ready = self._meeting_languages_ready
        self._meeting_languages_ready = False
        logger.warning(
            "Room %s BRSE meeting language context unavailable: %s",
            self.room_id,
            reason,
        )
        return was_ready
