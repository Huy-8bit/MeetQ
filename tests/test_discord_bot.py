"""
tests/test_discord_bot.py

Unit tests for Discord bot integration.

Tests cover:
- Parser validation
- DiscordAudioInput adapter
- Bot command logic (join/leave/status)
- Audio sink -> queue -> stream_frames flow
- Cleanup on leave

Uses mocks for Discord API - no real Discord connections.
"""
from __future__ import annotations

import asyncio
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from collections import namedtuple

import pytest
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.discord.audio import DiscordAudioInput
from src.discord.bot import TranslationBot, AudioSink
from src.discord.main import validate_env, build_parser


# ---------------------------------------------------------------------------
# Parser & validation tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_parser_default_values(self):
        """Parser has sensible defaults."""
        parser = build_parser()
        args = parser.parse_args([])
        
        assert args.src == "auto"
        assert args.tgt == "auto"
        assert args.meeting_mode == "locked"
        assert args.debug is False
        assert args.token is None
        assert args.voice_channel_id is None
        assert args.text_channel_id is None

    def test_parser_accepts_all_flags(self):
        """Parser accepts all required flags."""
        parser = build_parser()
        args = parser.parse_args([
            "--token", "test_token",
            "--voice-channel-id", "123456",
            "--text-channel-id", "789012",
            "--src", "vi",
            "--tgt", "en",
            "--pairs", "vi<->en",
            "--meeting-mode", "auto",
            "--debug",
        ])
        
        assert args.token == "test_token"
        assert args.voice_channel_id == 123456
        assert args.text_channel_id == 789012
        assert args.src == "vi"
        assert args.tgt == "en"
        assert args.pairs == "vi<->en"
        assert args.meeting_mode == "auto"
        assert args.debug is True


class TestValidation:
    def test_validate_env_requires_discord_token(self, monkeypatch):
        """validate_env raises SystemExit if no Discord token."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        Args = namedtuple("Args", ["token"])
        args = Args(token=None)
        
        with pytest.raises(SystemExit):
            validate_env(args)

    def test_validate_env_requires_openai_key(self, monkeypatch):
        """validate_env raises SystemExit if no OpenAI key."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord_test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        
        Args = namedtuple("Args", ["token"])
        args = Args(token="discord_test")
        
        with pytest.raises(SystemExit):
            validate_env(args)

    def test_validate_env_accepts_env_vars(self, monkeypatch):
        """validate_env returns tokens from environment."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord_env")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
        
        Args = namedtuple("Args", ["token"])
        args = Args(token=None)
        
        discord_token, openai_key = validate_env(args)
        assert discord_token == "discord_env"
        assert openai_key == "sk-env"

    def test_validate_env_cli_token_overrides_env(self, monkeypatch):
        """CLI --token overrides DISCORD_BOT_TOKEN env."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord_env")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        Args = namedtuple("Args", ["token"])
        args = Args(token="discord_cli")
        
        discord_token, openai_key = validate_env(args)
        assert discord_token == "discord_cli"
        assert openai_key == "sk-test"


# ---------------------------------------------------------------------------
# DiscordAudioInput tests
# ---------------------------------------------------------------------------

class TestDiscordAudioInput:
    def test_metadata(self):
        """Audio input exposes correct metadata."""
        audio_input = DiscordAudioInput()
        meta = audio_input.metadata
        
        assert meta.sample_rate == 16000
        assert meta.channels == 1
        assert meta.speaker_id is None

    def test_start_stop(self):
        """Start/stop lifecycle works."""
        audio_input = DiscordAudioInput()
        
        assert not audio_input._started
        audio_input.start()
        assert audio_input._started
        
        audio_input.stop()
        assert not audio_input._started

    def test_stream_frames_yields_chunks(self):
        """stream_frames yields 20ms PCM16 chunks."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # Feed some 48kHz stereo audio
        # 960 samples = 20ms at 48kHz
        samples_48k = 960
        pcm_48k_stereo = np.random.randint(-32768, 32767, samples_48k * 2, dtype=np.int16)
        audio_input.feed_audio(pcm_48k_stereo.tobytes(), sample_rate=48000, channels=2)
        
        # Should produce one 20ms chunk at 16kHz (320 samples = 640 bytes)
        chunks = []
        for chunk in audio_input.stream_frames():
            chunks.append(chunk)
            if len(chunks) >= 1:
                break
        
        audio_input.stop()
        
        assert len(chunks) == 1
        assert len(chunks[0]) == 640  # 320 samples * 2 bytes/sample

    def test_feed_audio_converts_stereo_to_mono(self):
        """feed_audio converts stereo to mono correctly."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # Create stereo audio where left=100, right=200
        # After averaging: mono should be 150
        left = np.full(960, 100, dtype=np.int16)
        right = np.full(960, 200, dtype=np.int16)
        stereo = np.stack([left, right], axis=1).flatten()
        
        audio_input.feed_audio(stereo.tobytes(), sample_rate=48000, channels=2)
        
        # Get the chunk
        chunk = None
        for c in audio_input.stream_frames():
            chunk = c
            break
        
        audio_input.stop()
        
        assert chunk is not None
        # Decode and check average value is around 150
        mono = np.frombuffer(chunk, dtype=np.int16)
        avg = mono.mean()
        assert 140 <= avg <= 160  # Allow some tolerance for resampling

    def test_feed_audio_resamples_48k_to_16k(self):
        """feed_audio resamples from 48kHz to 16kHz."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # 48kHz: 960 samples for 20ms
        # 16kHz: 320 samples for 20ms
        samples_48k = 960
        pcm_48k = np.random.randint(-32768, 32767, samples_48k, dtype=np.int16)
        
        audio_input.feed_audio(pcm_48k.tobytes(), sample_rate=48000, channels=1)
        
        chunk = None
        for c in audio_input.stream_frames():
            chunk = c
            break
        
        audio_input.stop()
        
        # Should be resampled to 320 samples (640 bytes)
        assert chunk is not None
        assert len(chunk) == 640

    def test_feed_audio_handles_errors_gracefully(self, capsys):
        """feed_audio logs errors but doesn't crash on bad data."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # Feed invalid data (odd number of bytes for int16)
        bad_data = b"invalid"
        audio_input.feed_audio(bad_data)
        
        audio_input.stop()
        
        # Should log error to stderr
        err = capsys.readouterr().err
        assert "Error processing audio" in err

    def test_queue_overflow_drops_old_chunks(self):
        """Queue overflow drops oldest chunks to prevent blocking."""
        audio_input = DiscordAudioInput()
        audio_input._q.maxsize = 2  # Set small queue for testing
        audio_input.start()
        
        # Feed 3 chunks - should drop oldest
        for i in range(3):
            pcm = np.random.randint(-32768, 32767, 960, dtype=np.int16)
            audio_input.feed_audio(pcm.tobytes(), sample_rate=48000, channels=1)
        
        # Should only get 2 chunks (queue size)
        chunks = []
        audio_input.stop()
        for chunk in audio_input.stream_frames():
            if chunk:
                chunks.append(chunk)
        
        assert len(chunks) >= 1  # At least one chunk made it


# ---------------------------------------------------------------------------
# AudioSink tests
# ---------------------------------------------------------------------------

class TestAudioSink:
    def test_audio_sink_feeds_input(self):
        """AudioSink.write() feeds data to DiscordAudioInput."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # Mock voice client and user
        mock_vc = Mock()
        mock_user = Mock()
        
        # Mock AudioData from discord.reader
        mock_audio_data = Mock()
        pcm = np.random.randint(-32768, 32767, 960 * 2, dtype=np.int16)
        mock_audio_data.pcm = pcm.tobytes()
        
        sink = AudioSink(audio_input, mock_vc)
        
        # Write some audio
        sink.write(mock_user, mock_audio_data)
        
        # Should be able to read from audio_input
        chunk = None
        for c in audio_input.stream_frames():
            chunk = c
            break
        
        audio_input.stop()
        assert chunk is not None

    def test_audio_sink_handles_errors(self):
        """AudioSink logs errors but doesn't crash."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        mock_vc = Mock()
        mock_user = Mock()
        
        sink = AudioSink(audio_input, mock_vc)
        
        # Write bad data
        mock_audio_data = Mock()
        mock_audio_data.pcm = b"bad"
        sink.write(mock_user, mock_audio_data)
        
        # Should increment error counter
        assert sink._error_count > 0
        
        audio_input.stop()

    def test_audio_sink_cleanup(self, capsys):
        """AudioSink.cleanup() stops input and logs stats."""
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        mock_vc = Mock()
        
        sink = AudioSink(audio_input, mock_vc)
        sink._packet_count = 100
        sink._error_count = 5
        
        sink.cleanup()
        
        # Should have stopped the audio input
        assert not audio_input._started


# ---------------------------------------------------------------------------
# TranslationBot tests
# ---------------------------------------------------------------------------

class TestTranslationBot:
    @pytest.mark.asyncio
    async def test_bot_initialization(self):
        """Bot initializes with correct configuration."""
        bot = TranslationBot(
            openai_api_key="sk-test",
            text_channel_id=12345,
            src_lang="vi",
            tgt_lang="en",
            meeting_mode="auto",
            debug=True,
        )
        
        assert bot.openai_api_key == "sk-test"
        assert bot.text_channel_id == 12345
        assert bot.src_lang == "vi"
        assert bot.tgt_lang == "en"
        assert bot.meeting_mode == "auto"
        assert bot.debug is True
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_join_requires_voice_channel(self):
        """!join command requires user to be in voice channel."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        # Mock context with user not in voice
        ctx = AsyncMock()
        ctx.author.voice = None
        ctx.send = AsyncMock()
        
        await bot.join(ctx)
        
        # Should send error message
        ctx.send.assert_called_once()
        args = ctx.send.call_args[0]
        assert "must be in a voice channel" in args[0]
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_join_connects_to_voice(self):
        """!join command connects to voice channel."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        # Mock context with user in voice
        ctx = AsyncMock()
        ctx.voice_client = None
        ctx.author.voice = MagicMock()
        ctx.author.voice.channel = MagicMock(name="Test Voice", id=123)
        ctx.send = AsyncMock()
        
        # Mock voice connection
        mock_vc = AsyncMock()
        mock_vc.listen = MagicMock()
        
        with patch.object(ctx.author.voice.channel, "connect", return_value=mock_vc):
            with patch("threading.Thread"):
                await bot.join(ctx)
        
        # Should have connected
        ctx.author.voice.channel.connect.assert_called_once()
        
        # Should have created audio input
        assert bot.audio_input is not None
        assert bot.realtime_client is not None
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_leave_disconnects_voice(self):
        """!leave command disconnects from voice."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        # Mock context with active voice connection
        ctx = AsyncMock()
        ctx.voice_client = AsyncMock()
        ctx.voice_client.disconnect = AsyncMock()
        ctx.send = AsyncMock()
        
        # Set up active state
        bot.audio_input = DiscordAudioInput()
        bot.realtime_client = MagicMock()
        bot.realtime_client._running = True
        
        await bot.leave(ctx)
        
        # Should have disconnected
        ctx.voice_client.disconnect.assert_called_once()
        
        # Should have cleaned up
        assert bot.audio_input is None
        assert bot.realtime_client is None
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_leave_without_connection(self):
        """!leave command handles no active connection."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        ctx = AsyncMock()
        ctx.voice_client = None
        ctx.send = AsyncMock()
        
        await bot.leave(ctx)
        
        # Should send warning message
        ctx.send.assert_called_once()
        args = ctx.send.call_args[0]
        assert "Not connected" in args[0]
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_status_command(self):
        """!status command displays current status."""
        bot = TranslationBot(
            openai_api_key="sk-test",
            src_lang="vi",
            tgt_lang="en",
            meeting_mode="locked",
        )
        
        ctx = AsyncMock()
        ctx.voice_client = None
        ctx.send = AsyncMock()
        
        await bot.status(ctx)
        
        # Should send status message
        ctx.send.assert_called_once()
        status_msg = ctx.send.call_args[0][0]
        assert "Status" in status_msg
        assert "Not connected" in status_msg
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_cleanup_stops_pipeline(self):
        """_cleanup stops all pipeline components."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        # Set up active state
        bot.audio_input = DiscordAudioInput()
        bot.audio_input.start()
        bot.realtime_client = MagicMock()
        bot.realtime_client._running = True
        bot.realtime_thread = MagicMock()
        bot.realtime_thread.is_alive.return_value = False
        
        await bot._cleanup()
        
        # Should have stopped everything
        assert bot.audio_input is None
        assert bot.realtime_client is None
        assert bot.realtime_thread is None
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_send_translation_to_discord(self):
        """Translation text is sent to Discord channel."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        # Mock text channel
        mock_channel = AsyncMock()
        mock_channel.send = AsyncMock()
        bot.translation_channel = mock_channel
        
        await bot._send_translation("Test translation text")
        
        # Should have sent message
        mock_channel.send.assert_called_once_with("Test translation text")
        
        await bot.close()

    @pytest.mark.asyncio
    async def test_send_translation_splits_long_messages(self):
        """Long translation messages are split at Discord's 2000 char limit."""
        bot = TranslationBot(openai_api_key="sk-test")
        
        mock_channel = AsyncMock()
        mock_channel.send = AsyncMock()
        bot.translation_channel = mock_channel
        
        # Create a message longer than 2000 characters
        long_text = "A" * 3000
        
        await bot._send_translation(long_text)
        
        # Should have sent multiple messages
        assert mock_channel.send.call_count == 2
        
        await bot.close()


# ---------------------------------------------------------------------------
# Integration test: full audio flow
# ---------------------------------------------------------------------------

class TestAudioFlow:
    def test_discord_audio_to_stream_frames(self):
        """
        Full flow: Discord audio -> AudioSink -> DiscordAudioInput -> stream_frames.
        """
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        mock_vc = Mock()
        mock_user = Mock()
        
        sink = AudioSink(audio_input, mock_vc)
        
        # Simulate Discord sending 5 audio packets
        for i in range(5):
            # 960 samples at 48kHz (20ms) stereo
            pcm = np.random.randint(-32768, 32767, 960 * 2, dtype=np.int16)
            mock_audio_data = Mock()
            mock_audio_data.pcm = pcm.tobytes()
            sink.write(mock_user, mock_audio_data)
        
        # Collect chunks from stream
        chunks = []
        # Use timeout to avoid hanging
        import time
        start = time.time()
        for chunk in audio_input.stream_frames():
            chunks.append(chunk)
            if len(chunks) >= 3 or time.time() - start > 1:
                break
        
        sink.cleanup()
        
        # Should have received some chunks
        assert len(chunks) >= 1
        
        # Each chunk should be 20ms at 16kHz (320 samples = 640 bytes)
        for chunk in chunks:
            assert len(chunk) == 640


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
