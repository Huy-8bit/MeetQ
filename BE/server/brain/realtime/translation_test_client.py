"""
TranslationTestClient — lightweight wrapper around InterpreterRealtimeClient
configured for single-user translation-test mode.

Differences from full meeting interpreter:
  - text-only output (no audio track publishing to LiveKit)
  - short VAD silence window (400 ms) to feel responsive on single utterances
  - strict translation-only instruction (same policy as meeting interpreter)
  - no LiveKit room join required — audio is fed directly via a queue-backed AudioInput shim

This runs entirely within the Gateway process for the duration of the test session.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import queue
import struct
from datetime import datetime, timezone
from typing import Callable, Optional

from server.shared.audio import AudioInput, AudioMetadata
from server.brain.realtime.interpreter_client import InterpreterRealtimeClient
from server.brain.realtime.session_config import (
    build_interpreter_instructions,
    INTERPRETER_TEMPERATURE,
    INTERPRETER_VAD_CONFIG,
)

logger = logging.getLogger(__name__)

# Tighter VAD for short test utterances (user speaks once, stops quickly)
_TEST_VAD_CONFIG = {
    **INTERPRETER_VAD_CONFIG,
    "silence_duration_ms": 400,  # faster commit for test utterances
}

_SAMPLE_RATE = 16000
_CHANNELS = 1
_BYTES_PER_SAMPLE = 2


class _QueueAudioInput(AudioInput):
    """
    Thread-safe AudioInput that consumes from an asyncio.Queue populated
    by the WebSocket receive loop running on the event loop.
    """

    def __init__(self, sample_rate: int = _SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=400)
        self._running = False

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(
            sample_rate=self._sample_rate,
            channels=_CHANNELS,
        )

    def start(self) -> None:
        self._running = True

    def stop(self, *, close_stream: bool = True) -> None:
        self._running = False
        # unblock stream_frames
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def push_pcm(self, pcm_bytes: bytes) -> None:
        """Called from the event-loop WS receive; may drop if full."""
        if not self._running:
            return
        if self._q.full():
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
        try:
            self._q.put_nowait(pcm_bytes)
        except queue.Full:
            pass

    def stream_frames(self):
        while self._running:
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            yield chunk


def _build_test_session_update(src_lang: str, tgt_lang: str) -> dict:
    """Build OpenAI session.update for text-only translation test mode."""
    from server.brain.realtime.session_config import (
        INTERPRETER_MAX_RESPONSE_OUTPUT_TOKENS,
    )

    instructions = build_interpreter_instructions(src_lang, tgt_lang)
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text"],  # text-only; no audio output for test mode
            "instructions": instructions,
            "input_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": dict(_TEST_VAD_CONFIG),
            "temperature": INTERPRETER_TEMPERATURE,
            "max_response_output_tokens": INTERPRETER_MAX_RESPONSE_OUTPUT_TOKENS,
        },
    }


class TranslationTestClient:
    """
    Manages one OpenAI Realtime session for translation test.

    Callbacks (set before calling start()):
      on_source_partial(text)   — incremental source transcript delta
      on_source_final(text)     — complete source transcript
      on_translated_partial(text) — incremental translated text delta
      on_translated_final(text) — final translated text
      on_error(code, message)   — error from pipeline
    """

    def __init__(
        self,
        api_key: str,
        src_lang: str,
        tgt_lang: str,
        model: str = "gpt-realtime-mini",
    ) -> None:
        self._api_key = api_key
        self._src_lang = src_lang
        self._tgt_lang = tgt_lang
        self._model = model
        self._audio_input = _QueueAudioInput(sample_rate=_SAMPLE_RATE)
        self._client: Optional[InterpreterRealtimeClient] = None
        self._task: Optional[asyncio.Task] = None

        # Callbacks
        self.on_source_partial: Callable[[str], None] = lambda t: None
        self.on_source_final: Callable[[str], None] = lambda t: None
        self.on_translated_partial: Callable[[str], None] = lambda t: None
        self.on_translated_final: Callable[[str], None] = lambda t: None
        self.on_error: Callable[[str, str], None] = lambda code, msg: None

    def push_audio(self, pcm_bytes: bytes) -> None:
        """Feed raw PCM16 bytes from the WebSocket receive loop."""
        self._audio_input.push_pcm(pcm_bytes)

    async def start(self) -> None:
        client = InterpreterRealtimeClient(
            api_key=self._api_key,
            model=self._model,
            src_lang=self._src_lang,
            tgt_lang=self._tgt_lang,
            audio_input=self._audio_input,
            request_audio_output=False,
        )

        # Override session_update_payload to use test-specific config
        def _session_update_payload() -> dict:
            return _build_test_session_update(self._src_lang, self._tgt_lang)

        client._session_update_payload = _session_update_payload  # type: ignore[method-assign]

        # Bind callbacks
        _source_buf: list[str] = []

        def on_input_transcript_delta(delta: str) -> None:
            if delta:
                _source_buf.append(delta)
                self.on_source_partial("".join(_source_buf))

        def on_transcript_complete(text: str) -> None:
            _source_buf.clear()
            if text:
                self.on_source_final(text)

        _trans_buf: list[str] = []

        def on_text_delta(delta: str) -> None:
            if delta:
                _trans_buf.append(delta)
                self.on_translated_partial("".join(_trans_buf))

        def on_text_done(text: str) -> None:
            _trans_buf.clear()
            if text:
                self.on_translated_final(text)

        def on_audio_delta(encoded: str) -> None:
            pass  # audio output disabled for test mode

        def on_audio_done() -> None:
            pass

        def on_status_change(status: str) -> None:
            if status == "capturing":
                _source_buf.clear()
                _trans_buf.clear()

        def on_error(err: dict) -> None:
            msg = err.get("message") or err.get("type") or "Translation test pipeline error"
            self.on_error("interpreter_unavailable", msg)

        client.on_input_transcript_delta = on_input_transcript_delta
        client.on_transcript_complete = on_transcript_complete
        client.on_text_delta = on_text_delta
        client.on_text_done = on_text_done
        client.on_audio_delta = on_audio_delta
        client.on_audio_done = on_audio_done
        client.on_status_change = on_status_change
        client.on_error = on_error

        self._client = client
        client._running = True
        self._task = asyncio.create_task(client._run_with_retry())
        logger.info(
            "TranslationTestClient started src=%s tgt=%s",
            self._src_lang,
            self._tgt_lang,
        )

    async def stop(self) -> None:
        client = self._client
        if client is not None:
            client._running = False
        self._audio_input.stop()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info(
            "TranslationTestClient stopped src=%s tgt=%s",
            self._src_lang,
            self._tgt_lang,
        )

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
