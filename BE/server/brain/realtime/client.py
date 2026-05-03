"""
server/brain/realtime/client.py
OpenAI Realtime API WebSocket client for live voice-to-voice interpretation.

Supports Vietnamese, English, Japanese, Chinese, Korean, French, and Spanish
with configurable src/tgt routing.
- Auto-detection via lightweight heuristic on input transcript (sticky per session).
- Barge-in: new user speech cancels in-progress assistant response immediately.
- Text streams to stdout; audio plays through speaker in real time.
- --debug flag enables verbose event logging.

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

from server.shared.audio import AudioInput, MicInput, SpeakerPlayer
from server.brain.prompts.language import (
    build_instructions,
    detect_lang,
    pair_allowed,
    parse_pairs,
    resolve_tgt,
    DEFAULT_TGT,
    LANG_NAMES,
)
from server.shared.logging_utils import get_logger, print_translation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REALTIME_URL_TEMPLATE = "wss://api.openai.com/v1/realtime?model={model}"
DEFAULT_MODEL = "gpt-realtime-mini"
SAMPLE_RATE = 16000
SPEAKER_SAMPLE_RATE = 24000   # Realtime API outputs PCM16 at 24kHz
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0

logger = get_logger("realtime.client")


# ---------------------------------------------------------------------------
# Session config
# ---------------------------------------------------------------------------

def _build_session_update(instructions: str, enable_audio: bool) -> dict:
    modalities = ["text", "audio"] if enable_audio else ["text"]
    session: dict = {
        "modalities": modalities,
        "instructions": instructions,
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
    Supports vi/en/ja/zh/ko/fr/es with auto-detection and sticky language.
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
        src_lang: str = "auto",
        tgt_lang: str = "auto",
        allowed_pairs: set = None,
        show_input: bool = False,
        meeting_mode: str = "locked",  # "locked" | "auto"
        audio_input: Optional[AudioInput] = None,  # Phase 2: plug in any AudioInput
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.mic_device = mic_device
        self.sample_rate = sample_rate
        self.enable_speaker = enable_speaker
        self.speaker_device = speaker_device
        self.debug = debug
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.allowed_pairs = allowed_pairs if allowed_pairs is not None else set()
        self.show_input = show_input
        self.meeting_mode = meeting_mode  # "locked" | "auto"
        # audio_input overrides mic_device/sample_rate when provided
        self._audio_input: Optional[AudioInput] = audio_input

        self._running = False
        self._ws = None
        self._player: Optional[SpeakerPlayer] = None
        self._assistant_speaking = False
        self._current_response_id: Optional[str] = None
        # Sticky language: last confidently detected source language
        self._last_detected_src: Optional[str] = None
        # True once routing is committed (always True in locked mode after first detection)
        self._routing_locked: bool = (
            self.meeting_mode == "locked"
            and self.src_lang != "auto"
            and self.tgt_lang != "auto"
        )

        # Observability counters (reset per session in _run_session)
        self._stat_transcripts: int = 0       # input transcripts received
        self._stat_translations: int = 0      # response.text.done events
        self._stat_audio_chunks: int = 0      # response.audio.delta chunks dispatched
        self._stat_detect_failed: int = 0     # transcripts where detect_lang returned None

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
        logger.info(msg)

    def _dbg(self, msg: str) -> None:
        if self.debug:
            logger.debug(msg)

    # ------------------------------------------------------------------
    # Instructions for current routing
    # ------------------------------------------------------------------

    def _current_instructions(self) -> str:
        """
        Build instructions using the effective src.
        If src=auto and we have a sticky detected language, use that.
        """
        effective_src = self.src_lang
        if effective_src == "auto" and self._last_detected_src:
            effective_src = self._last_detected_src
        return build_instructions(effective_src, self.tgt_lang)

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

        # Reset per-session observability counters
        self._stat_transcripts = 0
        self._stat_translations = 0
        self._stat_audio_chunks = 0
        self._stat_detect_failed = 0

        if self.enable_speaker:
            self._player = SpeakerPlayer(
                device=self.speaker_device,
                sample_rate=SPEAKER_SAMPLE_RATE,
            )
            self._player.start()
        else:
            # Emit a clear startup notice so operators know audio output is off.
            # Translation text will still appear on stdout; only TTS is disabled.
            print(
                "[RealtimeClient] Audio output: DISABLED (speaker=off). "
                "Translation text will print to stdout only. "
                "Use --speaker / --meet-mic-device to enable TTS output.",
                flush=True,
            )
            logger.info("Audio output disabled — text-only translation mode.")

        try:
            async with websockets.connect(
                url, additional_headers=headers, ping_interval=20
            ) as ws:
                self._ws = ws
                self._log(f"ws_connected model={self.model}")
                instructions = self._current_instructions()
                await ws.send(json.dumps(_build_session_update(instructions, self.enable_speaker)))

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
        loop = asyncio.get_running_loop()

        # Use the injected AudioInput, or fall back to MicInput for the given device
        audio_in: AudioInput = self._audio_input or MicInput(
            device=self.mic_device, sample_rate=self.sample_rate
        )

        audio_q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=300)

        def _capture_thread() -> None:
            audio_in.start()
            try:
                for chunk in audio_in.stream_frames():
                    encoded = base64.b64encode(chunk).decode("utf-8")
                    asyncio.run_coroutine_threadsafe(audio_q.put(encoded), loop)
            finally:
                audio_in.stop()
                asyncio.run_coroutine_threadsafe(audio_q.put(None), loop)

        t = threading.Thread(target=_capture_thread, daemon=True)
        t.start()

        src_label = self.src_lang if self.src_lang != "auto" else "auto-detect"
        tgt_label = self.tgt_lang if self.tgt_lang != "auto" else "auto"
        speaker_label = "speaker ON" if self.enable_speaker else "speaker OFF"

        # Show the input source in the banner
        input_label = type(audio_in).__name__

        if self.meeting_mode == "locked":
            if self._routing_locked:
                mode_line = f"[MeetingMode] locked | src={self.src_lang} tgt={self.tgt_lang}"
            else:
                mode_line = "[MeetingMode] locked | waiting for first confident detection to lock routing"
        else:
            mode_line = "[MeetingMode] auto | src=auto tgt=auto (sticky enabled)"

        print(f"\n{mode_line}", flush=True)
        print(
            f"[Listening... input={input_label} src={src_label} tgt={tgt_label}"
            f" | {speaker_label} | Ctrl+C to quit.]\n",
            flush=True,
        )
        self._log(f"Audio capture started: {input_label}")

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
            audio_in.stop()

    # ------------------------------------------------------------------
    # Event receiver
    # ------------------------------------------------------------------

    async def _receive_events(self, ws) -> None:
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
                self._stat_transcripts += 1
                self._dbg(f"transcript #{self._stat_transcripts}: {transcript!r}")
                await self._handle_input_transcript(ws, transcript)

        # ---- Response lifecycle ----
        elif etype == "response.created":
            self._current_response_id = event.get("response", {}).get("id")
            self._assistant_speaking = True
            self._dbg(f"response.created id={self._current_response_id}")
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
            self._stat_translations += 1
            self._log(f"response.text.done #{self._stat_translations} text={text!r}")
            print_translation("\n", end="")

        # ---- Audio output ----
        elif etype == "response.audio.delta":
            encoded = event.get("delta", "")
            if encoded and self._player:
                self._stat_audio_chunks += 1
                self._player.push(base64.b64decode(encoded))
            elif encoded and not self._player:
                # Audio was produced by the model but there is no output sink.
                # Log once per response (when first chunk arrives for this response).
                if self._stat_audio_chunks == 0:
                    self._dbg(
                        "response.audio.delta received but speaker is disabled "
                        "(enable_speaker=False). Audio is dropped. "
                        "Translation text is still printed to stdout."
                    )

        elif etype == "response.audio.done":
            self._dbg("response.audio.done")
            if self._player:
                self._player.flush()

        elif etype == "response.audio_transcript.delta":
            self._dbg(f"audio_transcript.delta={event.get('delta', '')!r}")

        elif etype == "response.audio_transcript.done":
            self._dbg(f"audio_transcript.done={event.get('transcript', '')!r}")

        # ---- Response done ----
        elif etype == "response.done":
            self._assistant_speaking = False
            self._current_response_id = None
            audio_note = (
                f" | audio_chunks={self._stat_audio_chunks}"
                if self.enable_speaker
                else " | audio=off(text-only)"
            )
            self._log(
                f"response.done | transcripts={self._stat_transcripts}"
                f" translations={self._stat_translations}{audio_note}"
            )

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
    # Input transcript handling + language routing
    # ------------------------------------------------------------------

    async def _handle_input_transcript(self, ws, transcript: str) -> None:
        """
        Called when a complete input transcript arrives.
        Detects language (heuristic), updates sticky src, reprints [You] label,
        and re-sends session.update if routing changed.
        """
        # Print [You] line
        if self.show_input or self.debug:
            if self.debug:
                print(f"\r[You] {transcript}\n", flush=True)
            else:
                print(f"[You] {transcript}", flush=True)
        else:
            # Always show [You] line (matches spec default behavior)
            print(f"[You] {transcript}", flush=True)

        # If routing is already locked, skip detection entirely (just log in debug)
        if self._routing_locked:
            self._dbg(f"lang_detect: routing locked, skipping detection for {transcript!r}")
            return

        # Skip language detection if src is explicitly set (not auto)
        if self.src_lang != "auto":
            return

        detected = detect_lang(transcript)
        if detected is None:
            self._stat_detect_failed += 1
            self._dbg(f"lang_detect: uncertain for {transcript!r}, keeping sticky={self._last_detected_src}")
            # After a few failed detections, remind the operator that translation
            # is still happening via the auto/auto instruction (model self-detects).
            if self._stat_detect_failed == 3:
                print(
                    "[MeetingMode] Language detection uncertain for recent transcripts. "
                    "The model is translating using auto-detect instructions. "
                    "Use --src/--tgt to fix the language pair explicitly.",
                    flush=True,
                )
            return  # keep previous sticky to avoid flip-flopping

        if detected == self._last_detected_src:
            # In locked mode, first detection sets the lock even if it's the same as sticky
            if self.meeting_mode == "locked":
                self._routing_locked = True
                effective_tgt = resolve_tgt(detected, self.tgt_lang)
                print(f"[MeetingMode] locked | src={detected} tgt={effective_tgt}", flush=True)
            return  # no routing change needed

        self._log(f"lang_detect: {self._last_detected_src!r} -> {detected!r}")
        self._last_detected_src = detected

        # Check pair is allowed
        effective_tgt = resolve_tgt(detected, self.tgt_lang)
        if not pair_allowed(detected, effective_tgt, self.allowed_pairs):
            self._log(f"pair {detected}<->{effective_tgt} not in --pairs, skipping session update")
            return

        # In locked mode: commit routing now and never change again
        if self.meeting_mode == "locked":
            self._routing_locked = True
            print(f"[MeetingMode] locked | src={detected} tgt={effective_tgt}", flush=True)

        # Re-send session.update with updated instructions
        new_instructions = build_instructions(detected, self.tgt_lang)
        self._log(f"routing: {LANG_NAMES[detected]} -> {LANG_NAMES[effective_tgt]}")
        try:
            await ws.send(json.dumps(
                _build_session_update(new_instructions, self.enable_speaker)
            ))
        except Exception as exc:
            logger.warning(f"Could not re-send session.update: {exc}")

    # ------------------------------------------------------------------
    # Barge-in
    # ------------------------------------------------------------------

    async def _cancel_response(self, ws) -> None:
        self._log("barge_in — cancelling assistant response")
        if self._player:
            self._player.restart()
        try:
            await ws.send(json.dumps({"type": "response.cancel"}))
        except Exception as exc:
            logger.warning(f"Could not send response.cancel: {exc}")
        self._assistant_speaking = False
        self._current_response_id = None
        print_translation("\n", end="")
