"""
src/realtime/client.py
OpenAI Realtime API WebSocket client for live voice-to-voice interpretation.

Behavior:
  - User speaks Vietnamese → assistant responds in English (text + audio)
  - User speaks English   → assistant responds in Vietnamese (text + audio)
  - Barge-in: new user speech cancels in-progress assistant response immediately
  - Text translation streams to stdout; audio plays through speaker in real time
  - --debug flag enables verbose event logging

Protocol reference: docs/realtime_protocol.md
"""
from __future__ import annotations

import asyncio
import base64
import json
import threading
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from src.common.audio import MicCapture, SpeakerPlayer
from src.common.logging_utils import get_logger, print_translation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REALTIME_URL_TEMPLATE = "wss://api.openai.com/v1/realtime?model={model}"
DEFAULT_MODEL = "gpt-4o-realtime-preview-2024-12-17"
SAMPLE_RATE = 16000
SPEAKER_SAMPLE_RATE = 24000   # Realtime API outputs PCM16 at 24kHz
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0

TRANSLATION_INSTRUCTIONS = (
    "You are a live bilingual interpreter between Vietnamese and English. "
    "Detect whether the user spoke Vietnamese or English. "
    "If Vietnamese, output ONLY the English translation. "
    "If English, output ONLY the Vietnamese translation. "
    "Output the translation text only. No explanations, no labels, no commentary."
)

logger = get_logger("realtime.client")


# ---------------------------------------------------------------------------
# Session config
# ---------------------------------------------------------------------------

def _build_session_update(enable_audio: bool) -> dict:
    modalities = ["text", "audio"] if enable_audio else ["text"]
    session: dict = {
        "modalities": modalities,
        "instructions": TRANSLATION_INSTRUCTIONS,
        "input_audio_format": "pcm16",
        "input_audio_transcription": {"model": "whisper-1"},
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 700,
        },
        "temperature": 0.8,  # Realtime API minimum is 0.6
    }
    if enable_audio:
        session["output_audio_format"] = "pcm16"
        session["voice"] = "alloy"
    return {"type": "session.update", "session": session}


# ---------------------------------------------------------------------------
# Main client class
# ---------------------------------------------------------------------------

class RealtimeClient:
    """
    Manages the WebSocket session to OpenAI Realtime API.
    Streams mic audio in, receives translated text + audio out.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        mic_device: Optional[int] = None,
        sample_rate: int = SAMPLE_RATE,
        enable_speaker: bool = True,
        speaker_device: Optional[int] = None,
        debug: bool = False,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.mic_device = mic_device
        self.sample_rate = sample_rate
        self.enable_speaker = enable_speaker
        self.speaker_device = speaker_device
        self.debug = debug
        self._running = False
        self._ws = None
        # Speaker player — created per session
        self._player: Optional[SpeakerPlayer] = None
        # Tracks whether assistant is currently speaking (for barge-in)
        self._assistant_speaking = False
        # Current response_id for cancel events
        self._current_response_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until Ctrl+C or unrecoverable error."""
        self._running = True
        try:
            asyncio.run(self._run_with_retry())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — shutting down.")
        finally:
            self._running = False
            if self._player:
                self._player.stop()

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        """Info-level log — always shown."""
        logger.info(msg)

    def _dbg(self, msg: str) -> None:
        """Debug-level log — only shown with --debug."""
        if self.debug:
            logger.debug(msg)

    # ------------------------------------------------------------------
    # Retry loop
    # ------------------------------------------------------------------

    async def _run_with_retry(self) -> None:
        attempt = 0
        while self._running:
            attempt += 1
            try:
                self._log(f"Connecting (attempt {attempt})...")
                await self._run_session()
            except KeyboardInterrupt:
                raise
            except (ConnectionClosedError, ConnectionClosedOK) as exc:
                logger.warning(f"WebSocket closed: {exc}")
            except websockets.exceptions.WebSocketException as exc:
                logger.error(f"WebSocket error: {exc}")
            except Exception as exc:
                logger.error(f"Unexpected error: {exc}", exc_info=True)

            if not self._running:
                break
            if attempt >= MAX_RECONNECT_ATTEMPTS:
                logger.error(f"Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached.")
                break

            delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
            self._log(f"Reconnecting in {delay:.1f}s...")
            await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _run_session(self) -> None:
        url = REALTIME_URL_TEMPLATE.format(model=self.model)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        # Create a fresh player for this session
        if self.enable_speaker:
            self._player = SpeakerPlayer(
                device=self.speaker_device,
                sample_rate=SPEAKER_SAMPLE_RATE,
            )
            self._player.start()

        try:
            async with websockets.connect(
                url, additional_headers=headers, ping_interval=20
            ) as ws:
                self._ws = ws
                self._log(f"ws_connected model={self.model}")
                await ws.send(json.dumps(_build_session_update(self.enable_speaker)))

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
            if self._player:
                self._player.stop()
                self._player = None

    # ------------------------------------------------------------------
    # Audio sender (mic -> websocket)
    # ------------------------------------------------------------------

    async def _send_audio(self, ws) -> None:
        """Read from mic and stream PCM16 chunks to the WebSocket."""
        loop = asyncio.get_running_loop()
        cap = MicCapture(device=self.mic_device, sample_rate=self.sample_rate)
        audio_q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=300)

        def _capture_thread() -> None:
            cap.start()
            try:
                for chunk in cap.iter_chunks():
                    encoded = base64.b64encode(chunk).decode("utf-8")
                    asyncio.run_coroutine_threadsafe(audio_q.put(encoded), loop)
            finally:
                cap.stop()
                asyncio.run_coroutine_threadsafe(audio_q.put(None), loop)

        t = threading.Thread(target=_capture_thread, daemon=True)
        t.start()

        speaker_label = " | speaker ON" if self.enable_speaker else " | speaker OFF"
        print(
            f"\n[Listening... speak Vietnamese or English.{speaker_label} Ctrl+C to quit.]\n",
            flush=True,
        )
        self._log("Mic capture started.")

        try:
            while self._running:
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
            cap.stop()

    # ------------------------------------------------------------------
    # Event receiver (websocket -> terminal + speaker)
    # ------------------------------------------------------------------

    async def _receive_events(self, ws) -> None:
        """Dispatch server events to the appropriate handler."""
        async for raw in ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Non-JSON message from server — ignoring.")
                continue

            etype = event.get("type", "")
            await self._handle_event(ws, etype, event)

    async def _handle_event(self, ws, etype: str, event: dict) -> None:
        # ---- Session lifecycle ----
        if etype == "session.created":
            sid = event.get("session", {}).get("id", "?")
            self._log(f"session.created id={sid}")

        elif etype == "session.updated":
            self._log("session.updated — config applied")

        # ---- VAD / input buffer ----
        elif etype == "input_audio_buffer.speech_started":
            self._log("vad_speech_started")
            # Barge-in: cancel any in-progress response and stop speaker
            if self._assistant_speaking:
                await self._cancel_response(ws)

        elif etype == "input_audio_buffer.speech_stopped":
            self._log("vad_speech_stopped")

        elif etype == "input_audio_buffer.committed":
            self._dbg("input_audio_buffer.committed")

        # ---- Input transcript (what user said) ----
        elif etype == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if self.debug:
                print(f"[You] {delta}", end="", flush=True)

        elif etype == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "").strip()
            if transcript:
                if self.debug:
                    print(f"\r[You] {transcript}\n", flush=True)
                else:
                    print(f"[You] {transcript}", flush=True)

        # ---- Response lifecycle ----
        elif etype == "response.created":
            self._current_response_id = event.get("response", {}).get("id")
            self._assistant_speaking = True
            self._dbg(f"response.created id={self._current_response_id}")
            # Blank line before each new translation block
            print_translation("\n[Interp] ", end="")

        elif etype in (
            "response.output_item.added",
            "response.content_part.added",
            "conversation.item.created",
            "rate_limits.updated",
            "response.output_item.done",
            "response.content_part.done",
        ):
            self._dbg(f"lifecycle: {etype}")

        # ---- Text output (translation) ----
        elif etype == "response.text.delta":
            delta = event.get("delta", "")
            self._dbg(f"text_delta={delta!r}")
            print_translation(delta, end="")

        elif etype == "response.text.done":
            text = event.get("text", "").strip()
            self._log(f"response.text.done text={text!r}")
            print_translation("\n", end="")

        # ---- Audio output (speaker) ----
        elif etype == "response.audio.delta":
            encoded = event.get("delta", "")
            if encoded and self._player:
                pcm = base64.b64decode(encoded)
                self._player.push(pcm)

        elif etype == "response.audio.done":
            self._dbg("response.audio.done")
            if self._player:
                self._player.flush()

        # ---- Output audio transcript (model's spoken text, for debug) ----
        elif etype == "response.audio_transcript.delta":
            self._dbg(f"audio_transcript.delta={event.get('delta', '')!r}")

        elif etype == "response.audio_transcript.done":
            self._dbg(f"audio_transcript.done={event.get('transcript', '')!r}")

        # ---- Response done ----
        elif etype == "response.done":
            self._assistant_speaking = False
            self._current_response_id = None
            self._log("response.done")

        # ---- Errors ----
        elif etype == "error":
            err = event.get("error", {})
            code = err.get("code", "?")
            msg = err.get("message", "?")
            logger.error(f"server_error code={code} message={msg}")
            if code in ("authentication_error", "invalid_api_key"):
                logger.error("Auth error — check OPENAI_API_KEY. Aborting.")
                self._running = False
                raise RuntimeError(f"Auth error: {msg}")

        else:
            self._dbg(f"unhandled_event type={etype}")

    # ------------------------------------------------------------------
    # Barge-in helper
    # ------------------------------------------------------------------

    async def _cancel_response(self, ws) -> None:
        """Cancel in-progress response and clear speaker buffer."""
        self._log("barge_in — cancelling assistant response")

        # Stop speaker immediately
        if self._player:
            self._player.restart()

        # Tell the API to cancel
        cancel_msg: dict = {"type": "response.cancel"}
        try:
            await ws.send(json.dumps(cancel_msg))
        except Exception as exc:
            logger.warning(f"Could not send response.cancel: {exc}")

        self._assistant_speaking = False
        self._current_response_id = None
        # Reprint the [Interp] prefix on a new line so barge-in is visually clean
        print_translation("\n", end="")
