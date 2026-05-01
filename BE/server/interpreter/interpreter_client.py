from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

import websockets

from src.common.audio import AudioInput, MicInput
from src.realtime.client import REALTIME_URL_TEMPLATE, RealtimeClient
from server.interpreter.meeting_config import (
    INTERPRETER_TEMPERATURE,
    INTERPRETER_VAD_CONFIG,
    INTERPRETER_SEND_QUEUE_MAXSIZE,
    build_interpreter_instructions,
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
        self.meeting_languages = kwargs.pop("meeting_languages", None)
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
        self._cancelled_response_ids: set[str] = set()
        self._suppress_response_output = False
        self._current_response_had_text = False
        self._using_audio_transcript_text = False
        self._text_done_emitted = False
        self._audio_transcript_text_parts: list[str] = []
        self.on_input_transcript_delta: Callable[[str], None] = lambda t: None
        self.on_transcript_complete: Callable[[str], None] = lambda t: None
        self.on_text_delta: Callable[[str], None] = lambda t: None
        self.on_text_done: Callable[[str], None] = lambda t: None
        self.on_audio_delta: Callable[[str], None] = lambda enc: None
        self.on_audio_done: Callable[[], None] = lambda: None
        self.on_status_change: Callable[[str], None] = lambda s: None
        self.on_error: Callable[[Dict[str, Any]], None] = lambda err: None

    def _current_instructions(self) -> str:
        effective_src = self.src_lang
        if effective_src == "auto" and self._last_detected_src:
            effective_src = self._last_detected_src
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
        self._cancelled_response_ids.clear()
        self._suppress_response_output = False
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
                    f"vad={INTERPRETER_VAD_CONFIG} temp={INTERPRETER_TEMPERATURE}"
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
            self._speech_started_at = now
            self._speech_stopped_at = None
            self._utterance_committed_at = None
            self._response_started_at = None
            self._first_text_delta_at = None
            self._first_audio_delta_at = None
            self._response_audio_chunks = 0
            self._log(f"speech_started src={self.src_lang} tgt={self.tgt_lang}")
            self.on_status_change("capturing")
            if self._assistant_speaking:
                await self._cancel_response(ws)

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

        elif etype == "input_audio_buffer.committed":
            self._remember_conversation_item_from_event(event)
            now = time.monotonic()
            self._utterance_committed_at = now
            metric_bits = []
            if self._speech_started_at is not None:
                metric_bits.append(
                    f"from_speech_started_ms={int((now - self._speech_started_at) * 1000)}"
                )
            if self._speech_stopped_at is not None:
                metric_bits.append(
                    f"from_speech_stopped_ms={int((now - self._speech_stopped_at) * 1000)}"
                )
            self._log("input_audio_buffer.committed " + " ".join(metric_bits))

        elif etype == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if delta:
                self.on_input_transcript_delta(delta)

        elif etype == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "").strip()
            if transcript:
                self._stat_transcripts += 1
                latency_bits = [f"chars={len(transcript)}"]
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

        elif etype == "response.created":
            self._current_response_id = event.get("response", {}).get("id")
            if self._current_response_id in self._cancelled_response_ids:
                self._suppress_response_output = True
                logger.debug(
                    "Dropping created event for cancelled BRSE response id=%s",
                    self._current_response_id,
                )
                return
            else:
                self._suppress_response_output = False
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
            if response_id:
                self._cancelled_response_ids.discard(response_id)
            if dropped_response:
                await self._prune_conversation(ws)
                return
            self._assistant_speaking = False
            self._current_response_id = None
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
            self._log("response.done " + " ".join(metric_bits))
            self.on_status_change("idle")
            await self._prune_conversation(ws)

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
        )

    async def _cancel_response(self, ws) -> None:
        response_id = self._current_response_id
        if response_id:
            self._cancelled_response_ids.add(response_id)
        self._suppress_response_output = True
        self._log(f"barge_in_or_route_change cancelling response id={response_id}")
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
