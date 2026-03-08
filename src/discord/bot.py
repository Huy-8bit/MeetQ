"""
src/discord/bot.py
Discord bot that joins a voice channel, captures audio from participants,
translates via OpenAI Realtime API, and optionally speaks translations back.

Design:
  - Uses discord.py with voice support (PyNaCl + libopus).
  - Bot joins a voice channel via slash-command or auto-join on startup.
  - Captures mixed audio from all speakers in the channel.
  - Pipes audio through RealtimeClient for real-time translation.
  - Translated text is posted to a designated text channel.
  - Optionally, TTS audio is played back into the voice channel.
  - Ctrl+C or !leave command stops the bot gracefully.

Environment:
  DISCORD_BOT_TOKEN   Required. Your Discord bot token.
  OPENAI_API_KEY      Required. Your OpenAI API key.

Usage (from discord entrypoint):
    bot = InterpreterBot(
        openai_api_key="sk-...",
        src_lang="auto",
        tgt_lang="auto",
        meeting_mode="locked",
        enable_tts=True,
        debug=False,
    )
    bot.run(token)
"""
from __future__ import annotations

import asyncio
import time as _time_mod
import threading
from typing import Optional

try:
    import discord
    from discord.ext import commands
except ImportError:
    raise ImportError(
        "discord.py[voice] is required.  Install with:\n"
        "  pip install 'discord.py[voice]'"
    )

from src.common.lang import parse_pairs
from src.common.logging_utils import get_logger, print_translation

logger = get_logger("discord.bot")


# ---------------------------------------------------------------------------
# Monkey-patch voice_recv to add DAVE E2E decryption.
# discord-ext-voice-recv only does transport-layer decryption (NaCl).
# Discord mandates DAVE E2EE, so after transport decrypt the opus data
# is still DAVE-encrypted.  We inject a step in PacketDecoder._process_packet
# to DAVE-decrypt before the Opus decoder sees the data.
#
# If the DAVE session isn't ready yet (MLS handshake in progress) or the
# SSRC→user mapping is unknown, we SKIP the packet to avoid crashing the
# Opus decoder on encrypted garbage.
# ---------------------------------------------------------------------------
def _patch_dave_decryption() -> None:
    try:
        from discord.ext.voice_recv.opus import PacketDecoder

        _original_process = PacketDecoder._process_packet

        def _dave_process_packet(self, packet):
            """Patched: DAVE-decrypt packet.decrypted_data before opus decode."""
            from discord.ext.voice_recv import VoiceData

            if packet and packet.decrypted_data:
                vc = self.sink.voice_client
                conn = getattr(vc, '_connection', None)
                dave_session = getattr(conn, 'dave_session', None) if conn else None
                dave_active = getattr(conn, 'dave_protocol_version', 0) > 0 if conn else False

                if dave_active:
                    if not dave_session or not dave_session.ready:
                        # DAVE negotiated but MLS handshake not done yet — skip
                        if not getattr(self, '_dave_wait_logged', False):
                            logger.debug(
                                "[DAVE] Session not ready (ssrc %s, ready=%s)",
                                self.ssrc,
                                dave_session.ready if dave_session else 'no session',
                            )
                            self._dave_wait_logged = True
                        return VoiceData(packet, self._get_cached_member(), pcm=None)

                    # DAVE session ready — try to decrypt
                    ssrc_map = getattr(vc, '_ssrc_to_id', {})
                    user_id = ssrc_map.get(self.ssrc)
                    if user_id is None:
                        return VoiceData(packet, self._get_cached_member(), pcm=None)

                    try:
                        import davey
                        decrypted = dave_session.decrypt(
                            user_id, davey.MediaType.audio, packet.decrypted_data
                        )
                        # Log first successful decrypt for diagnostics
                        if not getattr(self, '_dave_ok_logged', False):
                            logger.info(
                                "[DAVE] decrypt OK ssrc=%s raw=%d→dec=%d",
                                self.ssrc,
                                len(packet.decrypted_data),
                                len(decrypted) if decrypted else 0,
                            )
                            self._dave_ok_logged = True
                        packet.decrypted_data = decrypted
                        self._dave_wait_logged = False
                        # Reset error flag on success so future errors are logged
                        self._dave_err_logged = False
                    except Exception as e:
                        cnt = getattr(self, '_dave_err_count', 0) + 1
                        self._dave_err_count = cnt
                        if not getattr(self, '_dave_err_logged', False):
                            logger.warning("[DAVE] decrypt err ssrc=%s: %s", self.ssrc, e)
                            self._dave_err_logged = True
                        elif cnt % 500 == 0:
                            logger.debug("[DAVE] %d packets skipped (decrypt failed)", cnt)
                        return VoiceData(packet, self._get_cached_member(), pcm=None)

            # Wrap original _process_packet to survive OpusError on bad data
            try:
                return _original_process(self, packet)
            except Exception as e:
                if not getattr(self, '_opus_err_logged', False):
                    logger.warning("[DAVE] Opus decode error (ssrc=%s): %s", self.ssrc, e)
                    self._opus_err_logged = True
                return VoiceData(packet, self._get_cached_member(), pcm=None)

        PacketDecoder._process_packet = _dave_process_packet
        logger.debug("[Patch] voice_recv DAVE decryption injected into PacketDecoder._process_packet")
    except ImportError as e:
        logger.warning("[Patch] Failed to patch DAVE decryption: %s", e)

_patch_dave_decryption()


# ---------------------------------------------------------------------------
# Monkey-patch UDPKeepAlive to work with discord.py 2.7.1
# discord.py 2.7.1 connect()s the UDP socket so sendto() fails with
# "OSError: [Errno 56] Socket is already connected". Use send() instead.
# ---------------------------------------------------------------------------
def _patch_udp_keepalive() -> None:
    try:
        from discord.ext.voice_recv.reader import UDPKeepAlive
        import time

        def _patched_run(self) -> None:
            self.voice_client.wait_until_connected()
            while not self._end_thread.is_set():
                vc = self.voice_client
                try:
                    packet = self.counter.to_bytes(8, 'big')
                except OverflowError:
                    self.counter = 0
                    continue
                try:
                    # Use send() instead of sendto() for connected sockets
                    vc._connection.socket.send(packet)
                except Exception:
                    # On error, wait a bit before retrying (avoid tight loop)
                    time.sleep(1)
                    vc.wait_until_connected()
                    if vc.is_connected():
                        continue
                    break
                else:
                    self.counter += 1
                    time.sleep(self.delay / 1000)  # delay is in ms

        UDPKeepAlive.run = _patched_run
        logger.debug("[Patch] UDPKeepAlive.run patched for connected sockets")
    except ImportError:
        pass

_patch_udp_keepalive()

class InterpreterBot(commands.Bot):
    """
    Discord bot that joins voice channels and provides real-time
    speech translation (Vietnamese / English / Japanese).
    """

    def __init__(
        self,
        openai_api_key: str,
        model: Optional[str] = None,
        src_lang: str = "auto",
        tgt_lang: str = "auto",
        pairs: str = "",
        meeting_mode: str = "locked",
        enable_tts: bool = True,
        show_input: bool = False,
        debug: bool = False,
        text_channel_id: Optional[int] = None,
        auto_join_voice_channel_id: Optional[int] = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="brseAI — Discord voice interpreter bot (VI/EN/JA)",
        )

        self.openai_api_key = openai_api_key
        self.model = model
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.pairs = pairs
        self.meeting_mode = meeting_mode
        self.enable_tts = enable_tts
        self.show_input = show_input
        self.debug = debug
        self.text_channel_id = text_channel_id
        self.auto_join_voice_channel_id = auto_join_voice_channel_id

        # Runtime state
        self._voice_client: Optional[discord.VoiceClient] = None
        self._audio_input = None  # DiscordAudioInput
        self._audio_output = None  # DiscordAudioOutput
        self._audio_sink = None   # DiscordAudioSink — kept alive to prevent GC
        self._realtime_client = None  # RealtimeClient
        self._interpreter_task: Optional[asyncio.Task] = None
        self._text_channel: Optional[discord.TextChannel] = None
        self._join_timestamp: float = 0  # epoch when we last joined voice

        # Register commands
        self._register_commands()

    def _register_commands(self) -> None:
        """Register bot text commands (!join, !leave, !status, !lang)."""

        @self.command(name="join", help="Join your current voice channel and start interpreting.")
        async def cmd_join(ctx: commands.Context):
            if ctx.author.voice is None or ctx.author.voice.channel is None:
                await ctx.send("You need to be in a voice channel first.")
                return
            voice_channel = ctx.author.voice.channel
            self._text_channel = ctx.channel
            await self._join_and_start(voice_channel, ctx.channel)
            await ctx.send(
                f"Joined **{voice_channel.name}** — translating "
                f"(src={self.src_lang}, tgt={self.tgt_lang}, mode={self.meeting_mode})"
            )

        @self.command(name="leave", help="Leave the voice channel and stop interpreting.")
        async def cmd_leave(ctx: commands.Context):
            await self._stop_and_leave()
            await ctx.send("Left voice channel. Interpreter stopped.")

        @self.command(name="status", help="Show current interpreter status.")
        async def cmd_status(ctx: commands.Context):
            if self._voice_client and self._voice_client.is_connected():
                vc = self._voice_client.channel
                stats = ""
                if self._realtime_client:
                    rc = self._realtime_client
                    stats = (
                        f"\nTranscripts: {rc._stat_transcripts} | "
                        f"Translations: {rc._stat_translations} | "
                        f"Audio chunks: {rc._stat_audio_chunks}"
                    )
                await ctx.send(
                    f"Connected to **{vc.name}** | "
                    f"src={self.src_lang} tgt={self.tgt_lang} | "
                    f"mode={self.meeting_mode} | tts={'on' if self.enable_tts else 'off'}"
                    f"{stats}"
                )
            else:
                await ctx.send("Not connected to any voice channel. Use `!join`.")

        @self.command(name="lang", help="Change language pair. Usage: !lang <src> <tgt>")
        async def cmd_lang(ctx: commands.Context, src: str = "auto", tgt: str = "auto"):
            valid = {"auto", "vi", "en", "ja"}
            if src not in valid or tgt not in valid:
                await ctx.send(f"Valid languages: {', '.join(sorted(valid))}")
                return
            self.src_lang = src
            self.tgt_lang = tgt
            await ctx.send(f"Language updated: src={src}, tgt={tgt}")
            # If interpreter is running, it will pick up the change on next session.update

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info(f"[DiscordBot] Logged in as {self.user} (id={self.user.id})")
        print(f"[DiscordBot] Logged in as {self.user}", flush=True)

        # Auto-join voice channel if configured
        if self.auto_join_voice_channel_id:
            # Wait a moment for the gateway to stabilise before connecting voice
            await asyncio.sleep(2)
            try:
                # fetch_channel is more reliable than get_channel (cache may be empty)
                channel = self.get_channel(self.auto_join_voice_channel_id)
                if channel is None:
                    channel = await self.fetch_channel(self.auto_join_voice_channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    logger.warning(
                        f"[DiscordBot] Channel {self.auto_join_voice_channel_id} "
                        f"is {type(channel).__name__}, not a VoiceChannel."
                    )
                    return

                # Find a text channel to post translations
                text_ch = None
                if self.text_channel_id:
                    text_ch = self.get_channel(self.text_channel_id)
                    if text_ch is None:
                        text_ch = await self.fetch_channel(self.text_channel_id)
                if text_ch is None:
                    # Use the first text channel in the same guild
                    for ch in channel.guild.text_channels:
                        if ch.permissions_for(channel.guild.me).send_messages:
                            text_ch = ch
                            break
                self._text_channel = text_ch
                await self._join_and_start(channel, text_ch)
                if text_ch:
                    await text_ch.send(
                        f"Auto-joined **{channel.name}** — translating "
                        f"(src={self.src_lang}, tgt={self.tgt_lang})"
                    )
            except discord.NotFound:
                logger.error(
                    f"[DiscordBot] Voice channel {self.auto_join_voice_channel_id} not found."
                )
            except discord.Forbidden:
                logger.error(
                    f"[DiscordBot] No permission to access channel {self.auto_join_voice_channel_id}."
                )
            except Exception as exc:
                logger.error(f"[DiscordBot] Auto-join failed: {exc}", exc_info=True)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """
        If the bot is the only one left in the voice channel, auto-leave
        to save resources.
        """
        if self._voice_client is None or not self._voice_client.is_connected():
            return
        # Ignore our own voice-state changes (e.g. bot joining triggers this)
        if member.id == self.user.id:
            return
        # Grace period: don't auto-leave within 10s of joining (cache may be stale)
        if _time_mod.time() - self._join_timestamp < 10:
            return
        vc_channel = self._voice_client.channel
        # Check if the channel now has only the bot
        members = [m for m in vc_channel.members if not m.bot]
        if len(members) == 0:
            logger.info("[DiscordBot] All users left the voice channel — auto-leaving.")
            if self._text_channel:
                try:
                    await self._text_channel.send(
                        "All users left the voice channel. Interpreter stopped."
                    )
                except Exception:
                    pass
            await self._stop_and_leave()

    # ------------------------------------------------------------------
    # Core: join, start interpreter, stop
    # ------------------------------------------------------------------

    async def _join_and_start(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """Join a voice channel and start the real-time interpreter pipeline."""
        # Stop previous session if any (only if something is actually running)
        if self._voice_client and self._voice_client.is_connected():
            await self._stop_and_leave()

        from src.discord.audio import DiscordAudioInput, DiscordAudioOutput, DiscordAudioSink
        from src.realtime.client import DEFAULT_MODEL, RealtimeClient
        from discord.ext.voice_recv import VoiceRecvClient

        # Connect to voice using VoiceRecvClient (supports .listen())
        # Retry a few times in case of transient gateway issues
        for attempt in range(1, 4):
            try:
                self._voice_client = await voice_channel.connect(
                    cls=VoiceRecvClient, self_deaf=False
                )
                break
            except Exception as exc:
                logger.warning(
                    f"[DiscordBot] Voice connect attempt {attempt}/3 failed: {exc}"
                )
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * attempt)

        logger.info(f"[DiscordBot] Connected to voice: {voice_channel.name}")

        self._join_timestamp = _time_mod.time()

        # Create audio input
        self._audio_input = DiscordAudioInput()
        self._audio_input.start()

        # Start listening to voice channel — keep reference to prevent GC
        self._audio_sink = DiscordAudioSink(self._audio_input)
        self._voice_client.listen(self._audio_sink)

        # Create audio output (TTS back to voice channel)
        if self.enable_tts:
            self._audio_output = DiscordAudioOutput(self._voice_client)
            self._audio_output.start()

        # Build RealtimeClient
        model = self.model or DEFAULT_MODEL
        allowed_pairs = parse_pairs(self.pairs)

        self._realtime_client = RealtimeClient(
            api_key=self.openai_api_key,
            model=model,
            enable_speaker=self.enable_tts,
            debug=self.debug,
            src_lang=self.src_lang,
            tgt_lang=self.tgt_lang,
            allowed_pairs=allowed_pairs,
            show_input=self.show_input,
            meeting_mode=self.meeting_mode,
            audio_input=self._audio_input,
        )

        # Patch player with Discord audio output
        if self._audio_output is not None:
            self._realtime_client._player = self._audio_output

        # Optionally set up text channel forwarding
        if text_channel:
            self._text_channel = text_channel
            self._setup_text_forwarding()

        # Run interpreter as background task
        self._interpreter_task = asyncio.create_task(self._run_interpreter())

        print(
            f"[DiscordBot] Interpreter started | channel={voice_channel.name}"
            f" | src={self.src_lang} tgt={self.tgt_lang}"
            f" | mode={self.meeting_mode} | tts={'on' if self.enable_tts else 'off'}",
            flush=True,
        )

    def _setup_text_forwarding(self) -> None:
        """
        Monkeypatch print_translation to also send translations to
        the Discord text channel.
        """
        from src.common import logging_utils

        original_print = logging_utils.print_translation
        self._original_print_translation = original_print
        text_channel = self._text_channel
        bot_loop = self.loop
        self._translation_buffer = ""

        def _forwarding_print(text: str, end: str = "", flush: bool = True) -> None:
            # Call original
            original_print(text, end=end, flush=flush)
            # Accumulate translation text; send to Discord on newline
            self._translation_buffer += text + end
            if "\n" in self._translation_buffer:
                lines = self._translation_buffer.split("\n")
                for line in lines[:-1]:
                    line = line.strip()
                    if line and text_channel and not line.startswith("[You]"):
                        # Remove [Interp] prefix for cleaner Discord output
                        clean = line.replace("[Interp] ", "").replace("[Interp]", "").strip()
                        if clean:
                            asyncio.run_coroutine_threadsafe(
                                text_channel.send(f"**[Translation]** {clean}"),
                                bot_loop,
                            )
                self._translation_buffer = lines[-1]

        logging_utils.print_translation = _forwarding_print

    def _restore_print_translation(self) -> None:
        """Restore original print_translation after stopping."""
        from src.common import logging_utils
        if hasattr(self, "_original_print_translation"):
            logging_utils.print_translation = self._original_print_translation

    async def _run_interpreter(self) -> None:
        """Run the RealtimeClient in the bot async context."""
        client = self._realtime_client
        if client is None:
            return
        client._running = True
        try:
            await client._run_with_retry()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[DiscordBot] Interpreter error: {exc}", exc_info=True)
        finally:
            client._running = False
            if client._player:
                client._player.stop()

    async def _stop_and_leave(self) -> None:
        """Stop the interpreter and disconnect from voice."""
        # Cancel interpreter task
        if self._interpreter_task and not self._interpreter_task.done():
            self._interpreter_task.cancel()
            try:
                await self._interpreter_task
            except asyncio.CancelledError:
                pass
            self._interpreter_task = None

        # Stop RealtimeClient
        if self._realtime_client:
            self._realtime_client._running = False
            self._realtime_client = None

        # Stop audio output
        if self._audio_output:
            self._audio_output.stop()
            self._audio_output = None

        # Stop audio input
        if self._audio_input:
            self._audio_input.stop()
            self._audio_input = None

        # Release sink reference
        self._audio_sink = None

        # Disconnect from voice
        if self._voice_client and self._voice_client.is_connected():
            # Stop listening first
            try:
                self._voice_client.stop_listening()
            except Exception:
                pass
            await self._voice_client.disconnect()
            self._voice_client = None

        # Restore print_translation
        self._restore_print_translation()

        logger.info("[DiscordBot] Stopped and disconnected.")
