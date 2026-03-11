"""
src/discord/bot.py
Discord bot with voice channel integration and translation pipeline.

Provides:
- Voice channel join/leave commands
- Audio streaming from Discord to RealtimeClient
- Translation output to Discord text channel
"""
from __future__ import annotations

import asyncio
import io
import sys
import threading
import traceback
import wave
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stdout
from typing import Optional

import discord
from discord.ext import commands
from discord.ext.voice_recv import VoiceRecvClient
from discord.ext.voice_recv import BasicSink

from src.common.logging_utils import get_logger, print_translation
from src.discord.audio import DiscordAudioInput
from src.discord.voice_patch import apply_voice_recv_patch
from src.realtime.client import RealtimeClient

logger = get_logger("discord.bot")


class AudioSinkCallback:
    """
    Callback handler for BasicSink to feed Discord voice data into DiscordAudioInput.
    
    BasicSink is more resilient to OpusError than custom AudioSink inheritance.
    """

    def __init__(self, audio_input: DiscordAudioInput, debug: bool = False) -> None:
        self.audio_input = audio_input
        self._packet_count = 0
        self._error_count = 0
        self._running = True
        self._debug = debug
        self._debug_file = None
        
        # Setup debug recording if enabled
        if self._debug:
            recordings_dir = Path("recordings")
            recordings_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = recordings_dir / f"discord_audio_{timestamp}.wav"
            self._debug_file = wave.open(str(debug_path), 'wb')
            self._debug_file.setnchannels(2)  # Discord sends stereo
            self._debug_file.setsampwidth(2)  # 16-bit PCM
            self._debug_file.setframerate(48000)  # Discord uses 48kHz
            logger.info(f"Debug recording to: {debug_path}")

    def __call__(self, user: Optional[discord.User], data) -> None:
        """
        Called by BasicSink when audio packets arrive.
        
        Args:
            user: Discord user who sent the audio (can be None)
            data: VoiceData object containing PCM data
        """
        if not self._running:
            return
        
        try:
            # Extract PCM data from VoiceData
            pcm_data = data.pcm
            if pcm_data:
                # Log first few packets for debugging
                if self._packet_count < 5:
                    logger.info(f"✅ Packet {self._packet_count}: user={user}, data_len={len(pcm_data)}")
                
                # Save to debug file if enabled
                if self._debug and self._debug_file:
                    self._debug_file.writeframes(pcm_data)
                    self._debug_file._file.flush()  # Force flush to disk
                
                # Feed to translation pipeline
                self.audio_input.feed_audio(pcm_data)
                self._packet_count += 1
                
                # Log every 100 packets
                if self._packet_count % 100 == 0:
                    logger.info(f"Received {self._packet_count} audio packets")
        except Exception as e:
            self._error_count += 1
            if self._error_count % 100 == 1:  # Log every 100th error to avoid spam
                logger.warning(f"AudioSinkCallback error (count={self._error_count}): {e}")
    
    def cleanup(self) -> None:
        """Called when stopping."""
        if not self._running:
            return
        
        self._running = False
        logger.info(f"AudioSink cleanup: packets={self._packet_count} errors={self._error_count}")
        
        # Close debug file if open
        if self._debug_file:
            try:
                self._debug_file.close()
                logger.info("Debug recording saved")
            except Exception as e:
                logger.error(f"Error closing debug file: {e}")


class TranslationBot(commands.Bot):
    """
    Discord bot that provides realtime voice translation.
    
    Commands:
        !join  - Join the voice channel of the user who invoked the command
        !leave - Leave voice channel and stop translation
        !status - Display current status
    """

    def __init__(
        self,
        *,
        openai_api_key: str,
        text_channel_id: Optional[int] = None,
        voice_channel_id: Optional[int] = None,
        src_lang: str = "auto",
        tgt_lang: str = "auto",
        allowed_pairs: set = None,
        meeting_mode: str = "locked",
        debug: bool = False,
        **kwargs,
    ) -> None:
        """
        Initialize the translation bot.
        
        Args:
            openai_api_key: OpenAI API key for RealtimeClient
            text_channel_id: Discord text channel ID for translation output
            voice_channel_id: Discord voice channel ID to auto-join on startup
            src_lang: Source language (auto, vi, en, ja)
            tgt_lang: Target language (auto, vi, en, ja)
            allowed_pairs: Set of allowed language pairs
            meeting_mode: "locked" or "auto" meeting mode
            debug: Enable debug logging
            **kwargs: Additional arguments for commands.Bot
        """
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        
        kwargs.setdefault("command_prefix", "!")
        kwargs.setdefault("intents", intents)
        
        super().__init__(**kwargs)
        
        # Apply voice_recv patch for OpusError resilience
        apply_voice_recv_patch()
        
        self.openai_api_key = openai_api_key
        self.text_channel_id = text_channel_id
        self.auto_join_channel_id = voice_channel_id
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.allowed_pairs = allowed_pairs or set()
        self.meeting_mode = meeting_mode
        self.debug = debug
        
        # Translation pipeline state
        self.audio_input: Optional[DiscordAudioInput] = None
        self.realtime_client: Optional[RealtimeClient] = None
        self.realtime_thread: Optional[threading.Thread] = None
        self.translation_channel: Optional[discord.TextChannel] = None
        self._audio_sink_callback: Optional[AudioSinkCallback] = None  # Keep reference
        self._audio_sink: Optional[BasicSink] = None  # Keep reference to prevent GC
        
        # Output redirection for capturing print_translation calls
        self._original_print_translation = print_translation
        self._install_translation_hook()
        
        # Register commands using decorator approach
        self._register_commands()

    async def setup_hook(self) -> None:
        """Called when the bot is starting up. Used for auto-joining voice channel."""
        if self.auto_join_channel_id:
            self.loop.create_task(self._auto_join())

    async def _auto_join(self) -> None:
        """Auto-join the configured voice channel after bot is ready."""
        await self.wait_until_ready()
        
        channel = self.get_channel(self.auto_join_channel_id)
        if not channel:
            logger.error(f"Voice channel {self.auto_join_channel_id} not found")
            return
        
        if not hasattr(channel, 'connect'):
            logger.error(f"Channel {self.auto_join_channel_id} is not a voice channel")
            return
        
        try:
            from discord.ext.voice_recv import VoiceRecvClient
            
            logger.info(f"Auto-joining voice channel: {channel.name} ({self.auto_join_channel_id})")
            
            # Connect to voice channel
            vc = await channel.connect(cls=VoiceRecvClient)
            
            # Create audio input adapter
            self.audio_input = DiscordAudioInput()
            
            # Create and configure realtime client
            self.realtime_client = RealtimeClient(
                api_key=self.openai_api_key,
                audio_input=self.audio_input,
                enable_speaker=False,
                debug=self.debug,
                src_lang=self.src_lang,
                tgt_lang=self.tgt_lang,
                allowed_pairs=self.allowed_pairs,
                meeting_mode=self.meeting_mode,
            )
            
            # Start receiving audio with BasicSink (more resilient to OpusError)
            callback = AudioSinkCallback(self.audio_input, debug=self.debug)
            sink = BasicSink(callback)
            vc.listen(sink)
            
            # Keep strong references to prevent garbage collection
            self._audio_sink_callback = callback
            self._audio_sink = sink
            
            # Start realtime client in background thread
            self.realtime_thread = threading.Thread(
                target=self.realtime_client.run,
                daemon=True,
            )
            self.realtime_thread.start()
            
            logger.info(f"Auto-join successful: {channel.name}")
            
            # Send notification to text channel if configured
            if self.translation_channel:
                await self.translation_channel.send(
                    f"🤖 Bot auto-joined voice channel: **{channel.name}**\n"
                    f"📥 Source: `{self.src_lang}` → 📤 Target: `{self.tgt_lang}`"
                )
        
        except Exception as e:
            logger.error(f"Failed to auto-join voice channel: {e}", exc_info=True)

    def _register_commands(self) -> None:
        """Register bot commands using the command decorator."""
        @self.command(name="join")
        async def join_cmd(ctx: commands.Context) -> None:
            """Join voice channel."""
            await self.join(ctx)
        
        @self.command(name="leave")
        async def leave_cmd(ctx: commands.Context) -> None:
            """Leave voice channel."""
            await self.leave(ctx)
        
        @self.command(name="status")
        async def status_cmd(ctx: commands.Context) -> None:
            """Show status."""
            await self.status(ctx)

    def _install_translation_hook(self) -> None:
        """
        Install a hook to intercept print_translation calls and forward to Discord.
        
        This modifies the global print_translation function to also send output
        to the configured Discord text channel.
        """
        import src.common.logging_utils as logging_utils
        
        original = logging_utils.print_translation
        
        def hooked_print_translation(text: str, end: str = "", flush: bool = True) -> None:
            # Always call original to maintain stdout output
            original(text, end=end, flush=flush)
            
            # Also send to Discord if we have a channel
            if self.translation_channel and text.strip():
                # Send complete lines to Discord to avoid spam
                if end == "\n" or "\n" in text:
                    asyncio.run_coroutine_threadsafe(
                        self._send_translation(text),
                        self.loop
                    )
        
        logging_utils.print_translation = hooked_print_translation

    def _restore_translation_hook(self) -> None:
        """Restore the original print_translation function."""
        import src.common.logging_utils as logging_utils
        logging_utils.print_translation = self._original_print_translation

    async def _send_translation(self, text: str) -> None:
        """
        Send translation text to Discord text channel.
        
        Handles message length limits and errors gracefully.
        """
        if not self.translation_channel:
            return
        
        try:
            # Discord has a 2000 character limit per message
            if len(text) > 2000:
                # Split into chunks
                for i in range(0, len(text), 2000):
                    await self.translation_channel.send(text[i:i+2000])
            else:
                await self.translation_channel.send(text)
        except discord.HTTPException as e:
            logger.warning(f"Failed to send translation to Discord: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending translation: {e}")

    async def on_ready(self) -> None:
        """Called when the bot is ready and connected to Discord."""
        logger.info(f"Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        
        # Resolve text channel if provided
        if self.text_channel_id:
            channel = self.get_channel(self.text_channel_id)
            if isinstance(channel, discord.TextChannel):
                self.translation_channel = channel
                logger.info(f"Translation output -> #{channel.name} ({channel.id})")
            else:
                logger.warning(f"Channel {self.text_channel_id} not found or not a text channel")

    async def join(self, ctx: commands.Context) -> None:
        """
        Join the voice channel of the user who invoked the command.
        
        Usage: !join
        """
        # Check if user is in a voice channel
        if not ctx.author.voice:
            await ctx.send("❌ You must be in a voice channel to use this command.")
            return
        
        # Check if bot is already connected
        if ctx.voice_client:
            await ctx.send("⚠️ Already connected to a voice channel. Use !leave first.")
            return
        
        voice_channel = ctx.author.voice.channel
        
        try:
            await ctx.send(f"🎙️ Joining voice channel: **{voice_channel.name}**")
            
            # Connect to voice channel with voice_recv support
            vc = await voice_channel.connect(cls=VoiceRecvClient)
            
            # Create audio input adapter
            self.audio_input = DiscordAudioInput()
            
            # Create and configure realtime client
            self.realtime_client = RealtimeClient(
                api_key=self.openai_api_key,
                audio_input=self.audio_input,
                enable_speaker=False,  # Text-only translation this round
                debug=self.debug,
                src_lang=self.src_lang,
                tgt_lang=self.tgt_lang,
                allowed_pairs=self.allowed_pairs,
                meeting_mode=self.meeting_mode,
            )
            
            # Start receiving audio with BasicSink (more resilient to OpusError)
            callback = AudioSinkCallback(self.audio_input, debug=self.debug)
            sink = BasicSink(callback)
            vc.listen(sink)
            
            # Keep strong references to prevent garbage collection
            self._audio_sink_callback = callback
            self._audio_sink = sink
            
            # Start realtime client in background thread
            self.realtime_thread = threading.Thread(
                target=self.realtime_client.run,
                daemon=True,
            )
            self.realtime_thread.start()
            
            await ctx.send(
                f"✅ Translation started!\n"
                f"📥 Source: `{self.src_lang}` → 📤 Target: `{self.tgt_lang}`\n"
                f"Mode: `{self.meeting_mode}`"
            )
            
            logger.info(f"Started translation in {voice_channel.name} ({voice_channel.id})")
        
        except asyncio.TimeoutError:
            await ctx.send("❌ Timeout connecting to voice channel. Please try again.")
            logger.error(f"Timeout connecting to {voice_channel.name}")
        
        except Exception as e:
            await ctx.send(f"❌ Error joining voice channel: {e}")
            logger.error(f"Error joining voice channel: {e}", exc_info=True)
            await self._cleanup()

    async def leave(self, ctx: commands.Context) -> None:
        """
        Leave the current voice channel and stop translation.
        
        Usage: !leave
        """
        if not ctx.voice_client:
            await ctx.send("⚠️ Not connected to any voice channel.")
            return
        
        await ctx.send("👋 Leaving voice channel and stopping translation...")
        
        try:
            # Stop voice connection
            await ctx.voice_client.disconnect()
            
            # Clean up translation pipeline
            await self._cleanup()
            
            await ctx.send("✅ Translation stopped.")
            logger.info("Left voice channel and stopped translation")
        
        except Exception as e:
            await ctx.send(f"❌ Error during cleanup: {e}")
            logger.error(f"Error during leave: {e}", exc_info=True)

    async def status(self, ctx: commands.Context) -> None:
        """
        Display current bot status.
        
        Usage: !status
        """
        if not ctx.voice_client:
            await ctx.send("📊 **Status**: Not connected to any voice channel.")
            return
        
        vc = ctx.voice_client
        channel_name = vc.channel.name if vc.channel else "Unknown"
        
        status_lines = [
            "📊 **Translation Bot Status**",
            f"🎙️ Voice Channel: **{channel_name}**",
            f"📥 Source Language: `{self.src_lang}`",
            f"📤 Target Language: `{self.tgt_lang}`",
            f"🔧 Meeting Mode: `{self.meeting_mode}`",
            f"🐛 Debug: `{self.debug}`",
        ]
        
        if self.translation_channel:
            status_lines.append(f"💬 Text Output: #{self.translation_channel.name}")
        
        if self.realtime_client:
            status_lines.append(f"✅ Translation Pipeline: Active")
        else:
            status_lines.append(f"❌ Translation Pipeline: Inactive")
        
        await ctx.send("\n".join(status_lines))

    async def _cleanup(self) -> None:
        """Clean up translation pipeline resources."""
        # Stop realtime client
        if self.realtime_client:
            self.realtime_client._running = False
            self.realtime_client = None
        
        # Stop audio input
        if self.audio_input:
            self.audio_input.stop()
            self.audio_input = None
        
        # Wait for thread to finish
        if self.realtime_thread and self.realtime_thread.is_alive():
            self.realtime_thread.join(timeout=2.0)
            self.realtime_thread = None

    async def close(self) -> None:
        """Clean up resources when bot is shutting down."""
        logger.info("Bot shutting down...")
        
        # Restore original print_translation
        self._restore_translation_hook()
        
        # Clean up translation pipeline
        await self._cleanup()
        
        # Call parent close
        await super().close()
