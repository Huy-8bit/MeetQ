from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

import websockets

from server.shared.audio import AudioInput, MicInput
from server.brain.realtime.client import REALTIME_URL_TEMPLATE, RealtimeClient
from server.brain.realtime.session_config import (
    INTERPRETER_FINAL_TRANSCRIPT_HOLD_MS,
    INTERPRETER_INPUT_TRANSCRIPTION_MODEL,
    INTERPRETER_INPUT_TRANSCRIPTION_PROMPT,
    INTERPRETER_TEMPERATURE,
    INTERPRETER_VAD_CONFIG,
    INTERPRETER_SEND_QUEUE_MAXSIZE,
    build_interpreter_instructions,
    build_interpreter_silent_listener_instructions,
    build_interpreter_summary_instructions,
    build_interpreter_session_update,
)

logger = logging.getLogger(__name__)


class InterpreterRealtimeClient(RealtimeClient):
    """
    Interpreter-specific wrapper that keeps audio output enabled in the OpenAI
    session while preventing any local SpeakerPlayer playback on the server.
    """

    def __init__(self, *args, **kwargs):
        self.request_audio_output = kwargs.pop("request_audio_output", True)
        self.silent_listener_mode = kwargs.pop("silent_listener_mode", False)
        self.meeting_languages = kwargs.pop("meeting_languages", None)
        self.input_transcription_model = kwargs.pop(
            "input_transcription_model",
            INTERPRETER_INPUT_TRANSCRIPTION_MODEL,
        )
        self.input_transcription_prompt = kwargs.pop(
            "input_transcription_prompt",
            INTERPRETER_INPUT_TRANSCRIPTION_PROMPT,
        )
        kwargs["enable_speaker"] = False
        super().__init__(*args, **kwargs)
        self._deterministic_routing = self.src_lang != "auto" and self.tgt_lang != "auto"
        self._session_ready_event: Optional[asyncio.Event] = None
        self._speech_started_at: Optional[float] = None
        self._speech_stopped_at: Optional[float] = None
        self._response_started_at: Optional[float] = None
        self._first_text_delta_at: Optional[float] = None
        self._first_audio_delta_at: Optional[float] = None
        self._utterance_committed_at: Optional[float] = None
        self._response_audio_chunks: int = 0
        self._send_queue_drops: int = 0
        self._send_queue_drop_log_at: float = 0.0
        self._conversation_item_ids: list[str] = []
        self._conversation_item_id_set: set[str] = set()
        self._accepted_input_item_ids: set[str] = set()
        self._cancelled_response_ids: set[str] = set()
        self._pending_relay_requests: list[Dict[str, Any]] = []
        self._suppress_response_output = False
        self._active_input_item_id: Optional[str] = None
        self._pending_response_source_id: Optional[str] = None
        self._active_response_source_id: Optional[str] = None
        self._current_response_had_text = False
        self._using_audio_transcript_text = False
        self._text_done_emitted = False
        self._audio_transcript_text_parts: list[str] = []
        self.on_input_transcript_delta: Callable[[str], None] = lambda t: None
        self.on_transcript_complete: Callable[[str], None] = lambda t: None
        self.on_input_audio_committed: Callable[[Optional[str]], None] = lambda item_id: None
        self.approve_transcript_for_relay: Callable[[str, Optional[str]], Any] = (
            lambda _text, item_id: item_id or "validated_source_transcript"
        )
        self.on_text_delta: Callable[[str], None] = lambda t: None
        self.on_text_done: Callable[[str], None] = lambda t: None
        self.on_audio_delta: Callable[[str], None] = lambda enc: None
        self.on_audio_done: Callable[[], None] = lambda: None
        self.on_status_change: Callable[[str], None] = lambda s: None
        self.on_speech_started: Callable[[], None] = lambda: None
        self.on_speech_stopped: Callable[[Optional[int]], None] = lambda duration_ms: None
        self.on_error: Callable[[Dict[str, Any]], None] = lambda err: None
        self.on_response_done: Callable[[Optional[str]], None] = lambda source_id: None
        self.can_start_relay_response: Callable[[str], bool] = lambda _relay_source_id: True
        self.should_drop_pending_relay: Callable[[str], bool] = lambda _relay_source_id: False
        self.on_relay_response_starting: Callable[[str], None] = lambda _relay_source_id: None

    def _current_instructions(self) -> str:
        effective_src = self.src_lang
        if effective_src == "auto" and self._last_detected_src:
            effective_src = self._last_detected_src
        if self.silent_listener_mode:
            return build_interpreter_silent_listener_instructions(
                effective_src,
                self.tgt_lang,
                meeting_languages=self.meeting_languages,
            )
        return build_interpreter_instructions(
            effective_src,
            self.tgt_lang,
            meeting_languages=self.meeting_languages,
        )

    async def _run_session(self) -> None:
        url = REALTIME_URL_TEMPLATE.format(model=self.model)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        self._stat_transcripts = 0
        self._stat_translations = 0
        self._stat_audio_chunks = 0
        self._stat_detect_failed = 0
        self._player = None
        self._speech_started_at = None
        self._speech_stopped_at = None
        self._response_started_at = None
        self._first_text_delta_at = None
        self._first_audio_delta_at = None
        self._utterance_committed_at = None
        self._response_audio_chunks = 0
        self._send_queue_drops = 0
        self._send_queue_drop_log_at = 0.0
        self._conversation_item_ids = []
        self._conversation_item_id_set.clear()
        self._accepted_input_item_ids.clear()
        self._cancelled_response_ids.clear()
        self._pending_relay_requests.clear()
        self._suppress_response_output = False
        self._active_input_item_id = None
        self._pending_response_source_id = None
        self._active_response_source_id = None
        self._current_response_had_text = False
        self._using_audio_transcript_text = False
        self._text_done_emitted = False
        self._audio_transcript_text_parts = []
        self._session_ready_event = asyncio.Event()
        self._set_audio_consumer_ready(False)
        if self._deterministic_routing:
            self._last_detected_src = self.src_lang

        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
            ) as ws:
                self._ws = ws
                self._log(f"ws_connected model={self.model}")
                await ws.send(json.dumps(self._session_update_payload()))
                self._log(
                    "interpreter.session_config "
                    f"src={self.src_lang} tgt={self.tgt_lang} "
                    f"meeting_languages={self.meeting_languages} "
                    f"vad={INTERPRETER_VAD_CONFIG} "
                    f"transcription_model={self.input_transcription_model} "
                    f"transcription_prompt_chars={len(self.input_transcription_prompt)} "
                    f"temp={INTERPRETER_TEMPERATURE}"
                )

                try:
                    await asyncio.gather(
                        self._send_audio(ws),
                        self._receive_events(ws),
                    )
                except asyncio.CancelledError:
                    pass
                finally:
                    self._ws = None
        finally:
            self._set_audio_consumer_ready(False)
            self._session_ready_event = None
            self._player = None

    async def _send_audio(self, ws) -> None:
        loop = asyncio.get_running_loop()
        audio_in: AudioInput = self._audio_input or MicInput(
            device=self.mic_device,
            sample_rate=self.sample_rate,
        )
        audio_q: asyncio.Queue[Optional[str]] = asyncio.Queue(
            maxsize=INTERPRETER_SEND_QUEUE_MAXSIZE
        )
        self._set_audio_consumer_ready(False)

        def _offer_audio(encoded: Optional[str]) -> None:
            if encoded is None:
                try:
                    audio_q.put_nowait(None)
                except asyncio.QueueFull:
                    try:
                        audio_q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    audio_q.put_nowait(None)
                return

            if audio_q.full():
                try:
                    audio_q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                else:
                    self._send_queue_drops += 1
                    self._log_send_queue_drop()
            try:
                audio_q.put_nowait(encoded)
            except asyncio.QueueFull:
                self._send_queue_drops += 1
                self._log_send_queue_drop()

        def _capture_thread() -> None:
            audio_in.start()
            try:
                for chunk in audio_in.stream_frames():
                    encoded = base64.b64encode(chunk).decode("utf-8")
                    loop.call_soon_threadsafe(_offer_audio, encoded)
            finally:
                self._set_audio_consumer_ready(False)
                self._stop_audio_input(audio_in, close_stream=False)
                loop.call_soon_threadsafe(_offer_audio, None)

        threading.Thread(target=_capture_thread, daemon=True).start()
        self._log(
            "Interpreter audio capture primed "
            f"input={type(audio_in).__name__} src={self.src_lang} tgt={self.tgt_lang}"
        )

        try:
            while self._running:
                ready_event = self._session_ready_event
                if ready_event is not None and ready_event.is_set():
                    self._set_audio_consumer_ready(True)
                if ready_event is not None and not ready_event.is_set():
                    try:
                        await asyncio.wait_for(ready_event.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    self._set_audio_consumer_ready(True)
                    continue

                try:
                    encoded = await asyncio.wait_for(audio_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if encoded is None:
                    break
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": encoded,
                }))
        finally:
            self._set_audio_consumer_ready(False)
            self._stop_audio_input(audio_in, close_stream=False)

    async def _handle_event(self, ws, etype: str, event: dict) -> None:
        if etype == "session.created":
            sid = event.get("session", {}).get("id", "?")
            self._log(f"session.created id={sid}")

        elif etype == "session.updated":
            if self._session_ready_event is not None and not self._session_ready_event.is_set():
                self._session_ready_event.set()
                self._set_audio_consumer_ready(True)
            self._log("session.updated — interpreter config applied")

        elif etype == "conversation.item.created":
            self._remember_conversation_item_from_event(event)

        elif etype == "response.output_item.added":
            self._remember_conversation_item_from_event(event)

        elif etype == "response.output_item.done":
            self._remember_conversation_item_from_event(event)

        elif etype == "input_audio_buffer.speech_started":
            now = time.monotonic()
            output_in_progress = self._assistant_speaking or self._current_response_id is not None
            self._speech_started_at = now
            self._speech_stopped_at = None
            self._utterance_committed_at = None
            self._active_input_item_id = None
            if not output_in_progress:
                self._response_started_at = None
                self._first_text_delta_at = None
                self._first_audio_delta_at = None
                self._response_audio_chunks = 0
                self._pending_response_source_id = None
                self._active_response_source_id = None
            self._log(
                f"speech_started src={self.src_lang} tgt={self.tgt_lang} "
                f"output_in_progress={output_in_progress} pending_relays={len(self._pending_relay_requests)}"
            )
            self.on_speech_started()
            self.on_status_change("capturing")
            if output_in_progress:
                self._log(
                    "full_duplex_continue_output_on_new_speech "
                    f"active_response_id={self._current_response_id or 'n/a'}"
                )

        elif etype == "input_audio_buffer.speech_stopped":
            now = time.monotonic()
            self._speech_stopped_at = now
            duration_ms = None
            if self._speech_started_at is not None:
                duration_ms = int((now - self._speech_started_at) * 1000)
            if duration_ms is None:
                self._log("speech_stopped")
            else:
                self._log(f"speech_stopped duration_ms={duration_ms}")
            self.on_speech_stopped(duration_ms)

        elif etype == "input_audio_buffer.committed":
            self._remember_conversation_item_from_event(event)
            now = time.monotonic()
            self._utterance_committed_at = now
            item_id = self._input_item_id_from_event(event)
            self._active_input_item_id = item_id
            if item_id:
                self._accepted_input_item_ids.add(item_id)
            metric_bits = []
            if item_id:
                metric_bits.append(f"item_id={item_id}")
            if self._speech_started_at is not None:
                metric_bits.append(
                    f"from_speech_started_ms={int((now - self._speech_started_at) * 1000)}"
                )
            if self._speech_stopped_at is not None:
                metric_bits.append(
                    f"from_speech_stopped_ms={int((now - self._speech_stopped_at) * 1000)}"
                )
            self._log("input_audio_buffer.committed " + " ".join(metric_bits))
            self.on_input_audio_committed(item_id)

        elif etype == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if delta and self._input_transcription_event_is_current(event):
                self.on_input_transcript_delta(delta)

        elif etype == "conversation.item.input_audio_transcription.completed":
            item_id = self._input_item_id_from_event(event)
            if not self._input_transcription_event_is_current(event):
                self._log(
                    "dropping_stale_input_transcript_completed "
                    f"item_id={item_id or 'n/a'} active_item_id={self._active_input_item_id or 'n/a'}"
                )
                return
            transcript = event.get("transcript", "").strip()
            if transcript:
                self._stat_transcripts += 1
                latency_bits = [f"chars={len(transcript)}"]
                if item_id:
                    latency_bits.append(f"item_id={item_id}")
                if self._speech_started_at is not None:
                    latency_bits.append(
                        f"from_speech_started_ms={int((time.monotonic() - self._speech_started_at) * 1000)}"
                    )
                if self._speech_stopped_at is not None:
                    latency_bits.append(
                        f"from_speech_stopped_ms={int((time.monotonic() - self._speech_stopped_at) * 1000)}"
                    )
                self._log(
                    "input_transcript_completed "
                    + " ".join(latency_bits)
                )
                if not self._deterministic_routing:
                    await self._handle_input_transcript_with_audio(ws, transcript)
                self.on_transcript_complete(transcript)
                relay_source_id = self.approve_transcript_for_relay(transcript, item_id)
                if relay_source_id:
                    relay_request = self._normalize_relay_approval(
                        relay_source_id,
                        default_source_text=transcript,
                    )
                    await self._hold_for_turn_completion(
                        relay_style=relay_request["relay_style"],
                    )
                    await self._create_response_from_source_transcript(
                        ws,
                        relay_request["source_text"],
                        relay_source_id=relay_request["relay_source_id"],
                        relay_style=relay_request["relay_style"],
                    )
                else:
                    self._log(
                        "input_transcript_rejected_for_relay "
                        f"item_id={item_id or 'n/a'} chars={len(transcript)}"
                    )
                    await self._handle_input_without_relay(
                        ws,
                        item_id=item_id,
                        reason="rejected_for_relay",
                    )
                if item_id:
                    self._accepted_input_item_ids.discard(item_id)
            else:
                self._log(
                    "empty_input_transcript_suppressed "
                    f"item_id={item_id or 'n/a'}"
                )
                await self._handle_input_without_relay(
                    ws,
                    item_id=item_id,
                    reason="empty_input_transcript",
                )
                if item_id:
                    self._accepted_input_item_ids.discard(item_id)

        elif etype == "conversation.item.input_audio_transcription.failed":
            item_id = self._input_item_id_from_event(event)
            if not self._input_transcription_event_is_current(event):
                return
            error = event.get("error") or {}
            self._log(
                "input_transcription_failed_suppressed "
                f"item_id={item_id or 'n/a'} error={error}"
            )
            await self._handle_input_without_relay(
                ws,
                item_id=item_id,
                reason="input_transcription_failed",
            )
            if item_id:
                self._accepted_input_item_ids.discard(item_id)

        elif etype == "response.created":
            self._current_response_id = event.get("response", {}).get("id")
            response_source_id = self._response_source_id_from_event(event)
            if not self._response_source_is_expected(response_source_id):
                self._log(
                    "suppressing_response_without_valid_source "
                    f"id={self._current_response_id or 'n/a'} "
                    f"source_id={response_source_id or 'n/a'} "
                    f"pending_source_id={self._pending_response_source_id or 'n/a'}"
                )
                if self._current_response_id:
                    self._cancelled_response_ids.add(self._current_response_id)
                self._suppress_response_output = True
                await self._cancel_response(ws)
                return
            if self._current_response_id in self._cancelled_response_ids:
                self._suppress_response_output = True
                logger.debug(
                    "Dropping created event for cancelled BRSE response id=%s",
                    self._current_response_id,
                )
                return
            else:
                self._suppress_response_output = False
            self._active_response_source_id = (
                response_source_id or self._pending_response_source_id
            )
            self._pending_response_source_id = None
            self.on_status_change("translating")
            self._assistant_speaking = True
            self._response_started_at = time.monotonic()
            self._first_text_delta_at = None
            self._first_audio_delta_at = None
            self._response_audio_chunks = 0
            self._current_response_had_text = False
            self._using_audio_transcript_text = False
            self._text_done_emitted = False
            self._audio_transcript_text_parts = []
            self._log(f"response.created id={self._current_response_id}")

        elif etype == "response.text.delta":
            if self._should_drop_response_event(etype, event):
                return
            if self._using_audio_transcript_text:
                return
            delta = event.get("delta", "")
            if delta:
                self._current_response_had_text = True
            if delta and self._first_text_delta_at is None:
                now = time.monotonic()
                self._first_text_delta_at = now
                metric_bits = []
                if self._response_started_at is not None:
                    metric_bits.append(
                        f"from_response_created_ms={int((now - self._response_started_at) * 1000)}"
                    )
                if self._speech_started_at is not None:
                    metric_bits.append(
                        f"from_speech_started_ms={int((now - self._speech_started_at) * 1000)}"
                    )
                if self._utterance_committed_at is not None:
                    metric_bits.append(
                        f"from_audio_committed_ms={int((now - self._utterance_committed_at) * 1000)}"
                    )
                self._log("first_text_delta " + " ".join(metric_bits))
            self.on_text_delta(delta)

        elif etype == "response.text.done":
            if self._should_drop_response_event(etype, event):
                return
            if self._using_audio_transcript_text:
                return
            text = event.get("text", "").strip()
            self._stat_translations += 1
            self._text_done_emitted = True
            self.on_text_done(text)

        elif etype == "response.audio.delta":
            if self._should_drop_response_event(etype, event):
                return
            encoded = event.get("delta", "")
            if encoded:
                self._stat_audio_chunks += 1
                self._response_audio_chunks += 1
                first_audio_delta = self._first_audio_delta_at is None
                if first_audio_delta:
                    now = time.monotonic()
                    self._first_audio_delta_at = now
                    metric_bits = []
                    if self._response_started_at is not None:
                        metric_bits.append(
                            f"from_response_created_ms={int((now - self._response_started_at) * 1000)}"
                        )
                    if self._speech_started_at is not None:
                        metric_bits.append(
                            f"from_speech_started_ms={int((now - self._speech_started_at) * 1000)}"
                        )
                    if self._utterance_committed_at is not None:
                        metric_bits.append(
                            f"from_audio_committed_ms={int((now - self._utterance_committed_at) * 1000)}"
                        )
                    self._log("first_audio_delta " + " ".join(metric_bits))
                    self.on_status_change("playing")
                self.on_audio_delta(encoded)

        elif etype == "response.audio.done":
            if self._should_drop_response_event(etype, event):
                return
            self._log(f"response.audio.done chunks={self._response_audio_chunks}")
            self.on_audio_done()

        elif etype == "response.audio_transcript.delta":
            if self._should_drop_response_event(etype, event):
                return
            if not self._current_response_had_text and not self._text_done_emitted:
                delta = event.get("delta", "")
                if delta:
                    self._using_audio_transcript_text = True
                    self._audio_transcript_text_parts.append(delta)
                    if self._first_text_delta_at is None:
                        now = time.monotonic()
                        self._first_text_delta_at = now
                        self._log(
                            "first_text_delta source=audio_transcript "
                            f"from_response_created_ms={self._ms_since(self._response_started_at, now)} "
                            f"from_audio_committed_ms={self._ms_since(self._utterance_committed_at, now)}"
                        )
                    self.on_text_delta(delta)

        elif etype == "response.audio_transcript.done":
            if self._should_drop_response_event(etype, event):
                return
            if not self._current_response_had_text and not self._text_done_emitted:
                text = event.get("transcript", "").strip()
                if not text:
                    text = "".join(self._audio_transcript_text_parts).strip()
                if text:
                    self._using_audio_transcript_text = True
                    self._stat_translations += 1
                    self._text_done_emitted = True
                    self.on_text_done(text)

        elif etype == "response.done":
            dropped_response = self._should_drop_response_event(etype, event)
            response_id = self._event_response_id(event)
            completed_source_id = self._active_response_source_id
            if response_id:
                self._cancelled_response_ids.discard(response_id)
            if dropped_response:
                self._assistant_speaking = False
                self._current_response_id = None
                self._active_response_source_id = None
                self._pending_response_source_id = None
                self.on_response_done(completed_source_id)
                await self._prune_conversation(ws)
                await self._start_next_pending_relay(ws)
                return
            self._assistant_speaking = False
            self._current_response_id = None
            self._active_response_source_id = None
            self._pending_response_source_id = None
            metric_bits = [
                f"translations={self._stat_translations}",
                f"audio_chunks={self._response_audio_chunks}",
                f"send_queue_drops={self._send_queue_drops}",
            ]
            if self._speech_started_at is not None:
                metric_bits.append(
                    f"turn_ms={int((time.monotonic() - self._speech_started_at) * 1000)}"
                )
            audio_stats = self._audio_input_stats()
            if audio_stats:
                metric_bits.append(
                    "audio_input="
                    + ",".join(
                        f"{key}={value}"
                        for key, value in sorted(audio_stats.items())
                    )
            )
            await self._prune_conversation(ws)
            self._log("response.done " + " ".join(metric_bits))
            self.on_response_done(completed_source_id)
            if await self._start_next_pending_relay(ws):
                return
            self.on_status_change("idle")

        elif etype == "error":
            err = event.get("error", {})
            logger.error(f"InterpreterRealtimeClient error: {err}")
            self.on_error(err)

        else:
            # We skip printing unhandled events to avoid polluting logs
            pass

    async def _handle_input_transcript_with_audio(self, ws, transcript: str) -> None:
        original_enable_speaker = self.enable_speaker
        self.enable_speaker = self.request_audio_output
        try:
            await self._handle_input_transcript(ws, transcript)
        finally:
            self.enable_speaker = original_enable_speaker

    async def _handle_input_without_relay(
        self,
        ws,
        *,
        item_id: Optional[str],
        reason: str,
    ) -> None:
        if self._relay_response_busy():
            self._log(
                "input_without_relay_preserved_active_response "
                f"reason={reason} item_id={item_id or 'n/a'} "
                f"active_response_id={self._current_response_id or 'n/a'} "
                f"pending_source_id={self._pending_response_source_id or 'n/a'}"
            )
            return

        self._suppress_response_output = True
        self._pending_response_source_id = None
        self._active_response_source_id = None
        self.on_status_change("idle")
        await self._prune_conversation(ws)

    async def _create_response_from_source_transcript(
        self,
        ws,
        transcript: str,
        *,
        relay_source_id: str,
        relay_style: str = "normal",
    ) -> None:
        source_text = transcript.strip()
        if not source_text:
            return

        request = {
            "relay_source_id": relay_source_id,
            "source_text": source_text,
            "relay_style": relay_style,
            "queued_at": time.monotonic(),
        }
        if self._relay_response_busy() or not self.can_start_relay_response(relay_source_id):
            self._pending_relay_requests.append(request)
            self._log(
                "relay_response_queued "
                f"source_id={relay_source_id} style={relay_style} "
                f"queue_depth={len(self._pending_relay_requests)} "
                f"busy={self._relay_response_busy()}"
            )
            self.on_status_change("queued")
            return

        await self._send_relay_response(ws, request)

    async def _send_relay_response(self, ws, request: Dict[str, Any]) -> None:
        source_text = str(request["source_text"]).strip()
        relay_source_id = str(request["relay_source_id"])
        relay_style = str(request.get("relay_style") or "normal")
        if not source_text:
            return

        self.on_relay_response_starting(relay_source_id)
        self._pending_response_source_id = relay_source_id
        self._active_response_source_id = None
        self._suppress_response_output = False
        modalities = ["text", "audio"] if self.request_audio_output else ["text"]
        if relay_style == "summary":
            instructions = (
                build_interpreter_summary_instructions(
                    self.src_lang,
                    self.tgt_lang,
                    meeting_languages=self.meeting_languages,
                )
                + " Summarize the validated overlap snippets below only. "
                "Do not translate or summarize anything outside these snippets. "
                "Do not add facts, decisions, or context not present in the snippets. "
                "Do not use speaker labels, participant names, or narrator wording. "
                "Stop immediately after the summary."
            )
        else:
            instructions = (
                self._current_instructions()
                + " Relay the following validated source transcript only. "
                "Output only the direct interpreted message — nothing else. "
                "Do not add explanation, qualification, context, or commentary. "
                "Do not reference who said it. "
                "Do not infer meaning beyond what the text says. "
                "Do not use prior audio or conversation context. "
                "Preserve technical terms, code terms, and product names exactly as they appear. "
                "Stop immediately after the relay."
            )
        payload = {
            "type": "response.create",
            "response": {
                "conversation": "none",
                "modalities": modalities,
                "instructions": instructions,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": source_text,
                            }
                        ],
                    }
                ],
                "metadata": {
                    "source": "validated_input_transcript",
                    "relay_source_id": relay_source_id,
                    "source_language": self.src_lang,
                    "target_language": self.tgt_lang,
                    "relay_style": relay_style,
                },
            },
        }
        await ws.send(json.dumps(payload))
        self._log(
            "response.create_from_validated_transcript "
            f"source_id={relay_source_id} chars={len(source_text)} "
            f"modalities={','.join(modalities)} relay_style={relay_style}"
        )

    async def _hold_for_turn_completion(self, *, relay_style: str) -> None:
        if relay_style == "summary" or INTERPRETER_FINAL_TRANSCRIPT_HOLD_MS <= 0:
            return
        stopped_at = self._speech_stopped_at
        if stopped_at is None:
            return
        elapsed_ms = int(max(0.0, time.monotonic() - stopped_at) * 1000)
        remaining_ms = INTERPRETER_FINAL_TRANSCRIPT_HOLD_MS - elapsed_ms
        if remaining_ms <= 0:
            return
        self._log(
            "turn_completion_hold "
            f"remaining_ms={remaining_ms} elapsed_since_speech_stop_ms={elapsed_ms}"
        )
        await asyncio.sleep(remaining_ms / 1000)

    async def _start_next_pending_relay(self, ws) -> bool:
        if self._relay_response_busy():
            return False
        while self._pending_relay_requests:
            request = self._pending_relay_requests[0]
            relay_source_id = str(request.get("relay_source_id") or "")
            if not relay_source_id:
                self._pending_relay_requests.pop(0)
                continue
            if self.should_drop_pending_relay(relay_source_id):
                self._pending_relay_requests.pop(0)
                self._log(
                    "relay_response_pending_dropped "
                    f"source_id={relay_source_id} style={request.get('relay_style')} "
                    f"remaining={len(self._pending_relay_requests)}"
                )
                continue
            if not self.can_start_relay_response(relay_source_id):
                self._log(
                    "relay_response_pending_waiting_for_room_focus "
                    f"source_id={relay_source_id} queue_depth={len(self._pending_relay_requests)}"
                )
                self.on_status_change("queued")
                return False

            self._pending_relay_requests.pop(0)
            queued_ms = int(max(0.0, time.monotonic() - float(request.get("queued_at") or time.monotonic())) * 1000)
            self._log(
                "relay_response_dequeued "
                f"source_id={relay_source_id} style={request.get('relay_style')} "
                f"queued_ms={queued_ms} remaining={len(self._pending_relay_requests)}"
            )
            await self._send_relay_response(ws, request)
            return True
        return False

    async def try_start_pending_relay(self) -> bool:
        ws = self._ws
        if ws is None:
            return False
        return await self._start_next_pending_relay(ws)

    def pending_relay_count(self) -> int:
        return len(self._pending_relay_requests)

    def _relay_response_busy(self) -> bool:
        return bool(
            self._assistant_speaking
            or self._current_response_id is not None
            or self._pending_response_source_id is not None
        )

    def _normalize_relay_approval(self, approval: Any, *, default_source_text: str) -> Dict[str, str]:
        if isinstance(approval, dict):
            relay_source_id = str(approval.get("relay_source_id") or "")
            source_text = str(approval.get("source_text") or default_source_text)
            relay_style = str(approval.get("relay_style") or "normal")
        else:
            relay_source_id = str(approval)
            source_text = default_source_text
            relay_style = "normal"
        return {
            "relay_source_id": relay_source_id,
            "source_text": source_text,
            "relay_style": "summary" if relay_style == "summary" else "normal",
        }

    async def update_routing(self, src_lang: str, tgt_lang: str) -> None:
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._deterministic_routing = self.src_lang != "auto" and self.tgt_lang != "auto"
        self._routing_locked = self._deterministic_routing
        if self._deterministic_routing:
            self._last_detected_src = self.src_lang

        ws = self._ws
        if ws is None:
            return

        if self._assistant_speaking:
            await self._cancel_response(ws)
        elif self._conversation_item_ids:
            await self._prune_conversation(ws)
        await ws.send(json.dumps(self._session_update_payload()))
        self._log(
            "interpreter.routing_updated "
            f"src={self.src_lang} tgt={self.tgt_lang} meeting_languages={self.meeting_languages}"
        )

    def _session_update_payload(self) -> dict[str, Any]:
        instructions = self._current_instructions()
        return build_interpreter_session_update(
            instructions,
            self.request_audio_output,
            input_transcription_model=self.input_transcription_model,
            input_transcription_prompt=self.input_transcription_prompt,
            input_language=self.src_lang,
        )

    async def _cancel_response(self, ws) -> None:
        response_id = self._current_response_id
        if response_id:
            self._cancelled_response_ids.add(response_id)
        pending_count = len(self._pending_relay_requests)
        self._pending_relay_requests.clear()
        self._suppress_response_output = True
        self._pending_response_source_id = None
        self._active_response_source_id = None
        self._log(
            "controlled_response_cancel "
            f"id={response_id} pending_cleared={pending_count}"
        )
        try:
            await ws.send(json.dumps({"type": "response.cancel"}))
        except Exception as exc:
            logger.warning("Could not send interpreter response.cancel: %s", exc)
        self._assistant_speaking = False
        self._current_response_id = None
        await self._prune_conversation(ws)

    def _should_drop_response_event(self, etype: str, event: Dict[str, Any]) -> bool:
        response_id = self._event_response_id(event)
        if response_id and response_id in self._cancelled_response_ids:
            logger.debug("Dropping cancelled BRSE response event type=%s id=%s", etype, response_id)
            return True
        if self._suppress_response_output:
            logger.debug("Suppressing stale BRSE response event type=%s id=%s", etype, response_id)
            return True
        if self._current_response_id is None:
            logger.debug("Dropping response event without active response type=%s id=%s", etype, response_id)
            return True
        if self._active_response_source_id is None:
            logger.debug(
                "Dropping response event without validated source type=%s id=%s",
                etype,
                response_id,
            )
            return True
        if response_id and self._current_response_id and response_id != self._current_response_id:
            logger.debug(
                "Dropping mismatched BRSE response event type=%s event_id=%s current_id=%s",
                etype,
                response_id,
                self._current_response_id,
            )
            return True
        return False

    def _event_response_id(self, event: Dict[str, Any]) -> Optional[str]:
        response_id = event.get("response_id")
        if isinstance(response_id, str) and response_id:
            return response_id
        response = event.get("response")
        if isinstance(response, dict):
            nested_id = response.get("id")
            if isinstance(nested_id, str) and nested_id:
                return nested_id
        return None

    def current_response_source_id(self) -> Optional[str]:
        return self._active_response_source_id

    def _input_item_id_from_event(self, event: Dict[str, Any]) -> Optional[str]:
        item_id = event.get("item_id")
        if isinstance(item_id, str) and item_id:
            return item_id
        item = event.get("item")
        if isinstance(item, dict):
            nested_id = item.get("id")
            if isinstance(nested_id, str) and nested_id:
                return nested_id
        return None

    def _input_transcription_event_is_current(self, event: Dict[str, Any]) -> bool:
        item_id = self._input_item_id_from_event(event)
        active_item_id = self._active_input_item_id
        if item_id is None:
            return self._speech_stopped_at is not None
        return active_item_id == item_id or item_id in self._accepted_input_item_ids

    def _response_source_id_from_event(self, event: Dict[str, Any]) -> Optional[str]:
        response = event.get("response")
        if not isinstance(response, dict):
            return None
        metadata = response.get("metadata")
        if not isinstance(metadata, dict):
            return None
        relay_source_id = metadata.get("relay_source_id")
        if isinstance(relay_source_id, str) and relay_source_id:
            return relay_source_id
        return None

    def _response_source_is_expected(self, response_source_id: Optional[str]) -> bool:
        pending_source_id = self._pending_response_source_id
        if pending_source_id is None:
            return False
        if response_source_id is None:
            return True
        return response_source_id == pending_source_id

    def _ms_since(self, started_at: Optional[float], now: Optional[float] = None) -> str:
        if started_at is None:
            return "n/a"
        if now is None:
            now = time.monotonic()
        return str(int((now - started_at) * 1000))

    def _log_send_queue_drop(self) -> None:
        now = time.monotonic()
        if now - self._send_queue_drop_log_at < 2.0:
            return
        self._send_queue_drop_log_at = now
        self._log(
            "interpreter_send_queue_drop "
            f"total={self._send_queue_drops} maxsize={INTERPRETER_SEND_QUEUE_MAXSIZE}"
        )

    def _remember_conversation_item_from_event(self, event: Dict[str, Any]) -> None:
        item = event.get("item")
        if not isinstance(item, dict):
            item = event.get("output_item")
        if not isinstance(item, dict):
            item_id = event.get("item_id")
            if isinstance(item_id, str) and item_id:
                self._remember_conversation_item(item_id)
            return

        item_id = item.get("id")
        if not item_id or not self._item_is_prunable(item):
            return
        self._remember_conversation_item(item_id)

    def _item_is_prunable(self, item: Dict[str, Any]) -> bool:
        role = item.get("role")
        item_type = item.get("type")
        if role == "system":
            return False
        if item_type is None:
            return True
        return item_type in {"message", "audio", "input_audio", "input_text", "text"}

    def _remember_conversation_item(self, item_id: str) -> None:
        if item_id in self._conversation_item_id_set:
            return
        self._conversation_item_id_set.add(item_id)
        self._conversation_item_ids.append(item_id)

    async def _prune_conversation(self, ws) -> None:
        if not self._conversation_item_ids:
            return

        item_ids = list(self._conversation_item_ids)
        self._conversation_item_ids.clear()
        self._conversation_item_id_set.clear()
        for item_id in item_ids:
            try:
                await ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.delete",
                            "item_id": item_id,
                        }
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Could not prune interpreter conversation item %s: %s",
                    item_id,
                    exc,
                )
                self._remember_conversation_item(item_id)

    def _set_audio_consumer_ready(self, ready: bool) -> None:
        audio_input = self._audio_input
        if audio_input is None:
            return
        setter = getattr(audio_input, "set_streaming_ready", None)
        if callable(setter):
            setter(ready)

    def _stop_audio_input(self, audio_input: AudioInput, *, close_stream: bool) -> None:
        stop = getattr(audio_input, "stop")
        try:
            stop(close_stream=close_stream)
        except TypeError:
            stop()

    def _audio_input_stats(self) -> Dict[str, Any]:
        audio_input = self._audio_input
        if audio_input is None:
            return {}
        getter = getattr(audio_input, "stats_snapshot", None)
        if callable(getter):
            try:
                return dict(getter())
            except Exception:
                logger.exception("Failed to collect audio input stats")
        return {}
