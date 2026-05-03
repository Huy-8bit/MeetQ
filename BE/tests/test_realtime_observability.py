"""
tests/test_realtime_observability.py

Tests for RealtimeClient observability counters, startup warnings for disabled
audio output, and the locked-mode stall detection hint.

These tests do NOT open real WebSocket connections.  They exercise
_handle_event, _handle_input_transcript, and _run_session startup logic
directly via AsyncMock / patch.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.brain.realtime.client import RealtimeClient, SPEAKER_SAMPLE_RATE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> RealtimeClient:
    """Return a RealtimeClient with minimal config, not connected."""
    defaults = dict(
        api_key="sk-test",
        enable_speaker=True,
        src_lang="auto",
        tgt_lang="auto",
        meeting_mode="locked",
        debug=False,
    )
    defaults.update(kwargs)
    return RealtimeClient(**defaults)


def _fake_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Counter initialisation
# ---------------------------------------------------------------------------

class TestCounterInit:
    def test_counters_zero_at_construction(self):
        c = _make_client()
        assert c._stat_transcripts == 0
        assert c._stat_translations == 0
        assert c._stat_audio_chunks == 0
        assert c._stat_detect_failed == 0


# ---------------------------------------------------------------------------
# Startup warning when speaker is disabled
# ---------------------------------------------------------------------------

class TestSpeakerDisabledWarning:
    @pytest.mark.asyncio
    async def test_warning_printed_when_speaker_off(self, capsys):
        """_run_session prints a clear notice when enable_speaker=False."""
        c = _make_client(enable_speaker=False)

        # Patch websockets.connect so the session aborts immediately
        async def _fake_connect(*a, **kw):
            raise ConnectionError("abort for test")

        with patch("websockets.connect", side_effect=_fake_connect):
            try:
                await c._run_session()
            except Exception:
                pass

        out = capsys.readouterr().out
        assert "Audio output: DISABLED" in out
        assert "speaker=off" in out
        assert "--speaker" in out or "--meet-mic-device" in out

    @pytest.mark.asyncio
    async def test_no_warning_when_speaker_on(self, capsys):
        """No DISABLED warning when enable_speaker=True."""
        c = _make_client(enable_speaker=True)

        with patch("server.brain.realtime.client.SpeakerPlayer") as MockPlayer:
            MockPlayer.return_value.start = MagicMock()
            MockPlayer.return_value.stop = MagicMock()

            async def _fake_connect(*a, **kw):
                raise ConnectionError("abort for test")

            with patch("websockets.connect", side_effect=_fake_connect):
                try:
                    await c._run_session()
                except Exception:
                    pass

        out = capsys.readouterr().out
        assert "Audio output: DISABLED" not in out

    @pytest.mark.asyncio
    async def test_counters_reset_on_session_start(self):
        """Counters from a prior session are reset at the start of each new session."""
        c = _make_client(enable_speaker=False)
        # Simulate leftover counts from a previous session
        c._stat_transcripts = 5
        c._stat_translations = 3
        c._stat_audio_chunks = 99
        c._stat_detect_failed = 7

        async def _fake_connect(*a, **kw):
            raise ConnectionError("abort for test")

        with patch("websockets.connect", side_effect=_fake_connect):
            try:
                await c._run_session()
            except Exception:
                pass

        assert c._stat_transcripts == 0
        assert c._stat_translations == 0
        assert c._stat_audio_chunks == 0
        assert c._stat_detect_failed == 0


# ---------------------------------------------------------------------------
# response.text.done increments _stat_translations
# ---------------------------------------------------------------------------

class TestTranslationCounter:
    @pytest.mark.asyncio
    async def test_translation_counter_increments(self):
        c = _make_client()
        ws = _fake_ws()

        await c._handle_event(ws, "response.text.done", {"type": "response.text.done", "text": "Hello"})
        assert c._stat_translations == 1

        await c._handle_event(ws, "response.text.done", {"type": "response.text.done", "text": "World"})
        assert c._stat_translations == 2

    @pytest.mark.asyncio
    async def test_translation_counter_independent_of_audio(self):
        """Translations are counted regardless of enable_speaker."""
        c = _make_client(enable_speaker=False)
        ws = _fake_ws()

        await c._handle_event(ws, "response.text.done", {"type": "response.text.done", "text": "Xin chào"})
        assert c._stat_translations == 1


# ---------------------------------------------------------------------------
# conversation.item.input_audio_transcription.completed increments _stat_transcripts
# ---------------------------------------------------------------------------

class TestTranscriptCounter:
    @pytest.mark.asyncio
    async def test_transcript_counter_increments_on_nonempty(self):
        c = _make_client(src_lang="en", tgt_lang="vi", meeting_mode="locked")
        # Lock routing so _handle_input_transcript returns early (no session.update needed)
        c._routing_locked = True
        ws = _fake_ws()

        event = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Hello",
        }
        await c._handle_event(ws, event["type"], event)
        assert c._stat_transcripts == 1

    @pytest.mark.asyncio
    async def test_transcript_counter_skips_empty(self):
        c = _make_client()
        c._routing_locked = True
        ws = _fake_ws()

        event = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "   ",
        }
        await c._handle_event(ws, event["type"], event)
        assert c._stat_transcripts == 0


# ---------------------------------------------------------------------------
# response.audio.delta increments _stat_audio_chunks only when player exists
# ---------------------------------------------------------------------------

class TestAudioChunkCounter:
    @pytest.mark.asyncio
    async def test_audio_chunk_incremented_with_player(self):
        c = _make_client(enable_speaker=True)
        mock_player = MagicMock()
        mock_player.push = MagicMock()
        c._player = mock_player
        ws = _fake_ws()

        import base64
        audio_b64 = base64.b64encode(b"\x00" * 32).decode()
        event = {"type": "response.audio.delta", "delta": audio_b64}
        await c._handle_event(ws, "response.audio.delta", event)

        assert c._stat_audio_chunks == 1
        mock_player.push.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_chunk_not_incremented_without_player(self):
        """Audio dropped when no player — counter stays 0, no crash."""
        c = _make_client(enable_speaker=False)
        assert c._player is None
        ws = _fake_ws()

        import base64
        audio_b64 = base64.b64encode(b"\x00" * 32).decode()
        event = {"type": "response.audio.delta", "delta": audio_b64}
        await c._handle_event(ws, "response.audio.delta", event)

        assert c._stat_audio_chunks == 0

    @pytest.mark.asyncio
    async def test_empty_delta_skipped(self):
        c = _make_client(enable_speaker=True)
        c._player = MagicMock()
        ws = _fake_ws()

        event = {"type": "response.audio.delta", "delta": ""}
        await c._handle_event(ws, "response.audio.delta", event)

        assert c._stat_audio_chunks == 0
        c._player.push.assert_not_called()


# ---------------------------------------------------------------------------
# response.done log includes audio note
# The custom logger uses a StreamHandler bound to the real stderr at import
# time (propagate=False), so neither caplog nor capsys can intercept it.
# Instead we patch _log() directly to capture the message string.
# ---------------------------------------------------------------------------

class TestResponseDoneLog:
    @pytest.mark.asyncio
    async def test_response_done_includes_audio_off_note_when_speaker_disabled(self):
        c = _make_client(enable_speaker=False)
        ws = _fake_ws()
        logged = []
        c._log = lambda msg: logged.append(msg)

        await c._handle_event(ws, "response.done", {"type": "response.done"})

        combined = " ".join(logged)
        assert "audio=off(text-only)" in combined

    @pytest.mark.asyncio
    async def test_response_done_includes_audio_chunks_when_speaker_enabled(self):
        c = _make_client(enable_speaker=True)
        c._stat_audio_chunks = 42
        ws = _fake_ws()
        logged = []
        c._log = lambda msg: logged.append(msg)

        await c._handle_event(ws, "response.done", {"type": "response.done"})

        combined = " ".join(logged)
        assert "audio_chunks=42" in combined


# ---------------------------------------------------------------------------
# Locked-mode stall hint after 3 failed detections
# ---------------------------------------------------------------------------

class TestLockedModeStallHint:
    @pytest.mark.asyncio
    async def test_hint_printed_after_3_failed_detections(self, capsys):
        """After 3 consecutive uncertain detect_lang results, print a routing hint."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        ws = _fake_ws()

        # Short text that will return None from detect_lang (< 5 ASCII words, no ja/vi markers)
        short_text = "hi"  # 2 chars, detect_lang returns None

        with patch("server.brain.realtime.client.detect_lang", return_value=None):
            for _ in range(3):
                await c._handle_input_transcript(ws, short_text)

        out = capsys.readouterr().out
        assert "Language detection uncertain" in out
        assert "--src" in out

    @pytest.mark.asyncio
    async def test_hint_printed_only_once(self, capsys):
        """The hint fires exactly at count == 3 and not again."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value=None):
            for _ in range(6):
                await c._handle_input_transcript(ws, "hi")

        out = capsys.readouterr().out
        # Count occurrences — should appear exactly once
        assert out.count("Language detection uncertain") == 1

    @pytest.mark.asyncio
    async def test_detect_failed_counter_increments_on_none(self):
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value=None):
            await c._handle_input_transcript(ws, "hi")
            await c._handle_input_transcript(ws, "hi")

        assert c._stat_detect_failed == 2

    @pytest.mark.asyncio
    async def test_detect_failed_counter_not_incremented_on_success(self):
        """Successful detection does not increment _stat_detect_failed."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value="en"):
            await c._handle_input_transcript(ws, "Hello world this is a test")

        assert c._stat_detect_failed == 0

    @pytest.mark.asyncio
    async def test_no_hint_when_routing_already_locked(self, capsys):
        """No hint when routing is already locked — detection is skipped entirely."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        c._routing_locked = True
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value=None) as mock_detect:
            for _ in range(5):
                await c._handle_input_transcript(ws, "hi")

        out = capsys.readouterr().out
        assert "Language detection uncertain" not in out
        # detect_lang should not even be called once routing is locked
        mock_detect.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_hint_when_src_explicitly_set(self, capsys):
        """No hint when src is explicit — detection is skipped."""
        c = _make_client(src_lang="vi", tgt_lang="en", meeting_mode="locked")
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value=None) as mock_detect:
            for _ in range(5):
                await c._handle_input_transcript(ws, "hi")

        out = capsys.readouterr().out
        assert "Language detection uncertain" not in out
        mock_detect.assert_not_called()


# ---------------------------------------------------------------------------
# Full detection → lock flow
# ---------------------------------------------------------------------------

class TestDetectionLockFlow:
    @pytest.mark.asyncio
    async def test_successful_detection_locks_routing_in_locked_mode(self, capsys):
        """On first successful detection in locked mode, routing is committed."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        assert not c._routing_locked
        ws = _fake_ws()

        with patch("server.brain.realtime.client.detect_lang", return_value="vi"):
            await c._handle_input_transcript(ws, "Xin chào bạn")

        assert c._routing_locked is True
        # session.update should have been sent with new routing instructions
        ws.send.assert_called_once()
        payload = json.loads(ws.send.call_args[0][0])
        assert payload["type"] == "session.update"

    @pytest.mark.asyncio
    async def test_no_session_update_after_routing_locked(self, capsys):
        """Once locked, further transcripts do NOT trigger another session.update."""
        c = _make_client(src_lang="auto", tgt_lang="auto", meeting_mode="locked")
        ws = _fake_ws()

        # Lock on first detection
        with patch("server.brain.realtime.client.detect_lang", return_value="vi"):
            await c._handle_input_transcript(ws, "Xin chào")

        assert c._routing_locked is True
        ws.send.reset_mock()

        # Second transcript — should be ignored (routing locked)
        with patch("server.brain.realtime.client.detect_lang", return_value="en"):
            await c._handle_input_transcript(ws, "Hello world")

        ws.send.assert_not_called()
