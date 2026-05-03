from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Set

import livekit.rtc as rtc

from server.config import Settings
from server.service.media.audio_input import LiveKitAudioInput
from server.service.brain_runtime.events import RedisEventPublisher
from server.brain.realtime.interpreter_client import InterpreterRealtimeClient
from server.service.media.livekit_runtime import LiveKitRuntime
from server.brain.realtime.session_config import (
    INTERPRETER_INPUT_QUEUE_MAXSIZE,
    INTERPRETER_INPUT_WARMUP_CHUNKS,
)
from server.brain.realtime.source_policy import (
    assess_source_transcript,
    source_state_is_valid_for_output,
)
from server.service.media.output_router import OutputRouter
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
_OVERLAP_FOCUS_COOLDOWN_SECONDS = 0.85


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


class _SpeakerLifecycle:
    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"
    COOLING_DOWN = "cooling_down"
    BLOCKED_DUE_TO_OVERLAP = "blocked_due_to_overlap"


@dataclass
class _SpeakerArbitrationState:
    lifecycle: str = _SpeakerLifecycle.IDLE
    changed_at: float = field(default_factory=time.monotonic)
    generation: Optional[int] = None
    blocked_by: Optional[str] = None
    blocked_since: Optional[float] = None
    last_speech_started_at: Optional[float] = None
    last_speech_stopped_at: Optional[float] = None
    last_speech_duration_ms: Optional[int] = None


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
        self.speaker_lifecycle: Dict[str, _SpeakerArbitrationState] = {}
        self.relay_focus_speaker_id: Optional[str] = None
        self.relay_focus_generation: Optional[int] = None
        self.relay_focus_started_at: Optional[float] = None
        self.relay_focus_cooldown_until: Optional[float] = None
        self.relay_focus_release_task: Optional[asyncio.Task] = None
        self.overlap_blocked_speakers: Set[str] = set()
        self.overlap_blocked_generations: Dict[str, int] = {}
        self.overlap_started_at: Dict[str, float] = {}
        self.meeting_languages: tuple[str, str] = DEFAULT_ROOM_MEETING_LANGUAGES
        self._meeting_languages_ready = False
        self._closed = False

    async def start(self) -> None:
        await self.runtime.connect()

    async def stop(self) -> None:
        self._closed = True
        self._cancel_relay_focus_release()
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
        self.speaker_lifecycle.clear()
        self.relay_focus_speaker_id = None
        self.relay_focus_generation = None
        self.relay_focus_started_at = None
        self.relay_focus_cooldown_until = None
        self.overlap_blocked_speakers.clear()
        self.overlap_blocked_generations.clear()
        self.overlap_started_at.clear()
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
        if speaker_id not in self.overlap_blocked_speakers:
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
        self._set_speaker_lifecycle(speaker_id, _SpeakerLifecycle.LISTENING)

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
        self._forget_speaker_arbitration(speaker_id)

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

    def _handle_speech_started(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        generation: int,
        router: OutputRouter,
    ) -> bool:
        if self._closed:
            return False

        if (
            self.relay_focus_speaker_id is not None
            and self.relay_focus_speaker_id not in self.clients
        ):
            self._release_relay_focus(reason="stale_focus")

        if self.relay_focus_speaker_id in (None, speaker_id):
            state = self._speaker_state(speaker_id)
            state.last_speech_duration_ms = None
            self._claim_relay_focus(
                speaker_id=speaker_id,
                generation=generation,
                reason="speech_started",
            )
            self._set_speaker_lifecycle(
                speaker_id,
                _SpeakerLifecycle.SPEAKING,
                generation=generation,
                last_speech_started_at=time.monotonic(),
            )
            self._set_input_enabled(speaker_id, True, reason="primary_relay_focus")
            return True

        self._block_speaker_due_to_overlap(
            speaker_id=speaker_id,
            target_lang=target_lang,
            generation=generation,
            router=router,
        )
        return False

    def _handle_speech_stopped(
        self,
        *,
        speaker_id: str,
        generation: int,
        duration_ms: Optional[int],
    ) -> None:
        state = self._speaker_state(speaker_id)
        state.last_speech_stopped_at = time.monotonic()
        state.last_speech_duration_ms = duration_ms
        if state.generation is None:
            state.generation = generation

        if self.overlap_blocked_generations.get(speaker_id) == generation:
            logger.info(
                "BRSE blocked speaker speech stopped room=%s speaker=%s "
                "focus=%s duration_ms=%s generation=%d",
                self.room_id,
                speaker_id,
                self.relay_focus_speaker_id,
                duration_ms if duration_ms is not None else "n/a",
                generation,
            )
            return

        if self.relay_focus_speaker_id == speaker_id:
            self._set_speaker_lifecycle(
                speaker_id,
                _SpeakerLifecycle.COOLING_DOWN,
                generation=generation,
                last_speech_stopped_at=state.last_speech_stopped_at,
            )

    def _handle_focus_status(self, *, speaker_id: str, generation: int, status: str) -> None:
        if self.relay_focus_speaker_id != speaker_id:
            return
        if status == "capturing":
            self._set_speaker_lifecycle(
                speaker_id,
                _SpeakerLifecycle.SPEAKING,
                generation=generation,
            )
        elif status in {"translating", "playing"}:
            self._set_speaker_lifecycle(
                speaker_id,
                _SpeakerLifecycle.COOLING_DOWN,
                generation=generation,
            )
        elif status == "idle":
            self._set_speaker_lifecycle(
                speaker_id,
                _SpeakerLifecycle.COOLING_DOWN,
                generation=generation,
            )
            self._schedule_relay_focus_release(speaker_id=speaker_id, generation=generation)

    def _speaker_generation_can_publish(self, *, speaker_id: str, generation: int) -> bool:
        if self.overlap_blocked_generations.get(speaker_id) == generation:
            return False
        if speaker_id in self.overlap_blocked_speakers:
            return False

        focus_speaker_id = self.relay_focus_speaker_id
        if focus_speaker_id is None:
            self._claim_relay_focus(
                speaker_id=speaker_id,
                generation=generation,
                reason="late_publish_without_speech_started",
            )
            return True
        if focus_speaker_id == speaker_id:
            self.relay_focus_generation = generation
            return True
        return False

    def _claim_relay_focus(self, *, speaker_id: str, generation: int, reason: str) -> None:
        previous = self.relay_focus_speaker_id
        if previous == speaker_id:
            self.relay_focus_generation = generation
            self._cancel_relay_focus_release()
            self.relay_focus_cooldown_until = None
            return

        self._cancel_relay_focus_release()
        self.relay_focus_speaker_id = speaker_id
        self.relay_focus_generation = generation
        self.relay_focus_started_at = time.monotonic()
        self.relay_focus_cooldown_until = None
        self._clear_overlap_block(speaker_id)
        logger.info(
            "BRSE relay focus claimed room=%s speaker=%s previous=%s "
            "generation=%d reason=%s",
            self.room_id,
            speaker_id,
            previous or "-",
            generation,
            reason,
        )

    def _block_speaker_due_to_overlap(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        generation: int,
        router: OutputRouter,
    ) -> None:
        now = time.monotonic()
        focus_speaker_id = self.relay_focus_speaker_id
        first_block = (
            speaker_id not in self.overlap_blocked_speakers
            or self.overlap_blocked_generations.get(speaker_id) != generation
        )
        self.overlap_blocked_speakers.add(speaker_id)
        self.overlap_blocked_generations[speaker_id] = generation
        self.overlap_started_at.setdefault(speaker_id, now)
        self.transcript_state.pop(speaker_id, None)
        router.clear_queue()
        self._set_speaker_lifecycle(
            speaker_id,
            _SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP,
            generation=generation,
            blocked_by=focus_speaker_id,
            blocked_since=self.overlap_started_at.get(speaker_id, now),
            last_speech_started_at=now,
        )
        self._set_input_enabled(speaker_id, False, reason="blocked_due_to_overlap")

        if not first_block:
            return

        overlap_window_ms = self._overlap_window_ms()
        logger.warning(
            "BRSE overlap detected room=%s primary=%s blocked=%s "
            "generation=%d overlap_window_ms=%s suppressed_count=%d",
            self.room_id,
            focus_speaker_id,
            speaker_id,
            generation,
            overlap_window_ms if overlap_window_ms is not None else "n/a",
            len(self.overlap_blocked_speakers),
        )
        asyncio.create_task(
            self._publish_runtime_status(
                speaker_id=speaker_id,
                target_lang=target_lang,
                status=_SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP,
                message=(
                    "BRSE relay is focused on another active speaker; "
                    "this overlapping speaker is temporarily suppressed."
                ),
            )
        )

    def _mark_blocked_turn_finished(self, speaker_id: str, generation: int) -> None:
        if self.overlap_blocked_generations.get(speaker_id) != generation:
            return
        self.overlap_blocked_generations.pop(speaker_id, None)
        logger.info(
            "BRSE blocked overlap turn finished room=%s speaker=%s focus=%s generation=%d",
            self.room_id,
            speaker_id,
            self.relay_focus_speaker_id,
            generation,
        )

    def _schedule_relay_focus_release(self, *, speaker_id: str, generation: int) -> None:
        if self.relay_focus_speaker_id != speaker_id:
            return
        self._cancel_relay_focus_release()
        cooldown_until = time.monotonic() + _OVERLAP_FOCUS_COOLDOWN_SECONDS
        self.relay_focus_cooldown_until = cooldown_until
        self.relay_focus_release_task = asyncio.create_task(
            self._release_relay_focus_after_cooldown(
                speaker_id=speaker_id,
                generation=generation,
                cooldown_until=cooldown_until,
            )
        )

    async def _release_relay_focus_after_cooldown(
        self,
        *,
        speaker_id: str,
        generation: int,
        cooldown_until: float,
    ) -> None:
        try:
            await asyncio.sleep(_OVERLAP_FOCUS_COOLDOWN_SECONDS)
        except asyncio.CancelledError:
            return
        if (
            self.relay_focus_speaker_id != speaker_id
            or self.relay_focus_generation != generation
            or self.relay_focus_cooldown_until != cooldown_until
        ):
            return
        self._release_relay_focus(reason="cooldown_elapsed")

    def _release_relay_focus(self, *, reason: str) -> None:
        focus_speaker_id = self.relay_focus_speaker_id
        if focus_speaker_id is None:
            return

        started_at = self.relay_focus_started_at
        focus_duration_ms = None
        if started_at is not None:
            focus_duration_ms = int(max(0.0, time.monotonic() - started_at) * 1000)

        blocked_speaker_ids = sorted(self.overlap_blocked_speakers)
        self._cancel_relay_focus_release()
        self.relay_focus_speaker_id = None
        self.relay_focus_generation = None
        self.relay_focus_started_at = None
        self.relay_focus_cooldown_until = None

        if focus_speaker_id in self.active_inputs:
            self._set_speaker_lifecycle(focus_speaker_id, _SpeakerLifecycle.LISTENING)
        else:
            self._set_speaker_lifecycle(focus_speaker_id, _SpeakerLifecycle.IDLE)

        for blocked_speaker_id in blocked_speaker_ids:
            self._clear_overlap_block(blocked_speaker_id)
            if blocked_speaker_id in self.active_inputs:
                self._set_speaker_lifecycle(blocked_speaker_id, _SpeakerLifecycle.LISTENING)
                self._set_input_enabled(
                    blocked_speaker_id,
                    True,
                    reason="relay_focus_released",
                )
            else:
                self._set_speaker_lifecycle(blocked_speaker_id, _SpeakerLifecycle.IDLE)

            target_lang = self.speaker_targets.get(blocked_speaker_id)
            if target_lang is not None and not self._closed:
                asyncio.create_task(
                    self._publish_runtime_status(
                        speaker_id=blocked_speaker_id,
                        target_lang=target_lang,
                        status="idle",
                        message="Overlap suppression cleared; speaker is eligible for relay again.",
                    )
                )

        logger.info(
            "BRSE relay focus released room=%s speaker=%s reason=%s "
            "focus_duration_ms=%s suppressed_speakers=%d",
            self.room_id,
            focus_speaker_id,
            reason,
            focus_duration_ms if focus_duration_ms is not None else "n/a",
            len(blocked_speaker_ids),
        )

    def _cancel_relay_focus_release(self) -> None:
        task = self.relay_focus_release_task
        self.relay_focus_release_task = None
        if task is None or task.done():
            return
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if task is not current_task:
            task.cancel()

    def _forget_speaker_arbitration(self, speaker_id: str) -> None:
        if self.relay_focus_speaker_id == speaker_id:
            self._release_relay_focus(reason="speaker_teardown")
        self._clear_overlap_block(speaker_id)
        self.speaker_lifecycle.pop(speaker_id, None)

    def _clear_overlap_block(self, speaker_id: str) -> None:
        self.overlap_blocked_speakers.discard(speaker_id)
        self.overlap_blocked_generations.pop(speaker_id, None)
        self.overlap_started_at.pop(speaker_id, None)

    def _speaker_state(self, speaker_id: str) -> _SpeakerArbitrationState:
        return self.speaker_lifecycle.setdefault(speaker_id, _SpeakerArbitrationState())

    def _set_speaker_lifecycle(
        self,
        speaker_id: str,
        lifecycle: str,
        *,
        generation: Optional[int] = None,
        blocked_by: Optional[str] = None,
        blocked_since: Optional[float] = None,
        last_speech_started_at: Optional[float] = None,
        last_speech_stopped_at: Optional[float] = None,
    ) -> None:
        state = self._speaker_state(speaker_id)
        previous = state.lifecycle
        state.lifecycle = lifecycle
        state.changed_at = time.monotonic()
        if generation is not None:
            state.generation = generation
        state.blocked_by = blocked_by
        if blocked_since is not None:
            state.blocked_since = blocked_since
        elif lifecycle != _SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP:
            state.blocked_since = None
        if last_speech_started_at is not None:
            state.last_speech_started_at = last_speech_started_at
        if last_speech_stopped_at is not None:
            state.last_speech_stopped_at = last_speech_stopped_at

        if previous != lifecycle:
            logger.info(
                "BRSE speaker lifecycle room=%s speaker=%s %s->%s "
                "focus=%s generation=%s blocked_by=%s",
                self.room_id,
                speaker_id,
                previous,
                lifecycle,
                self.relay_focus_speaker_id,
                state.generation,
                state.blocked_by,
            )

    def _speaker_lifecycle_name(self, speaker_id: str) -> str:
        state = self.speaker_lifecycle.get(speaker_id)
        if state is not None:
            return state.lifecycle
        if speaker_id in self.active_inputs:
            return _SpeakerLifecycle.LISTENING
        return _SpeakerLifecycle.IDLE

    def _set_input_enabled(self, speaker_id: str, enabled: bool, *, reason: str) -> None:
        audio_input = self.active_inputs.get(speaker_id)
        if audio_input is None:
            return
        setter = getattr(audio_input, "set_input_enabled", None)
        if callable(setter):
            setter(enabled, reason=reason)

    def _overlap_window_ms(self) -> Optional[int]:
        if self.relay_focus_started_at is None:
            return None
        return int(max(0.0, time.monotonic() - self.relay_focus_started_at) * 1000)

    def _relay_focus_payload(self, speaker_id: str) -> Dict[str, Any]:
        cooldown_ms = None
        if self.relay_focus_cooldown_until is not None:
            cooldown_ms = int(max(0.0, self.relay_focus_cooldown_until - time.monotonic()) * 1000)
        return {
            "policy": "single_primary_speaker_serialized",
            "active_speaker_id": self.relay_focus_speaker_id,
            "active_generation": self.relay_focus_generation,
            "speaker_state": self._speaker_lifecycle_name(speaker_id),
            "is_active_relay_speaker": self.relay_focus_speaker_id == speaker_id,
            "blocked_speaker_ids": sorted(self.overlap_blocked_speakers),
            "suppressed_speaker_count": len(self.overlap_blocked_speakers),
            "cooldown_ms": cooldown_ms,
        }

    def _overlap_payload(self, speaker_id: str) -> Dict[str, Any]:
        blocked_speaker_ids = sorted(self.overlap_blocked_speakers)
        state = self.speaker_lifecycle.get(speaker_id)
        overlap_window_ms = None
        if speaker_id in self.overlap_blocked_speakers:
            overlap_window_ms = self._overlap_window_ms()
        return {
            "detected": bool(blocked_speaker_ids),
            "speaker_blocked": speaker_id in self.overlap_blocked_speakers,
            "primary_speaker_id": self.relay_focus_speaker_id,
            "blocked_by": state.blocked_by if state is not None else None,
            "blocked_speaker_ids": blocked_speaker_ids,
            "suppressed_speaker_count": len(blocked_speaker_ids),
            "overlap_window_ms": overlap_window_ms,
        }

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

        def is_publishable_callback(kind: str) -> bool:
            if not is_current_callback():
                return False
            publishable = self._speaker_generation_can_publish(
                speaker_id=speaker_id,
                generation=generation,
            )
            if not publishable:
                logger.debug(
                    "Suppressing BRSE %s callback due to room relay focus room=%s "
                    "speaker=%s focus=%s state=%s generation=%d",
                    kind,
                    self.room_id,
                    speaker_id,
                    self.relay_focus_speaker_id,
                    self._speaker_lifecycle_name(speaker_id),
                    generation,
                )
            return publishable

        def relay_state_for_response(kind: str) -> Optional[Dict[str, Any]]:
            if not is_publishable_callback(kind):
                return None
            state = self.transcript_state.get(speaker_id)
            if state is None:
                logger.debug(
                    "Suppressing BRSE %s without source transcript state room=%s speaker=%s generation=%d",
                    kind,
                    self.room_id,
                    speaker_id,
                    generation,
                )
                router.clear_queue()
                return None
            if not self._source_state_can_relay(
                speaker_id=speaker_id,
                state=state,
                generation=generation,
                src_lang=src_lang,
                target_lang=target_lang,
                response_source_id=client.current_response_source_id(),
                kind=kind,
            ):
                router.clear_queue()
                return None
            return state

        def on_input_audio_committed(item_id: Optional[str]) -> None:
            if not is_publishable_callback("source_commit"):
                return
            state = self._ensure_transcript_state(
                speaker_id=speaker_id,
                src_lang=src_lang,
                target_lang=target_lang,
                generation=generation,
            )
            state["source_item_id"] = item_id
            state["source_committed"] = True
            state["source_final"] = False
            state["source_valid"] = False
            state["source_rejected_reason"] = None
            state["source_signal"] = {}
            state["source_text"] = ""
            state["brse_text"] = ""
            state["speech_duration_ms"] = self._speaker_state(speaker_id).last_speech_duration_ms

        def on_input_transcript_delta(delta: str) -> None:
            if not delta or not is_publishable_callback("source_partial"):
                return
            state = self.transcript_state.get(speaker_id)
            if state is None or not state.get("source_committed"):
                logger.debug(
                    "Dropping BRSE source partial before committed input room=%s speaker=%s generation=%d",
                    self.room_id,
                    speaker_id,
                    generation,
                )
                return
            state["source_text"] = f"{state['source_text']}{delta}"
            asyncio.create_task(
                self._publish_source_partial(
                    speaker_id,
                    state["utterance_id"],
                    generation,
                )
            )

        def on_transcript_complete(text: str) -> None:
            if not is_publishable_callback("source_final"):
                return
            state = self.transcript_state.get(speaker_id)
            if state is None or not state.get("source_committed"):
                logger.warning(
                    "Dropping BRSE source final without committed source room=%s speaker=%s "
                    "route=%s->%s generation=%d",
                    self.room_id,
                    speaker_id,
                    src_lang,
                    target_lang,
                    generation,
                )
                return
            if state.get("speech_duration_ms") is None:
                state["speech_duration_ms"] = self._speaker_state(speaker_id).last_speech_duration_ms
            source_ok, reason, normalized_text, signal = self._assess_source_transcript(
                text,
                duration_ms=state.get("speech_duration_ms"),
                final=True,
            )
            state["source_text"] = normalized_text
            state["source_final"] = True
            state["source_valid"] = source_ok
            state["source_rejected_reason"] = None if source_ok else reason
            state["source_signal"] = signal
            if source_ok:
                logger.info(
                    "BRSE source transcript completed room=%s speaker=%s utterance=%s "
                    "route=%s->%s chars=%d tokens=%s duration_ms=%s generation=%d",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    len(normalized_text),
                    signal.get("meaningful_tokens"),
                    state.get("speech_duration_ms"),
                    generation,
                )
                asyncio.create_task(
                    self._publish_source_final(
                        speaker_id,
                        state["utterance_id"],
                        generation,
                    )
                )
            else:
                router.clear_queue()
                logger.info(
                    "Suppressing BRSE source transcript room=%s speaker=%s utterance=%s "
                    "route=%s->%s reason=%s signal=%s generation=%d text=%r",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    reason,
                    signal,
                    generation,
                    normalized_text,
                )

        def approve_transcript_for_relay(text: str, item_id: Optional[str]) -> Optional[str]:
            if not is_publishable_callback("source_approval"):
                return None
            state = self.transcript_state.get(speaker_id)
            if state is None:
                return None
            state_item_id = state.get("source_item_id")
            if item_id is not None and state_item_id is not None and item_id != state_item_id:
                logger.debug(
                    "Rejecting BRSE source approval due to item mismatch room=%s speaker=%s "
                    "item_id=%s state_item_id=%s generation=%d",
                    self.room_id,
                    speaker_id,
                    item_id,
                    state_item_id,
                    generation,
                )
                return None
            if not self._source_state_can_relay(
                speaker_id=speaker_id,
                state=state,
                generation=generation,
                src_lang=src_lang,
                target_lang=target_lang,
                response_source_id=state.get("utterance_id"),
                kind="source_approval",
            ):
                return None
            return str(state["utterance_id"])

        def on_text_delta(delta: str) -> None:
            if not delta:
                return
            state = relay_state_for_response("relay_partial")
            if state is None:
                return
            state["brse_text"] = f"{state['brse_text']}{delta}"
            asyncio.create_task(
                self._publish_partial(
                    speaker_id,
                    state["utterance_id"],
                    generation,
                )
            )

        def on_text_done(text: str) -> None:
            state = relay_state_for_response("relay_final")
            if state is None:
                return
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
            if not encoded:
                return
            state = relay_state_for_response("audio_delta")
            if state is None:
                return
            asyncio.create_task(
                self._capture_audio_delta(
                    speaker_id=speaker_id,
                    utterance_id=state["utterance_id"],
                    generation=generation,
                    router=router,
                    encoded=encoded,
                )
            )

        def on_audio_done() -> None:
            state = relay_state_for_response("audio_done")
            if state is None:
                return
            asyncio.create_task(
                self._flush_audio(
                    speaker_id=speaker_id,
                    utterance_id=state["utterance_id"],
                    generation=generation,
                    router=router,
                )
            )

        def on_speech_started() -> None:
            if not is_current_callback():
                return
            self._handle_speech_started(
                speaker_id=speaker_id,
                target_lang=target_lang,
                generation=generation,
                router=router,
            )

        def on_speech_stopped(duration_ms: Optional[int]) -> None:
            if not is_current_callback():
                return
            self._handle_speech_stopped(
                speaker_id=speaker_id,
                generation=generation,
                duration_ms=duration_ms,
            )

        def on_status_change(status: str) -> None:
            if not is_current_callback():
                return
            if status == "capturing":
                if not self._speaker_generation_can_publish(
                    speaker_id=speaker_id,
                    generation=generation,
                ):
                    return
                self._handle_focus_status(
                    speaker_id=speaker_id,
                    generation=generation,
                    status=status,
                )
            elif not self._speaker_generation_can_publish(
                speaker_id=speaker_id,
                generation=generation,
            ):
                if status == "idle":
                    self._mark_blocked_turn_finished(speaker_id, generation)
                return
            else:
                self._handle_focus_status(
                    speaker_id=speaker_id,
                    generation=generation,
                    status=status,
                )

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

        client.on_input_audio_committed = on_input_audio_committed
        client.on_input_transcript_delta = on_input_transcript_delta
        client.on_transcript_complete = on_transcript_complete
        client.approve_transcript_for_relay = approve_transcript_for_relay
        client.on_text_delta = on_text_delta
        client.on_text_done = on_text_done
        client.on_audio_delta = on_audio_delta
        client.on_audio_done = on_audio_done
        client.on_status_change = on_status_change
        client.on_speech_started = on_speech_started
        client.on_speech_stopped = on_speech_stopped
        client.on_error = on_error

    async def _capture_audio_delta(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        generation: int,
        router: OutputRouter,
        encoded: str,
    ) -> None:
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not self._source_state_is_valid_for_output(state):
            router.clear_queue()
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
        utterance_id: str,
        generation: int,
        router: OutputRouter,
    ) -> None:
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not self._source_state_is_valid_for_output(state):
            router.clear_queue()
            return
        await router.flush()

    def _source_state_can_relay(
        self,
        *,
        speaker_id: str,
        state: Dict[str, Any],
        generation: int,
        src_lang: str,
        target_lang: str,
        response_source_id: Optional[str],
        kind: str,
    ) -> bool:
        if state.get("generation") != generation:
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="generation_mismatch",
            )
        if state.get("src_lang") != src_lang or state.get("target_lang") != target_lang:
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="route_mismatch",
            )
        if self.relay_focus_speaker_id != speaker_id or self.relay_focus_generation != generation:
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="relay_focus_mismatch",
            )
        if not self._relay_route_is_still_valid(
            speaker_id=speaker_id,
            src_lang=src_lang,
            target_lang=target_lang,
        ):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="route_not_current",
            )
        if not self._source_state_is_valid_for_output(state):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason=str(state.get("source_rejected_reason") or "source_not_validated"),
            )
        if response_source_id != state.get("utterance_id"):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="response_utterance_mismatch",
                response_source_id=response_source_id,
            )
        return True

    def _source_state_is_valid_for_output(self, state: Dict[str, Any]) -> bool:
        return source_state_is_valid_for_output(state)

    def _relay_route_is_still_valid(
        self,
        *,
        speaker_id: str,
        src_lang: str,
        target_lang: str,
    ) -> bool:
        if not self._meeting_languages_ready:
            return False
        speaker = self.participants.get(speaker_id)
        if speaker is None or not self._is_active_human_participant(speaker):
            return False
        if speaker.get("language") != src_lang:
            return False
        if src_lang not in self.meeting_languages or target_lang not in self.meeting_languages:
            return False
        if src_lang == target_lang:
            return False
        relay_map = build_relay_language_map(self.meeting_languages)
        return relay_target_language(src_lang, relay_map) == target_lang

    def _log_source_gate_drop(
        self,
        *,
        speaker_id: str,
        state: Dict[str, Any],
        kind: str,
        reason: str,
        response_source_id: Optional[str] = None,
    ) -> bool:
        logger.debug(
            "Suppressing BRSE %s before publish room=%s speaker=%s utterance=%s "
            "reason=%s response_source_id=%s source_valid=%s source_final=%s generation=%s",
            kind,
            self.room_id,
            speaker_id,
            state.get("utterance_id"),
            reason,
            response_source_id,
            state.get("source_valid"),
            state.get("source_final"),
            state.get("generation"),
        )
        return False

    def _assess_source_transcript(
        self,
        text: str,
        *,
        duration_ms: Optional[int],
        final: bool,
    ) -> tuple[bool, str, str, Dict[str, Any]]:
        return assess_source_transcript(text, duration_ms=duration_ms, final=final)

    async def _publish_source_partial(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not state["source_text"]:
            return
        partial_ok, _reason, normalized_text, _signal = self._assess_source_transcript(
            state["source_text"],
            duration_ms=state.get("speech_duration_ms"),
            final=False,
        )
        if not partial_ok:
            return

        await self.publisher.publish_source_transcript_partial(
            transcript_id=state["source_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            text=normalized_text,
            created_at=state["created_at"],
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
        )

    async def _publish_source_final(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not state["source_text"] or not state.get("source_valid"):
            return

        await self.publisher.publish_source_transcript_final(
            transcript_id=state["source_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            text=state["source_text"],
            created_at=state["created_at"],
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
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
        if not self._source_state_is_valid_for_output(state) or not state["brse_text"]:
            router.clear_queue()
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
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
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
        if not self._source_state_is_valid_for_output(state):
            router.clear_queue()
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
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
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
        output_suppressed = status == _SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP
        audio_track = None if output_suppressed or router is None else router.track_descriptor()
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
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
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
            "source_item_id": None,
            "source_committed": False,
            "source_final": False,
            "source_valid": False,
            "source_rejected_reason": None,
            "source_signal": {},
            "speech_duration_ms": self._speaker_state(speaker_id).last_speech_duration_ms,
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
