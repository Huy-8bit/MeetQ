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
from server.service.brain_runtime.context import RoomContextBuffer
from server.service.brain_runtime.delivery import RelayDeliveryController
from server.service.brain_runtime.events import RedisEventPublisher
from server.service.brain_runtime.overlap import (
    OVERLAP_LEVEL_HEAVY,
    OVERLAP_LEVEL_LIGHT,
    OVERLAP_LEVEL_SINGLE,
    OverlapManager,
)
from server.service.brain_runtime.policy import ConversationPolicyEngine
from server.service.brain_runtime.text_translation import translate_caption_text
from server.brain.realtime.interpreter_client import InterpreterRealtimeClient
from server.service.media.livekit_runtime import LiveKitRuntime
from server.brain.realtime.session_config import (
    INTERPRETER_INPUT_QUEUE_MAXSIZE,
    INTERPRETER_INPUT_WARMUP_CHUNKS,
)
from server.brain.realtime.source_policy import (
    source_state_is_valid_for_output,
)
from server.service.media.output_router import OutputRouter
from server.meeting_modes import (
    BRSE_PARTICIPANT_ID,
    DEFAULT_BRSE_MODE,
    DEFAULT_BRSE_OUTPUT_MODE,
    DEFAULT_ROOM_MEETING_LANGUAGES,
    SUPPORTED_MEETING_LANGUAGES,
    is_active_human_participant,
    resolve_relay_target_language,
)

logger = logging.getLogger(__name__)


_SUPPORTED_LANGS = set(SUPPORTED_MEETING_LANGUAGES)
_SUPPORTED_LANGS_MESSAGE = ", ".join(SUPPORTED_MEETING_LANGUAGES)
_INPUT_QUEUE_MAXSIZE = INTERPRETER_INPUT_QUEUE_MAXSIZE
_INPUT_WARMUP_CHUNKS = INTERPRETER_INPUT_WARMUP_CHUNKS
_OVERLAP_FOCUS_COOLDOWN_SECONDS = 0.85
_CHAOS_RECENT_WINDOW_SECONDS = 9.0
_CHAOS_MIN_SUMMARY_TURNS = 3
_CHAOS_MIN_DISTINCT_SPEAKERS = 2
_CHAOS_PENDING_RELAY_THRESHOLD = 3
_OVERLAP_UNDERSTANDING_WINDOW_SECONDS = 9.0
_OVERLAP_SUMMARY_MIN_TURNS = 2
_OVERLAP_SUMMARY_MIN_SIGNAL_CHARS = 24
_OVERLAP_SUMMARY_MAX_TURNS = 6
_OVERLAP_LEVEL_SINGLE = OVERLAP_LEVEL_SINGLE
_OVERLAP_LEVEL_LIGHT = OVERLAP_LEVEL_LIGHT
_OVERLAP_LEVEL_HEAVY = OVERLAP_LEVEL_HEAVY
_OVERLAP_HEAVY_BLOCKED_SPEAKER_THRESHOLD = 2
_SUMMARY_MAX_SOURCE_CHARS = 1400
_RELAY_STATE_CLEANUP_DELAY_SECONDS = 1.0
_PUBLIC_TEXT_GATE_REASON = "pending_public_text_gate"
_PUBLIC_TEXT_GATE_MIN_PARTIAL_MEANINGFUL_CHARS = 8
_PUBLIC_RELAY_MAX_START_DELAY_SECONDS = 8.0
_PUBLIC_SUMMARY_MAX_START_DELAY_SECONDS = 24.0


@dataclass(frozen=True)
class _RoutingPlan:
    src_lang: str
    tgt_lang: str
    audience_ids: frozenset[str]
    relay_enabled: bool = True
    routing_mode: str = "cross_language"


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
    @property
    def relay_focus_speaker_id(self) -> Optional[str]:
        return self.room_context.relay_focus.speaker_id

    @relay_focus_speaker_id.setter
    def relay_focus_speaker_id(self, value: Optional[str]) -> None:
        self.room_context.relay_focus.speaker_id = value

    @property
    def relay_focus_generation(self) -> Optional[int]:
        return self.room_context.relay_focus.generation

    @relay_focus_generation.setter
    def relay_focus_generation(self, value: Optional[int]) -> None:
        self.room_context.relay_focus.generation = value

    @property
    def relay_focus_started_at(self) -> Optional[float]:
        return self.room_context.relay_focus.started_at

    @relay_focus_started_at.setter
    def relay_focus_started_at(self, value: Optional[float]) -> None:
        self.room_context.relay_focus.started_at = value

    @property
    def relay_focus_cooldown_until(self) -> Optional[float]:
        return self.room_context.relay_focus.cooldown_until

    @relay_focus_cooldown_until.setter
    def relay_focus_cooldown_until(self, value: Optional[float]) -> None:
        self.room_context.relay_focus.cooldown_until = value

    def __init__(
        self,
        room_id: str,
        settings: Settings,
        publisher: RedisEventPublisher,
        *,
        brse_mode: str = DEFAULT_BRSE_MODE,
        brse_output_mode: str = DEFAULT_BRSE_OUTPUT_MODE,
        room_languages: Optional[Iterable[str]] = None,
    ):
        self.room_id = room_id
        self.settings = settings
        self.publisher = publisher
        self.room_languages: tuple[str, ...] = tuple(DEFAULT_ROOM_MEETING_LANGUAGES)
        self.meeting_languages: tuple[str, ...] = self.room_languages
        self._meeting_languages_ready = False
        self._set_meeting_languages(room_languages)
        self.delivery = RelayDeliveryController(
            room_id=room_id,
            brse_mode=brse_mode,
            brse_output_mode=brse_output_mode,
            room_languages=self.room_languages,
        )
        self.brse_mode = self.delivery.brse_mode
        self.brse_output_mode = self.delivery.brse_output_mode
        self.relay_text_enabled = self.delivery.relay_text_enabled
        self.relay_audio_enabled = self.delivery.relay_audio_enabled
        self.relay_output_enabled = self.delivery.relay_output_enabled
        self.silent_summary_mode = self.delivery.silent_summary_mode
        self.text_only_output_mode = self.delivery.text_only_output_mode
        self.room_context = RoomContextBuffer(room_id)
        self.policy = ConversationPolicyEngine(room_id)
        self.overlap = OverlapManager(
            room_id=room_id,
            context=self.room_context,
            recent_window_seconds=_CHAOS_RECENT_WINDOW_SECONDS,
            understanding_window_seconds=_OVERLAP_UNDERSTANDING_WINDOW_SECONDS,
            summary_min_turns=_OVERLAP_SUMMARY_MIN_TURNS,
            summary_min_signal_chars=_OVERLAP_SUMMARY_MIN_SIGNAL_CHARS,
            summary_max_turns=_OVERLAP_SUMMARY_MAX_TURNS,
            chaos_min_summary_turns=_CHAOS_MIN_SUMMARY_TURNS,
            chaos_min_distinct_speakers=_CHAOS_MIN_DISTINCT_SPEAKERS,
            chaos_pending_relay_threshold=_CHAOS_PENDING_RELAY_THRESHOLD,
            heavy_blocked_speaker_threshold=_OVERLAP_HEAVY_BLOCKED_SPEAKER_THRESHOLD,
            summary_max_source_chars=_SUMMARY_MAX_SOURCE_CHARS,
        )
        self.runtime = LiveKitRuntime(
            room_id=room_id,
            settings=settings,
            on_media_connected=self._on_media_connected,
            on_media_disconnected=self._on_media_disconnected,
            on_audio_stream=self._on_audio_stream,
            output_audio_enabled=self.relay_audio_enabled,
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
        self.speaker_relay_enabled: Dict[str, bool] = {}
        self.speaker_route_modes: Dict[str, str] = {}
        self.speaker_generations: Dict[str, int] = {}
        self.transcript_state: Dict[str, Dict[str, Any]] = {}
        self.transcript_states: Dict[str, Dict[str, Any]] = {}
        self.route_failures: Dict[str, tuple[Any, ...]] = {}
        self.speaker_lifecycle: Dict[str, _SpeakerArbitrationState] = {}
        self.relay_focus_speaker_id: Optional[str] = None
        self.relay_focus_generation: Optional[int] = None
        self.relay_focus_started_at: Optional[float] = None
        self.relay_focus_cooldown_until: Optional[float] = None
        self.relay_focus_release_task: Optional[asyncio.Task] = None
        self._closed = False
        self.public_relay_approved_count = 0
        self.public_relay_suppressed_count = 0
        self.single_speaker_relay_approved_count = 0

    async def start(self) -> None:
        logger.info(
            "Starting BRSE room runtime room=%s brse_mode=%s brse_output_mode=%s",
            self.room_id,
            self.brse_mode,
            self.brse_output_mode,
        )
        self.delivery.log_startup()
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
            self.speaker_relay_enabled,
            self.speaker_route_modes,
            self.speaker_generations,
            self.transcript_state,
            self.transcript_states,
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
        self.speaker_relay_enabled.clear()
        self.speaker_route_modes.clear()
        self.speaker_generations.clear()
        self.transcript_state.clear()
        self.transcript_states.clear()
        self.room_context.reset()
        self.overlap.reset()
        self.route_failures.clear()
        self.speaker_lifecycle.clear()
        self.relay_focus_speaker_id = None
        self.relay_focus_generation = None
        self.relay_focus_started_at = None
        self.relay_focus_cooldown_until = None
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
                self.room_context.upsert_speaker(participant_id, payload)

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
        self.room_context.upsert_speaker(participant_id, current)
        await self._refresh_all_routes()

    async def remove_participant(self, participant_id: str) -> None:
        self.participants.pop(participant_id, None)
        self.room_context.remove_speaker(participant_id)
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
        if speaker_id not in self.overlap.blocked_speakers:
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
                    f"Room {self.room_id} does not have a valid room_languages configuration yet. "
                    "BRSE runtime is paused until the room-level language context is available."
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

        if speaker_lang not in self.room_languages:
            return _RoutingResolution(
                plan=None,
                error_code="invalid_language",
                error_message=(
                    f"Speaker {speaker_id} uses language {speaker_lang}, but room_languages is "
                    f"{', '.join(self.room_languages)}."
                ),
            )

        if len(self.room_languages) > 2:
            target_languages = self._multi_language_text_target_languages(
                speaker_id,
                speaker_lang,
            )
            audience_ids = frozenset(
                participant_id
                for target_language in target_languages
                for participant_id in self._audience_ids_for_target(
                    speaker_id,
                    target_language,
                )
            )
            routing_mode = (
                "multi_language_text_caption"
                if target_languages
                else "multi_language_source_capture_no_audience"
            )
            logger.info(
                "BRSE route chosen room=%s speaker=%s speaker_language=%s target_languages=%s "
                "room_languages=%s audience_ids=%s routing_mode=%s relay_enabled=False "
                "relay_text_enabled=%s relay_audio_enabled=%s",
                self.room_id,
                speaker_id,
                speaker_lang,
                ",".join(target_languages) or "-",
                ",".join(self.room_languages),
                ",".join(sorted(audience_ids)) or "-",
                routing_mode,
                self.relay_text_enabled,
                self.relay_audio_enabled,
            )
            return _RoutingResolution(
                plan=_RoutingPlan(
                    src_lang=speaker_lang,
                    tgt_lang=target_languages[0] if target_languages else speaker_lang,
                    audience_ids=audience_ids,
                    relay_enabled=False,
                    routing_mode=routing_mode,
                )
            )

        audience_languages = self._audience_languages_for_speaker(speaker_id)
        target_lang = resolve_relay_target_language(
            speaker_lang,
            self.room_languages,
            audience_languages=audience_languages,
        )
        if target_lang is None:
            audience_ids = frozenset(self._audience_ids_for_target(speaker_id, speaker_lang))
            logger.info(
                "BRSE route chosen room=%s speaker=%s speaker_language=%s target_language=%s "
                "room_languages=%s audience_ids=%s routing_mode=same_language_source_capture "
                "relay_enabled=False",
                self.room_id,
                speaker_id,
                speaker_lang,
                speaker_lang,
                ",".join(self.room_languages),
                ",".join(sorted(audience_ids)) or "-",
            )
            return _RoutingResolution(
                plan=_RoutingPlan(
                    src_lang=speaker_lang,
                    tgt_lang=speaker_lang,
                    audience_ids=audience_ids,
                    relay_enabled=False,
                    routing_mode="same_language_source_capture",
                )
            )

        audience_ids = frozenset(self._audience_ids_for_target(speaker_id, target_lang))
        logger.info(
            "BRSE route chosen room=%s speaker=%s speaker_language=%s target_language=%s "
            "room_languages=%s audience_ids=%s routing_mode=cross_language relay_enabled=True",
            self.room_id,
            speaker_id,
            speaker_lang,
            target_lang,
            ",".join(self.room_languages),
            ",".join(sorted(audience_ids)) or "-",
        )
        return _RoutingResolution(
            plan=_RoutingPlan(
                src_lang=speaker_lang,
                tgt_lang=target_lang,
                audience_ids=audience_ids,
                relay_enabled=True,
                routing_mode="cross_language",
            )
        )

    async def _ensure_speaker_runtime(self, speaker_id: str, plan: _RoutingPlan) -> None:
        if speaker_id in self.clients:
            return

        stream = self.active_streams.get(speaker_id)
        if stream is None:
            return

        logger.info(
            "Starting BRSE relay runtime for speaker=%s room=%s route=%s->%s audience=%d "
            "routing_mode=%s relay_enabled=%s",
            speaker_id,
            self.room_id,
            plan.src_lang,
            plan.tgt_lang,
            len(plan.audience_ids),
            plan.routing_mode,
            plan.relay_enabled,
        )
        route_audio_enabled = self.relay_audio_enabled and plan.relay_enabled
        route_silent_listener = self.silent_summary_mode or not plan.relay_enabled
        route_suppressed_reason = (
            self.delivery.suppressed_audio_reason
            if plan.relay_enabled
            else "same_language_no_translation_required"
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
            output_enabled=route_audio_enabled,
            output_mode=self.brse_output_mode,
            suppressed_reason=route_suppressed_reason,
        )
        self.routers[speaker_id] = router
        await router.ensure_track()

        client = InterpreterRealtimeClient(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_realtime_model,
            input_transcription_model=self.settings.openai_realtime_transcription_model,
            src_lang=plan.src_lang,
            tgt_lang=plan.tgt_lang,
            meeting_languages=list(self.room_languages),
            audio_input=audio_input,
            request_audio_output=route_audio_enabled,
            silent_listener_mode=route_silent_listener,
        )
        logger.info(
            "BRSE model path selected room=%s speaker=%s realtime_model=%s "
            "input_transcription_model=%s overlap_summary_model=%s fallback_override_env=%s",
            self.room_id,
            speaker_id,
            self.settings.openai_realtime_model,
            self.settings.openai_realtime_transcription_model,
            self.settings.openai_realtime_model,
            "OPENAI_REALTIME_MODEL,OPENAI_REALTIME_TRANSCRIPTION_MODEL",
        )
        generation = self._next_speaker_generation(speaker_id)
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        self.speaker_audiences[speaker_id] = plan.audience_ids
        self.speaker_relay_enabled[speaker_id] = plan.relay_enabled
        self.speaker_route_modes[speaker_id] = plan.routing_mode
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
            "Reconfiguring BRSE relay runtime for %s in room %s: %s -> %s "
            "routing_mode=%s relay_enabled=%s",
            speaker_id,
            self.room_id,
            f"{current_src}->{current_tgt}",
            f"{plan.src_lang}->{plan.tgt_lang}",
            plan.routing_mode,
            plan.relay_enabled,
        )
        route_audio_enabled = self.relay_audio_enabled and plan.relay_enabled
        route_silent_listener = self.silent_summary_mode or not plan.relay_enabled
        route_suppressed_reason = (
            self.delivery.suppressed_audio_reason
            if plan.relay_enabled
            else "same_language_no_translation_required"
        )

        if client._ws is not None and client._assistant_speaking:
            try:
                await client._cancel_response(client._ws)
            except Exception:
                logger.exception("Failed to cancel in-flight BRSE relay response for %s", speaker_id)

        self.transcript_state.pop(speaker_id, None)
        for utterance_id, state in list(self.transcript_states.items()):
            if state.get("speaker_id") == speaker_id:
                self.transcript_states.pop(utterance_id, None)
        self.room_context.remove_speaker_runtime_state(speaker_id)

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
            output_enabled=route_audio_enabled,
            output_mode=self.brse_output_mode,
            suppressed_reason=route_suppressed_reason,
        )
        self.routers[speaker_id] = router
        await router.ensure_track()

        generation = self._next_speaker_generation(speaker_id)
        self.speaker_sources[speaker_id] = plan.src_lang
        self.speaker_targets[speaker_id] = plan.tgt_lang
        self.speaker_audiences[speaker_id] = plan.audience_ids
        self.speaker_relay_enabled[speaker_id] = plan.relay_enabled
        self.speaker_route_modes[speaker_id] = plan.routing_mode
        self._bind_client_callbacks(
            speaker_id=speaker_id,
            src_lang=plan.src_lang,
            target_lang=plan.tgt_lang,
            generation=generation,
            client=client,
            router=router,
        )
        client.meeting_languages = list(self.room_languages)
        client.request_audio_output = route_audio_enabled
        client.input_transcription_model = self.settings.openai_realtime_transcription_model
        if hasattr(client, "silent_listener_mode"):
            client.silent_listener_mode = route_silent_listener
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
        self.speaker_relay_enabled.pop(speaker_id, None)
        self.speaker_route_modes.pop(speaker_id, None)
        self.speaker_generations.pop(speaker_id, None)
        self.transcript_state.pop(speaker_id, None)
        for utterance_id, state in list(self.transcript_states.items()):
            if state.get("speaker_id") == speaker_id:
                self.transcript_states.pop(utterance_id, None)
        self.room_context.remove_speaker_runtime_state(speaker_id, keep_speaker=keep_participant)
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

        if self.overlap.blocked_generations.get(speaker_id) == generation:
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
        if self.overlap.blocked_generations.get(speaker_id) == generation:
            return False
        if speaker_id in self.overlap.blocked_speakers:
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
            self.room_context.refresh_relay_focus_generation(generation=generation)
            return True
        return False

    def _claim_relay_focus(self, *, speaker_id: str, generation: int, reason: str) -> None:
        previous = self.relay_focus_speaker_id
        if previous == speaker_id:
            self.room_context.refresh_relay_focus_generation(generation=generation)
            self._cancel_relay_focus_release()
            self.relay_focus_cooldown_until = None
            return

        self._cancel_relay_focus_release()
        self.room_context.claim_relay_focus(speaker_id=speaker_id, generation=generation)
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
        window, first_block = self.overlap.block_speaker(
            primary_speaker_id=focus_speaker_id,
            blocked_speaker_id=speaker_id,
            generation=generation,
        )
        router.clear_queue()
        self._set_speaker_lifecycle(
            speaker_id,
            _SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP,
            generation=generation,
            blocked_by=focus_speaker_id,
            blocked_since=self.overlap.started_at.get(speaker_id, now),
            last_speech_started_at=now,
        )

        if not first_block:
            return

        overlap_window_ms = self._overlap_window_ms()
        logger.warning(
            "BRSE overlap detected room=%s primary=%s blocked=%s "
            "generation=%d overlap_window_ms=%s suppressed_count=%d "
            "understanding_window=%s capture_continues=True",
            self.room_id,
            focus_speaker_id,
            speaker_id,
            generation,
            overlap_window_ms if overlap_window_ms is not None else "n/a",
            len(self.overlap.blocked_speakers),
            window.window_id,
        )
        asyncio.create_task(
            self._publish_runtime_status(
                speaker_id=speaker_id,
                target_lang=target_lang,
                status=_SpeakerLifecycle.BLOCKED_DUE_TO_OVERLAP,
                message=(
                    "BRSE relay is focused on another active speaker; "
                    "capture continues and heavy overlap will be summarized for relay."
                ),
            )
        )

    def _mark_blocked_turn_finished(self, speaker_id: str, generation: int) -> None:
        if not self.overlap.mark_blocked_turn_finished(speaker_id, generation):
            return
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
        self.room_context.start_relay_focus_cooldown(cooldown_until=cooldown_until)
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

        blocked_speaker_ids = sorted(self.overlap.blocked_speakers)
        self._cancel_relay_focus_release()
        self.room_context.clear_relay_focus()

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
        if not self._closed:
            asyncio.create_task(self._try_start_pending_relays(reason=f"focus_released:{reason}"))

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
        self.overlap.clear_speaker(speaker_id)

    def _open_overlap_understanding_window(
        self,
        *,
        primary_speaker_id: Optional[str],
        blocked_speaker_id: str,
        reason: str,
    ):
        return self.overlap.open_window(
            primary_speaker_id=primary_speaker_id,
            blocked_speaker_id=blocked_speaker_id,
            reason=reason,
        )

    def _current_overlap_understanding_window(self):
        return self.overlap.current_window()

    def _close_overlap_understanding_window(
        self,
        *,
        reason: str,
        summary_utterance_id: Optional[str] = None,
    ) -> None:
        self.overlap.close_window(reason=reason, summary_utterance_id=summary_utterance_id)

    def _overlap_window_turns(self) -> list[Dict[str, Any]]:
        return self.overlap.window_turns()

    def _summary_signal_chars(self, turns: Iterable[Dict[str, Any]]) -> int:
        return self.overlap.summary_signal_chars(list(turns))

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
        window = self._current_overlap_understanding_window()
        return {
            "policy": "controlled_full_duplex_serialized_output",
            "active_speaker_id": self.relay_focus_speaker_id,
            "active_generation": self.relay_focus_generation,
            "speaker_state": self._speaker_lifecycle_name(speaker_id),
            "is_active_relay_speaker": self.relay_focus_speaker_id == speaker_id,
            "blocked_speaker_ids": sorted(self.overlap.blocked_speakers),
            "suppressed_speaker_count": len(self.overlap.blocked_speakers),
            "cooldown_ms": cooldown_ms,
            "pending_relay_count": self._pending_relay_count(),
            "overlap_window_id": window.window_id if window is not None else None,
        }

    def _overlap_payload(self, speaker_id: str) -> Dict[str, Any]:
        state = self.speaker_lifecycle.get(speaker_id)
        overlap_window_ms = None
        if speaker_id in self.overlap.blocked_speakers:
            overlap_window_ms = self._overlap_window_ms()
        return self.overlap.overlap_payload(
            speaker_id=speaker_id,
            overlap_window_ms=overlap_window_ms,
            pending_relay_count=self._pending_relay_count(),
            primary_speaker_id=self.relay_focus_speaker_id,
            blocked_by=state.blocked_by if state is not None else None,
        )

    def _pending_relay_count(self) -> int:
        total = 0
        for client in self.clients.values():
            getter = getattr(client, "pending_relay_count", None)
            if callable(getter):
                try:
                    total += int(getter())
                except Exception:
                    logger.debug("Failed to read pending relay count", exc_info=True)
        return total

    def _chaos_detected(self) -> bool:
        return self._overlap_level() == _OVERLAP_LEVEL_HEAVY

    def _recent_overlap_context(self) -> tuple[list[Dict[str, Any]], set[Any]]:
        return self.overlap.recent_overlap_context()

    def _overlap_level(self) -> str:
        return self.overlap.overlap_level(pending_relay_count=self._pending_relay_count())

    def _record_validated_source_turn(self, *, speaker_id: str, state: Dict[str, Any]) -> None:
        self.overlap.record_validated_source_turn(
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            state=state,
        )

    def _apply_public_relay_policy(
        self,
        *,
        speaker_id: str,
        state: Dict[str, Any],
        overlap_level: Optional[str] = None,
    ) -> None:
        audience_count = len(self.speaker_audiences.get(speaker_id, frozenset()))
        relay_style = str(state.get("relay_style") or "normal")
        if overlap_level is None:
            overlap_level = self._overlap_level()
        decision = self.policy.decide_public_relay(
            speaker_id=speaker_id,
            utterance_id=str(state.get("utterance_id") or ""),
            source_text=state.get("relay_source_text") or state.get("source_text") or "",
            duration_ms=state.get("speech_duration_ms"),
            relay_style=relay_style,
            overlap_blocked=bool(state.get("source_blocked_for_overlap")),
            audience_count=audience_count,
            overlap_level=overlap_level,
        )
        state["public_relay_approved"] = decision.approved
        state["public_relay_reason"] = decision.reason
        state["public_relay_signal"] = decision.signal
        state["public_relay_overlap_level"] = decision.overlap_level
        state["relay_decision"] = {
            "approved": decision.approved,
            "reason": decision.reason,
            "relay_style": decision.relay_style,
            "overlap_level": decision.overlap_level,
            "candidate_reason": state.get("relay_candidate_reason"),
        }
        self.room_context.record_relay_decision(
            utterance_id=str(state.get("utterance_id") or ""),
            speaker_id=speaker_id,
            relay_style=decision.relay_style,
            decision="publish" if decision.approved else "suppress",
            reason=decision.reason,
            overlap_level=decision.overlap_level,
            delivery_mode=None,
        )
        if decision.approved:
            self.public_relay_approved_count += 1
            if relay_style == "normal" and decision.overlap_level == _OVERLAP_LEVEL_SINGLE:
                self.single_speaker_relay_approved_count += 1
            logger.info(
                "BRSE public relay approved room=%s speaker=%s utterance=%s "
                "reason=%s relay_style=%s audience=%d overlap_level=%s chaos=%s "
                "approved_total=%d single_speaker_total=%d signal=%s",
                self.room_id,
                speaker_id,
                state.get("utterance_id"),
                decision.reason,
                relay_style,
                audience_count,
                decision.overlap_level,
                decision.overlap_level == _OVERLAP_LEVEL_HEAVY,
                self.public_relay_approved_count,
                self.single_speaker_relay_approved_count,
                decision.signal,
            )
            return

        self.public_relay_suppressed_count += 1
        logger.info(
            "BRSE public relay suppressed room=%s speaker=%s utterance=%s "
            "reason=%s relay_style=%s audience=%d overlap_level=%s chaos=%s "
            "suppressed_total=%d signal=%s",
            self.room_id,
            speaker_id,
            state.get("utterance_id"),
            decision.reason,
            relay_style,
            audience_count,
            decision.overlap_level,
            decision.overlap_level == _OVERLAP_LEVEL_HEAVY,
            self.public_relay_suppressed_count,
            decision.signal,
        )

    def _public_relay_is_approved(self, *, speaker_id: str, state: Dict[str, Any], kind: str) -> bool:
        if state.get("public_relay_approved"):
            return True
        logger.info(
            "Suppressing BRSE %s by public relay policy room=%s speaker=%s utterance=%s reason=%s",
            kind,
            self.room_id,
            speaker_id,
            state.get("utterance_id"),
            state.get("public_relay_reason") or "public_relay_not_approved",
        )
        return False

    def _public_relay_is_fresh(self, *, speaker_id: str, state: Dict[str, Any], kind: str) -> bool:
        started_at = state.get("started_at")
        if not isinstance(started_at, (int, float)):
            return True
        max_age = (
            _PUBLIC_SUMMARY_MAX_START_DELAY_SECONDS
            if state.get("relay_style") == "summary"
            else _PUBLIC_RELAY_MAX_START_DELAY_SECONDS
        )
        age_seconds = max(0.0, time.monotonic() - float(started_at))
        if age_seconds <= max_age:
            return True
        state["public_relay_approved"] = False
        state["public_relay_reason"] = "stale_public_relay"
        logger.info(
            "BRSE public relay suppressed as stale room=%s speaker=%s utterance=%s "
            "kind=%s age_ms=%d max_age_ms=%d relay_style=%s",
            self.room_id,
            speaker_id,
            state.get("utterance_id"),
            kind,
            int(age_seconds * 1000),
            int(max_age * 1000),
            state.get("relay_style", "normal"),
        )
        return False

    def _prepare_public_output_gate(self, *, router: OutputRouter, state: Dict[str, Any]) -> None:
        state["public_output_ready"] = False
        state["public_output_rejected"] = False
        state["public_output_gate_reason"] = _PUBLIC_TEXT_GATE_REASON
        state["public_output_gate_logged"] = False
        router.reset_public_output_gate()
        router.hold_public_output(reason=_PUBLIC_TEXT_GATE_REASON)

    def _apply_public_output_text_gate(
        self,
        *,
        speaker_id: str,
        state: Dict[str, Any],
        router: OutputRouter,
        final: bool,
    ) -> bool:
        if state.get("public_output_rejected"):
            return False
        text = str(state.get("brse_text") or "")
        decision = self.policy.decide_relay_output_text(
            speaker_id=speaker_id,
            utterance_id=str(state.get("utterance_id") or ""),
            text=text,
            speaker_name=self._speaker_name(speaker_id),
            final=final,
            relay_style=str(state.get("relay_style") or "normal"),
            min_partial_meaningful_chars=_PUBLIC_TEXT_GATE_MIN_PARTIAL_MEANINGFUL_CHARS,
        )
        if not decision.publishable:
            if decision.reject:
                state["public_output_rejected"] = True
                state["public_output_ready"] = False
                state["public_output_gate_reason"] = decision.reason
                state["brse_text"] = ""
                self.room_context.record_relay_decision(
                    utterance_id=str(state.get("utterance_id") or ""),
                    speaker_id=speaker_id,
                    relay_style=str(state.get("relay_style") or "normal"),
                    decision="reject_output",
                    reason=decision.reason,
                    overlap_level=str(state.get("public_relay_overlap_level") or _OVERLAP_LEVEL_SINGLE),
                    delivery_mode=None,
                )
                logger.warning(
                    "BRSE relay output rejected room=%s speaker=%s utterance=%s "
                    "reason=%s relay_style=%s signal=%s text=%r",
                    self.room_id,
                    speaker_id,
                    state.get("utterance_id"),
                    decision.reason,
                    state.get("relay_style", "normal"),
                    decision.signal,
                    text,
                )
                asyncio.create_task(router.reject_public_output(reason=decision.reason))
            elif not state.get("public_output_gate_logged"):
                state["public_output_gate_logged"] = True
                self.room_context.record_relay_decision(
                    utterance_id=str(state.get("utterance_id") or ""),
                    speaker_id=speaker_id,
                    relay_style=str(state.get("relay_style") or "normal"),
                    decision="hold_output",
                    reason=decision.reason,
                    overlap_level=str(state.get("public_relay_overlap_level") or _OVERLAP_LEVEL_SINGLE),
                    delivery_mode=None,
                )
                logger.info(
                    "BRSE relay output held pending usable text room=%s speaker=%s "
                    "utterance=%s reason=%s signal=%s text=%r",
                    self.room_id,
                    speaker_id,
                    state.get("utterance_id"),
                    decision.reason,
                    decision.signal,
                    text,
                )
            return False

        if not state.get("public_output_ready"):
            state["public_output_ready"] = True
            state["public_output_gate_reason"] = None
            state["public_output_policy_reason"] = decision.reason
            asyncio.create_task(router.release_public_output(reason="text_gate_passed"))
            logger.info(
                "BRSE relay output text gate passed room=%s speaker=%s utterance=%s chars=%d final=%s",
                self.room_id,
                speaker_id,
                state.get("utterance_id"),
                len(text.strip()),
                final,
            )
        return True

    def _build_summary_plan_if_chaotic(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        current_state: Dict[str, Any],
        overlap_level: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.overlap.build_summary_plan_if_chaotic(
            speaker_id=speaker_id,
            target_lang=target_lang,
            current_state=current_state,
            pending_relay_count=self._pending_relay_count(),
            transcript_states=self.transcript_states,
            relay_source_is_active_response=self._relay_source_is_active_response,
            overlap_level=overlap_level,
        )

    def _relay_source_is_active_response(self, relay_source_id: str) -> bool:
        for client in self.clients.values():
            getter = getattr(client, "current_response_source_id", None)
            if not callable(getter):
                continue
            try:
                if getter() == relay_source_id:
                    return True
            except Exception:
                logger.debug("Failed to read active BRSE response source", exc_info=True)
        return False

    def _relay_source_can_start(
        self,
        *,
        speaker_id: str,
        generation: int,
        relay_source_id: str,
    ) -> bool:
        if not self.relay_output_enabled:
            return False
        state = self.transcript_states.get(relay_source_id)
        if state is None:
            return False
        if not state.get("relay_translation_enabled", True):
            return False
        if state.get("speaker_id") != speaker_id or state.get("generation") != generation:
            return False
        if not self._source_state_is_valid_for_output(state):
            return False
        if not self._public_relay_is_approved(
            speaker_id=speaker_id,
            state=state,
            kind="queued_relay_start",
        ):
            return False
        if not self._public_relay_is_fresh(
            speaker_id=speaker_id,
            state=state,
            kind="queued_relay_start",
        ):
            return False
        focus_speaker_id = self.relay_focus_speaker_id
        if focus_speaker_id is None:
            self._claim_relay_focus(
                speaker_id=speaker_id,
                generation=generation,
                reason=f"queued_relay_start:{state.get('relay_style', 'normal')}",
            )
            self._clear_overlap_block(speaker_id)
            return True
        return focus_speaker_id == speaker_id

    def _relay_source_should_drop_pending(
        self,
        *,
        speaker_id: str,
        generation: int,
        relay_source_id: str,
    ) -> bool:
        state = self.transcript_states.get(relay_source_id)
        if state is None:
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=state_missing",
                self.room_id,
                speaker_id,
                relay_source_id,
            )
            return True
        if not state.get("relay_translation_enabled", True):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s "
                "reason=same_language_no_translation_required",
                self.room_id,
                speaker_id,
                relay_source_id,
            )
            return True
        if state.get("speaker_id") != speaker_id or state.get("generation") != generation:
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s "
                "reason=stale_generation state_speaker=%s state_generation=%s current_generation=%d",
                self.room_id,
                speaker_id,
                relay_source_id,
                state.get("speaker_id"),
                state.get("generation"),
                generation,
            )
            return True
        if not self._source_state_is_valid_for_output(state):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=source_not_valid",
                self.room_id,
                speaker_id,
                relay_source_id,
            )
            return True
        if not self._relay_route_is_still_valid(
            speaker_id=speaker_id,
            src_lang=str(state.get("src_lang") or ""),
            target_lang=str(state.get("target_lang") or ""),
        ):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=route_not_current",
                self.room_id,
                speaker_id,
                relay_source_id,
            )
            return True
        if not state.get("public_relay_approved"):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=%s relay_style=%s",
                self.room_id,
                speaker_id,
                relay_source_id,
                state.get("public_relay_reason") or "public_relay_not_approved",
                state.get("relay_style", "normal"),
            )
            return True
        if not self._public_relay_is_fresh(
            speaker_id=speaker_id,
            state=state,
            kind="pending_relay_drop_check",
        ):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=stale_public_relay "
                "relay_style=%s",
                self.room_id,
                speaker_id,
                relay_source_id,
                state.get("relay_style", "normal"),
            )
            return True
        if state.get("public_output_rejected"):
            logger.info(
                "Dropping pending BRSE relay room=%s speaker=%s source=%s reason=%s relay_style=%s",
                self.room_id,
                speaker_id,
                relay_source_id,
                state.get("public_output_gate_reason") or "public_output_rejected",
                state.get("relay_style", "normal"),
            )
            return True
        return False

    async def _try_start_pending_relays(self, *, reason: str) -> None:
        if self._closed or not self.relay_output_enabled or self.relay_focus_speaker_id is not None:
            return
        for speaker_id, client in list(self.clients.items()):
            starter = getattr(client, "try_start_pending_relay", None)
            if not callable(starter):
                continue
            try:
                started = await starter()
            except Exception:
                logger.exception(
                    "Failed to start pending BRSE relay room=%s speaker=%s reason=%s",
                    self.room_id,
                    speaker_id,
                    reason,
                )
                continue
            if started:
                logger.info(
                    "Started pending BRSE relay room=%s speaker=%s reason=%s",
                    self.room_id,
                    speaker_id,
                    reason,
                )
                return

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
            response_source_id = client.current_response_source_id()
            state = self.transcript_states.get(response_source_id) if response_source_id else None
            if state is None:
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
                response_source_id=response_source_id,
                kind=kind,
            ):
                router.clear_queue()
                return None
            return state

        def on_input_audio_committed(item_id: Optional[str]) -> None:
            if not is_current_callback():
                return
            state = self._open_transcript_state(
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
            state["relay_source_text"] = ""
            state["brse_text"] = ""
            state["relay_translation_enabled"] = self.speaker_relay_enabled.get(speaker_id, True)
            state["route_mode"] = self.speaker_route_modes.get(speaker_id, "cross_language")
            state["source_blocked_for_overlap"] = speaker_id in self.overlap.blocked_speakers
            window = self._current_overlap_understanding_window()
            if window is not None:
                state["overlap_window_id"] = window.window_id
            state["speech_duration_ms"] = self._speaker_state(speaker_id).last_speech_duration_ms

        def on_input_transcript_delta(delta: str) -> None:
            if not delta or not is_current_callback():
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
            if not is_publishable_callback("source_partial"):
                return
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
                speaker_id=speaker_id,
                target_lang=target_lang,
            )
            state["source_text"] = normalized_text
            state["source_final"] = True
            state["source_valid"] = source_ok
            state["source_rejected_reason"] = None if source_ok else reason
            state["source_signal"] = signal
            state["source_blocked_for_overlap"] = bool(
                state.get("source_blocked_for_overlap")
                or speaker_id in self.overlap.blocked_speakers
            )
            technical_signal = signal.get("technical_terms")
            detected_term_signal = signal.get("detected_terms")
            if isinstance(technical_signal, dict) and any(
                technical_signal.get(key)
                for key in ("protected_terms", "corrections", "ambiguous_fragments")
            ):
                logger.info(
                    "BRSE source technical term signal room=%s speaker=%s utterance=%s "
                    "route=%s->%s source_ok=%s reason=%s technical=%s",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    source_ok,
                    reason,
                    technical_signal,
                )
            if isinstance(detected_term_signal, dict) and any(
                detected_term_signal.get(key)
                for key in ("preserve", "conservative", "ambiguous", "is_mixed_language")
            ):
                logger.info(
                    "BRSE source detected term signal room=%s speaker=%s utterance=%s "
                    "route=%s->%s source_ok=%s reason=%s detected_terms=%s",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    source_ok,
                    reason,
                    detected_term_signal,
                )
            if source_ok:
                self._record_validated_source_turn(
                    speaker_id=speaker_id,
                    state=state,
                )
                overlap_level = self._overlap_level()
                route_relay_enabled = bool(state.get("relay_translation_enabled", True))
                if self.relay_output_enabled and route_relay_enabled:
                    summary_plan = self._build_summary_plan_if_chaotic(
                        speaker_id=speaker_id,
                        target_lang=target_lang,
                        current_state=state,
                        overlap_level=overlap_level,
                    )
                    candidate = self.policy.select_relay_candidate(
                        speaker_id=speaker_id,
                        utterance_id=state["utterance_id"],
                        normalized_source_text=normalized_text,
                        overlap_blocked=bool(state.get("source_blocked_for_overlap")),
                        overlap_level=overlap_level,
                        summary_plan=summary_plan,
                    )
                    state["relay_style"] = candidate.relay_style
                    state["relay_source_text"] = candidate.source_text
                    state["relay_candidate_reason"] = candidate.reason
                    state["relay_candidate_metadata"] = candidate.metadata
                    if candidate.relay_style == "summary":
                        state["summary_item_count"] = candidate.metadata.get("summary_item_count", 0)
                        state["summary_speaker_ids"] = candidate.metadata.get("summary_speaker_ids", [])
                        state["summary_window_id"] = candidate.metadata.get("summary_window_id")
                    self._apply_public_relay_policy(
                        speaker_id=speaker_id,
                        state=state,
                        overlap_level=overlap_level,
                    )
                else:
                    reason = (
                        "same_language_no_translation_required"
                        if not route_relay_enabled
                        else "relay_output_disabled"
                    )
                    state["relay_style"] = "normal"
                    state["relay_source_text"] = normalized_text
                    state["relay_candidate_reason"] = reason
                    state["relay_candidate_metadata"] = {}
                    state["public_relay_approved"] = False
                    state["public_relay_reason"] = reason
                    state["public_relay_signal"] = {}
                    state["public_relay_overlap_level"] = overlap_level
                    state["relay_decision"] = {
                        "approved": False,
                        "reason": reason,
                        "relay_style": "normal",
                        "overlap_level": overlap_level,
                        "candidate_reason": reason,
                    }
                    self.room_context.record_relay_decision(
                        utterance_id=str(state.get("utterance_id") or ""),
                        speaker_id=speaker_id,
                        relay_style="normal",
                        decision="suppress",
                        reason=reason,
                        overlap_level=overlap_level,
                        delivery_mode="source_transcript_only",
                    )
                    logger.info(
                        "BRSE relay translation disabled room=%s speaker=%s utterance=%s "
                        "route=%s->%s route_mode=%s reason=%s room_languages=%s",
                        self.room_id,
                        speaker_id,
                        state["utterance_id"],
                        src_lang,
                        target_lang,
                        state.get("route_mode"),
                        reason,
                        ",".join(self.room_languages),
                    )
                logger.info(
                    "BRSE source transcript completed room=%s speaker=%s utterance=%s "
                    "route=%s->%s chars=%d tokens=%s duration_ms=%s generation=%d "
                    "relay_style=%s blocked=%s overlap_level=%s public_relay=%s "
                    "public_reason=%s pending_relays=%d",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    src_lang,
                    target_lang,
                    len(normalized_text),
                    signal.get("meaningful_tokens"),
                    state.get("speech_duration_ms"),
                    generation,
                    state.get("relay_style", "normal"),
                    state.get("source_blocked_for_overlap"),
                    state.get("public_relay_overlap_level"),
                    state.get("public_relay_approved"),
                    state.get("public_relay_reason"),
                    self._pending_relay_count(),
                )
                logger.info(
                    "BRSE source transcript handed to relay policy room=%s speaker=%s "
                    "utterance=%s relay_source_chars=%d relay_style=%s",
                    self.room_id,
                    speaker_id,
                    state["utterance_id"],
                    len(str(state.get("relay_source_text") or "")),
                    state.get("relay_style", "normal"),
                )
                if self.silent_summary_mode:
                    logger.info(
                        "BRSE silent listener source captured room=%s speaker=%s utterance=%s "
                        "chars=%d summary_ready=True relay_output_enabled=False",
                        self.room_id,
                        speaker_id,
                        state["utterance_id"],
                        len(normalized_text),
                    )
                asyncio.create_task(
                    self._publish_source_final(
                        speaker_id,
                        state["utterance_id"],
                        generation,
                    )
                )
                if state.get("route_mode") == "multi_language_text_caption":
                    asyncio.create_task(
                        self._publish_multi_language_text_translations(
                            speaker_id=speaker_id,
                            utterance_id=state["utterance_id"],
                            generation=generation,
                        )
                    )
                elif state.get("route_mode") == "multi_language_source_capture_no_audience":
                    logger.info(
                        "BRSE multi-language text relay skipped room=%s speaker=%s utterance=%s "
                        "src=%s room_languages=%s reason=no_active_cross_language_audience",
                        self.room_id,
                        speaker_id,
                        state["utterance_id"],
                        src_lang,
                        ",".join(self.room_languages),
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

        def approve_transcript_for_relay(text: str, item_id: Optional[str]) -> Optional[Dict[str, Any]]:
            if not is_current_callback():
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
            if not self.relay_output_enabled:
                logger.info(
                    "BRSE relay response suppressed by mode room=%s speaker=%s utterance=%s "
                    "brse_mode=%s source_chars=%d",
                    self.room_id,
                    speaker_id,
                    state.get("utterance_id"),
                    self.brse_mode,
                    len(state.get("source_text") or text or ""),
                )
                return None
            if not state.get("relay_translation_enabled", True):
                logger.info(
                    "BRSE relay response skipped room=%s speaker=%s utterance=%s "
                    "route=%s->%s route_mode=%s reason=same_language_no_translation_required "
                    "source_chars=%d",
                    self.room_id,
                    speaker_id,
                    state.get("utterance_id"),
                    src_lang,
                    target_lang,
                    state.get("route_mode"),
                    len(state.get("source_text") or text or ""),
                )
                return None
            if not self._public_relay_is_approved(
                speaker_id=speaker_id,
                state=state,
                kind="source_approval",
            ):
                router.clear_queue()
                return None
            if not self._public_relay_is_fresh(
                speaker_id=speaker_id,
                state=state,
                kind="source_approval",
            ):
                router.clear_queue()
                return None
            if speaker_id in self.overlap.blocked_speakers and state.get("relay_style") != "summary":
                logger.info(
                    "BRSE relay source queued behind active focus room=%s speaker=%s utterance=%s "
                    "focus=%s generation=%d",
                    self.room_id,
                    speaker_id,
                    state.get("utterance_id"),
                    self.relay_focus_speaker_id,
                    generation,
                )
            if not self._source_state_can_relay(
                speaker_id=speaker_id,
                state=state,
                generation=generation,
                src_lang=src_lang,
                target_lang=target_lang,
                response_source_id=state.get("utterance_id"),
                kind="source_approval",
            ):
                can_queue_behind_focus = (
                    self.relay_focus_speaker_id != speaker_id
                    and state.get("generation") == generation
                    and state.get("src_lang") == src_lang
                    and state.get("target_lang") == target_lang
                    and self._relay_route_is_still_valid(
                        speaker_id=speaker_id,
                        src_lang=src_lang,
                        target_lang=target_lang,
                    )
                    and self._source_state_is_valid_for_output(state)
                )
                if can_queue_behind_focus:
                    return {
                        "relay_source_id": str(state["utterance_id"]),
                        "source_text": state.get("relay_source_text") or state.get("source_text") or text,
                        "relay_style": state.get("relay_style", "normal"),
                    }
                return None
            return {
                "relay_source_id": str(state["utterance_id"]),
                "source_text": state.get("relay_source_text") or state.get("source_text") or text,
                "relay_style": state.get("relay_style", "normal"),
            }

        def on_text_delta(delta: str) -> None:
            if not delta:
                return
            state = relay_state_for_response("relay_partial")
            if state is None:
                return
            state["brse_text"] = f"{state['brse_text']}{delta}"
            if not self._apply_public_output_text_gate(
                speaker_id=speaker_id,
                state=state,
                router=router,
                final=False,
            ):
                return
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
            if final_text and self._apply_public_output_text_gate(
                speaker_id=speaker_id,
                state=state,
                router=router,
                final=True,
            ):
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

        def on_response_done(relay_source_id: Optional[str]) -> None:
            if relay_source_id is None:
                return
            state = self.transcript_states.get(relay_source_id)
            if state is not None and not state.get("public_output_ready"):
                reason = str(state.get("public_output_gate_reason") or "relay_completed_without_public_text")
                asyncio.create_task(router.reject_public_output(reason=reason))
            asyncio.create_task(
                self._cleanup_relay_state_after_response(
                    speaker_id=speaker_id,
                    utterance_id=relay_source_id,
                    generation=generation,
                )
            )

        def on_relay_response_starting(relay_source_id: str) -> None:
            if not is_current_callback():
                return
            state = self.transcript_states.get(relay_source_id)
            if state is None:
                return
            if not self._public_relay_is_approved(
                speaker_id=speaker_id,
                state=state,
                kind="response_start",
            ):
                asyncio.create_task(router.reject_public_output(reason="public_relay_not_approved"))
                return
            if not self._public_relay_is_fresh(
                speaker_id=speaker_id,
                state=state,
                kind="response_start",
            ):
                asyncio.create_task(router.reject_public_output(reason="stale_public_relay"))
                return
            self._prepare_public_output_gate(router=router, state=state)

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
                logger.info(
                    "BRSE input capturing while preserving relay output room=%s speaker=%s "
                    "route=%s->%s generation=%d pending_relays=%d",
                    self.room_id,
                    speaker_id,
                    src_lang,
                    target_lang,
                    generation,
                    self._pending_relay_count(),
                )
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
        client.on_response_done = on_response_done
        client.on_relay_response_starting = on_relay_response_starting
        client.can_start_relay_response = (
            lambda relay_source_id: self._relay_source_can_start(
                speaker_id=speaker_id,
                generation=generation,
                relay_source_id=relay_source_id,
            )
        )
        client.should_drop_pending_relay = (
            lambda relay_source_id: self._relay_source_should_drop_pending(
                speaker_id=speaker_id,
                generation=generation,
                relay_source_id=relay_source_id,
            )
        )

    async def _capture_audio_delta(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        generation: int,
        router: OutputRouter,
        encoded: str,
    ) -> None:
        if not self.relay_audio_enabled:
            logger.debug(
                "Suppressing BRSE audio delta by output mode room=%s speaker=%s generation=%d "
                "brse_mode=%s brse_output_mode=%s",
                self.room_id,
                speaker_id,
                generation,
                self.brse_mode,
                self.brse_output_mode,
            )
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is not None and not state.get("relay_translation_enabled", True):
            router.clear_queue()
            return
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
        if not self.relay_audio_enabled:
            logger.debug(
                "Suppressing BRSE audio flush by output mode room=%s speaker=%s generation=%d "
                "brse_mode=%s brse_output_mode=%s",
                self.room_id,
                speaker_id,
                generation,
                self.brse_mode,
                self.brse_output_mode,
            )
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is not None and not state.get("relay_translation_enabled", True):
            router.clear_queue()
            return
        if state is None or not self._source_state_is_valid_for_output(state):
            router.clear_queue()
            return
        await router.flush()

    async def _cleanup_relay_state_after_response(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        await asyncio.sleep(_RELAY_STATE_CLEANUP_DELAY_SECONDS)
        state = self.transcript_states.get(utterance_id)
        if state is None:
            return
        if state.get("speaker_id") != speaker_id or state.get("generation") != generation:
            return
        if state.get("brse_text") and not state.get("relay_final_published"):
            await asyncio.sleep(_RELAY_STATE_CLEANUP_DELAY_SECONDS)
            state = self.transcript_states.get(utterance_id)
            if state is None:
                return
            if state.get("speaker_id") != speaker_id or state.get("generation") != generation:
                return
        if self.transcript_state.get(speaker_id) is state:
            self.transcript_state.pop(speaker_id, None)
        self.transcript_states.pop(utterance_id, None)
        logger.debug(
            "BRSE relay utterance state closed room=%s speaker=%s utterance=%s generation=%d",
            self.room_id,
            speaker_id,
            utterance_id,
            generation,
        )

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
        if not state.get("relay_translation_enabled", True):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason="same_language_no_translation_required",
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
        if not state.get("public_relay_approved"):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason=str(state.get("public_relay_reason") or "public_relay_not_approved"),
            )
        if not self._public_relay_is_fresh(
            speaker_id=speaker_id,
            state=state,
            kind=kind,
        ):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason=str(state.get("public_relay_reason") or "stale_public_relay"),
            )
        if state.get("public_output_rejected"):
            return self._log_source_gate_drop(
                speaker_id=speaker_id,
                state=state,
                kind=kind,
                reason=str(state.get("public_output_gate_reason") or "public_output_rejected"),
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
        if src_lang not in self.room_languages or target_lang not in self.room_languages:
            return False
        if src_lang == target_lang:
            return False
        resolved_target = resolve_relay_target_language(
            src_lang,
            self.room_languages,
            audience_languages=self._audience_languages_for_speaker(speaker_id),
        )
        return resolved_target == target_lang

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
        speaker_id: str,
        target_lang: Optional[str] = None,
    ) -> tuple[bool, str, str, Dict[str, Any]]:
        decision = self.policy.assess_source(
            text,
            duration_ms=duration_ms,
            final=final,
            speaker_id=speaker_id,
            target_lang=target_lang,
        )
        return (
            decision.accepted,
            decision.reason,
            decision.normalized_text,
            decision.signal,
        )

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
            speaker_id=speaker_id,
            target_lang=state.get("target_lang"),
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

    async def _publish_multi_language_text_translations(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        if not self.relay_text_enabled:
            logger.info(
                "BRSE multi-language text relay skipped room=%s speaker=%s utterance=%s "
                "reason=relay_text_disabled brse_mode=%s",
                self.room_id,
                speaker_id,
                utterance_id,
                self.brse_mode,
            )
            return

        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        if state is None or not self._source_state_is_valid_for_output(state):
            return

        source_text = str(state.get("source_text") or "").strip()
        src_lang = str(state.get("src_lang") or "")
        if not source_text or src_lang not in self.room_languages:
            return

        target_languages = self._multi_language_text_target_languages(speaker_id, src_lang)
        if not target_languages:
            logger.info(
                "BRSE multi-language text relay skipped room=%s speaker=%s utterance=%s "
                "src=%s room_languages=%s reason=no_active_cross_language_audience",
                self.room_id,
                speaker_id,
                utterance_id,
                src_lang,
                ",".join(self.room_languages),
            )
            return

        logger.info(
            "BRSE multi-language text relay translating room=%s speaker=%s utterance=%s "
            "src=%s targets=%s relay_audio_enabled=%s brse_output_mode=%s",
            self.room_id,
            speaker_id,
            utterance_id,
            src_lang,
            ",".join(target_languages),
            self.relay_audio_enabled,
            self.brse_output_mode,
        )

        published_targets: list[str] = []
        for target_lang in target_languages:
            audience_ids = sorted(self._audience_ids_for_target(speaker_id, target_lang))
            if not audience_ids:
                continue

            translated_text = await translate_caption_text(
                text=source_text,
                src_lang=src_lang,
                tgt_lang=target_lang,
                api_key=self.settings.openai_api_key,
            )
            if not translated_text:
                logger.warning(
                    "BRSE multi-language text relay translation empty room=%s speaker=%s "
                    "utterance=%s src=%s target=%s",
                    self.room_id,
                    speaker_id,
                    utterance_id,
                    src_lang,
                    target_lang,
                )
                continue

            delivery_plan = self.delivery.plan_publish(
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                relay_style="normal",
                final=True,
                policy_reason="multi_language_text_caption",
            )
            if not delivery_plan.text_enabled:
                return

            latency_ms = int(max(0.0, time.monotonic() - state["started_at"]) * 1000)
            relay_decision = {
                "approved": True,
                "reason": "multi_language_text_caption",
                "relay_style": "normal",
                "overlap_level": state.get("public_relay_overlap_level", _OVERLAP_LEVEL_SINGLE),
                "candidate_reason": "multi_language_text_caption",
            }
            await self.publisher.publish_relay_transcript_final(
                transcript_id=f"{utterance_id}::relay::{target_lang}",
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=self._speaker_name(speaker_id),
                src_lang=src_lang,
                target_lang=target_lang,
                source_text=source_text,
                brse_text=translated_text,
                created_at=state["created_at"],
                brse_livekit_identity=self.runtime.livekit_identity,
                audio_track_name=None,
                audio_track=self._disabled_audio_track_descriptor(
                    speaker_id=speaker_id,
                    src_lang=src_lang,
                    target_lang=target_lang,
                ),
                audience_participant_ids=audience_ids,
                latency_ms=latency_ms,
                relay_style="normal",
                relay_focus=self._relay_focus_payload(speaker_id),
                overlap=self._overlap_payload(speaker_id),
                relay_decision=relay_decision,
                delivery=delivery_plan.as_payload(),
            )
            self.room_context.record_relay_output(
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                target_lang=target_lang,
                text=translated_text,
                relay_style="normal",
                created_at=state["created_at"],
            )
            self.room_context.record_relay_decision(
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                relay_style="normal",
                decision="publish_final",
                reason=delivery_plan.reason,
                overlap_level=str(state.get("public_relay_overlap_level") or _OVERLAP_LEVEL_SINGLE),
                delivery_mode=delivery_plan.delivery_mode,
            )
            published_targets.append(target_lang)

        if published_targets:
            state["relay_final_published"] = True
            state["delivery_mode"] = "text_only"
            logger.info(
                "BRSE multi-language text relay published room=%s speaker=%s utterance=%s "
                "targets=%s source_chars=%d relay_audio_enabled=False",
                self.room_id,
                speaker_id,
                utterance_id,
                ",".join(published_targets),
                len(source_text),
            )

    async def _publish_partial(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        if not self.relay_output_enabled:
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        target_lang = state.get("target_lang") if state is not None else None
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None:
            return
        if not state.get("relay_translation_enabled", True):
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        if not self._source_state_is_valid_for_output(state) or not state["brse_text"]:
            router.clear_queue()
            return
        delivery_plan = self.delivery.plan_publish(
            speaker_id=speaker_id,
            utterance_id=state["utterance_id"],
            relay_style=state.get("relay_style", "normal"),
            final=False,
            policy_reason=str(state.get("public_output_policy_reason") or "text_gate_passed"),
        )
        if not delivery_plan.text_enabled:
            return
        state["delivery_mode"] = delivery_plan.delivery_mode
        state["delivery"] = delivery_plan.as_payload()
        self.room_context.record_relay_decision(
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            relay_style=state.get("relay_style", "normal"),
            decision="publish_partial",
            reason=delivery_plan.reason,
            overlap_level=str(state.get("public_relay_overlap_level") or _OVERLAP_LEVEL_SINGLE),
            delivery_mode=delivery_plan.delivery_mode,
        )

        await self.publisher.publish_relay_transcript_partial(
            transcript_id=state["relay_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            target_lang=target_lang,
            source_text=state.get("relay_source_text") or state["source_text"],
            brse_text=state["brse_text"],
            created_at=state["created_at"],
            brse_livekit_identity=self.runtime.livekit_identity,
            audio_track_name=router.audio_track_name(),
            audio_track=router.track_descriptor(),
            audience_participant_ids=sorted(self.speaker_audiences.get(speaker_id, frozenset())),
            relay_style=state.get("relay_style", "normal"),
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
            relay_decision=state.get("relay_decision"),
            delivery=delivery_plan.as_payload(),
        )

    async def _publish_final(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> None:
        if not self.relay_output_enabled:
            return
        state = self._transcript_state_for_publish(speaker_id, utterance_id, generation)
        target_lang = state.get("target_lang") if state is not None else None
        router = self.routers.get(speaker_id)
        if state is None or target_lang is None or router is None or not state["brse_text"]:
            return
        if not state.get("relay_translation_enabled", True):
            return
        if not self._runtime_generation_matches(speaker_id, generation, router):
            return
        if not self._source_state_is_valid_for_output(state):
            router.clear_queue()
            return
        delivery_plan = self.delivery.plan_publish(
            speaker_id=speaker_id,
            utterance_id=state["utterance_id"],
            relay_style=state.get("relay_style", "normal"),
            final=True,
            policy_reason=str(state.get("public_output_policy_reason") or "text_gate_passed"),
        )
        if not delivery_plan.text_enabled:
            return
        state["delivery_mode"] = delivery_plan.delivery_mode
        state["delivery"] = delivery_plan.as_payload()

        latency_ms = int(max(0.0, time.monotonic() - state["started_at"]) * 1000)
        logger.info(
            "BRSE relay final room=%s speaker=%s utterance=%s route=%s->%s "
            "source_chars=%d relay_chars=%d latency_ms=%d audience=%d generation=%d "
            "relay_style=%s overlap_level=%s relay_audio_enabled=%s",
            self.room_id,
            speaker_id,
            state["utterance_id"],
            state["src_lang"],
            target_lang,
            len(state.get("relay_source_text") or state["source_text"]),
            len(state["brse_text"]),
            latency_ms,
            len(self.speaker_audiences.get(speaker_id, frozenset())),
            generation,
            state.get("relay_style", "normal"),
            state.get("public_relay_overlap_level", _OVERLAP_LEVEL_SINGLE),
            self.relay_audio_enabled,
        )
        await self.publisher.publish_relay_transcript_final(
            transcript_id=state["relay_transcript_id"],
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=self._speaker_name(speaker_id),
            src_lang=state["src_lang"],
            target_lang=target_lang,
            source_text=state.get("relay_source_text") or state["source_text"],
            brse_text=state["brse_text"],
            created_at=state["created_at"],
            brse_livekit_identity=self.runtime.livekit_identity,
            audio_track_name=router.audio_track_name(),
            audio_track=router.track_descriptor(),
            audience_participant_ids=sorted(self.speaker_audiences.get(speaker_id, frozenset())),
            latency_ms=latency_ms,
            relay_style=state.get("relay_style", "normal"),
            relay_focus=self._relay_focus_payload(speaker_id),
            overlap=self._overlap_payload(speaker_id),
            relay_decision=state.get("relay_decision"),
            delivery=delivery_plan.as_payload(),
        )

        state["relay_final_published"] = True
        self.room_context.record_relay_output(
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            target_lang=target_lang,
            text=state["brse_text"],
            relay_style=state.get("relay_style", "normal"),
            created_at=state["created_at"],
        )
        self.room_context.record_relay_decision(
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            relay_style=state.get("relay_style", "normal"),
            decision="publish_final",
            reason=delivery_plan.reason,
            overlap_level=str(state.get("public_relay_overlap_level") or _OVERLAP_LEVEL_SINGLE),
            delivery_mode=delivery_plan.delivery_mode,
        )
        if state.get("relay_style") == "summary":
            window = self.overlap.window
            logger.info(
                "BRSE overlap summary relay published room=%s speaker=%s utterance=%s "
                "target=%s window=%s source_items=%s speakers=%s relay_chars=%d "
                "summary_targets=%s",
                self.room_id,
                speaker_id,
                state["utterance_id"],
                target_lang,
                state.get("summary_window_id") or state.get("overlap_window_id") or "-",
                state.get("summary_item_count"),
                len(state.get("summary_speaker_ids") or []),
                len(state["brse_text"]),
                sorted(window.summary_target_langs) if window is not None else [],
            )
            expected_targets = {
                language
                for language in self._audience_languages_for_speaker(speaker_id)
                if language != state.get("src_lang")
            }
            if not expected_targets and target_lang:
                expected_targets = {target_lang}
            if window is None or expected_targets.issubset(window.summary_target_langs):
                self._close_overlap_understanding_window(
                    reason="summary_relay_published",
                    summary_utterance_id=state["utterance_id"],
                )

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
        audio_track = None if router is None else router.track_descriptor()
        if output_suppressed and self.relay_output_enabled:
            audio_track = None
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

    def _audience_languages_for_speaker(self, speaker_id: str) -> Set[str]:
        return {
            str(payload.get("language"))
            for participant_id, payload in self.participants.items()
            if participant_id != speaker_id
            and self._is_active_human_participant(payload)
            and payload.get("language") in self.room_languages
        }

    def _multi_language_text_target_languages(
        self,
        speaker_id: str,
        src_lang: str,
    ) -> tuple[str, ...]:
        if len(self.room_languages) <= 2:
            return tuple()
        audience_languages = self._audience_languages_for_speaker(speaker_id)
        return tuple(
            language
            for language in self.room_languages
            if language != src_lang and language in audience_languages
        )

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

    def _disabled_audio_track_descriptor(
        self,
        *,
        speaker_id: str,
        src_lang: str,
        target_lang: str,
    ) -> Dict[str, Any]:
        return {
            "model": "brse_text_only_relay",
            "mode": "disabled",
            "canonical": False,
            "track_available": False,
            "track_name": None,
            "track_sid": None,
            "participant_id": BRSE_PARTICIPANT_ID,
            "participant_kind": "virtual_brse",
            "livekit_identity": self.runtime.livekit_identity,
            "speaker_id": speaker_id,
            "source_language": src_lang,
            "target_language": target_lang,
            "output_suppressed": True,
            "suppressed_reason": self.delivery.suppressed_audio_reason,
            "relay_audio_enabled": False,
            "brse_output_mode": self.brse_output_mode,
            "stats": {
                "output_enabled": False,
                "output_suppressed": True,
                "suppressed_reason": self.delivery.suppressed_audio_reason,
                "brse_output_mode": self.brse_output_mode,
            },
        }

    def _transcript_state_for_publish(
        self,
        speaker_id: str,
        utterance_id: str,
        generation: int,
    ) -> Optional[Dict[str, Any]]:
        state = self.transcript_states.get(utterance_id)
        if state is None:
            return None
        if state.get("speaker_id") != speaker_id:
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

    def _open_transcript_state(
        self,
        *,
        speaker_id: str,
        src_lang: str,
        target_lang: str,
        generation: int,
    ) -> Dict[str, Any]:
        utterance_id = f"seg_{uuid.uuid4().hex[:12]}"
        state = {
            "utterance_id": utterance_id,
            "speaker_id": speaker_id,
            "source_transcript_id": f"{utterance_id}::source",
            "relay_transcript_id": f"{utterance_id}::relay::{target_lang}",
            "source_text": "",
            "relay_source_text": "",
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
            "relay_translation_enabled": self.speaker_relay_enabled.get(speaker_id, True),
            "route_mode": self.speaker_route_modes.get(speaker_id, "cross_language"),
            "relay_style": "normal",
            "relay_candidate_reason": None,
            "relay_candidate_metadata": {},
            "public_relay_approved": False,
            "public_relay_reason": None,
            "public_relay_signal": {},
            "public_relay_overlap_level": _OVERLAP_LEVEL_SINGLE,
            "relay_decision": {},
            "public_output_ready": False,
            "public_output_rejected": False,
            "public_output_gate_reason": None,
            "public_output_gate_logged": False,
            "public_output_policy_reason": None,
            "delivery_mode": None,
            "delivery": {},
            "overlap_window_id": None,
            "summary_window_id": None,
            "summary_item_count": 0,
            "summary_speaker_ids": [],
        }
        self.transcript_state[speaker_id] = state
        self.transcript_states[utterance_id] = state
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
            return self._mark_meeting_languages_not_ready("missing room_languages")

        normalized: list[str] = []
        invalid: list[str] = []
        duplicates: list[str] = []
        for lang in meeting_languages:
            if not isinstance(lang, str):
                continue
            language = lang.strip().lower()
            if language not in _SUPPORTED_LANGS:
                invalid.append(lang)
                continue
            if language in normalized:
                duplicates.append(language)
                continue
            normalized.append(language)

        if invalid:
            return self._mark_meeting_languages_not_ready(
                f"unsupported room_languages={invalid!r}"
            )
        if duplicates:
            logger.info(
                "Room %s BRSE duplicate room_languages removed: duplicates=%s normalized=%s",
                self.room_id,
                duplicates,
                normalized,
            )
        if not normalized:
            return self._mark_meeting_languages_not_ready(
                f"invalid room_languages={normalized!r}"
            )

        normalized_tuple = tuple(normalized)
        changed = normalized_tuple != self.room_languages or not self._meeting_languages_ready

        self.room_languages = normalized_tuple
        self.meeting_languages = normalized_tuple
        self._meeting_languages_ready = True
        if changed:
            logger.info(
                "Room %s BRSE room language context set to %s",
                self.room_id,
                ",".join(normalized_tuple),
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
