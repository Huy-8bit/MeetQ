from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict

import websockets

from src.realtime.client import REALTIME_URL_TEMPLATE, RealtimeClient, _build_session_update

logger = logging.getLogger(__name__)


class InterpreterRealtimeClient(RealtimeClient):
    """
    Interpreter-specific wrapper that keeps audio output enabled in the OpenAI
    session while preventing any local SpeakerPlayer playback on the server.
    """

    def __init__(self, *args, **kwargs):
        self.request_audio_output = kwargs.pop("request_audio_output", True)
        kwargs["enable_speaker"] = False
        super().__init__(*args, **kwargs)
        self.on_transcript_complete: Callable[[str], None] = lambda t: None
        self.on_text_delta: Callable[[str], None] = lambda t: None
        self.on_text_done: Callable[[str], None] = lambda t: None
        self.on_audio_delta: Callable[[str], None] = lambda enc: None
        self.on_audio_done: Callable[[], None] = lambda: None
        self.on_status_change: Callable[[str], None] = lambda s: None
        self.on_error: Callable[[Dict[str, Any]], None] = lambda err: None

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

        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
            ) as ws:
                self._ws = ws
                self._log(f"ws_connected model={self.model}")
                instructions = self._current_instructions()
                await ws.send(
                    json.dumps(
                        _build_session_update(
                            instructions,
                            self.request_audio_output,
                        )
                    )
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
            self._player = None

    async def _handle_event(self, ws, etype: str, event: dict) -> None:
        if etype == "input_audio_buffer.speech_started":
            self.on_status_change("capturing")
            if self._assistant_speaking:
                await self._cancel_response(ws)

        elif etype == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "").strip()
            if transcript:
                await self._handle_input_transcript_with_audio(ws, transcript)
                self.on_transcript_complete(transcript)

        elif etype == "response.created":
            self.on_status_change("translating")
            self._current_response_id = event.get("response", {}).get("id")
            self._assistant_speaking = True

        elif etype == "response.text.delta":
            delta = event.get("delta", "")
            self.on_text_delta(delta)

        elif etype == "response.text.done":
            text = event.get("text", "").strip()
            self.on_text_done(text)

        elif etype == "response.audio.delta":
            encoded = event.get("delta", "")
            if encoded:
                self.on_status_change("playing")
                self.on_audio_delta(encoded)

        elif etype == "response.audio.done":
            self.on_audio_done()

        elif etype == "response.done":
            self._assistant_speaking = False
            self._current_response_id = None
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
