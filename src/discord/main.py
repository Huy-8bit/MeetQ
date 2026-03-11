"""
src/discord/main.py
Discord bot CLI entry point for realtime voice translation.

Usage:
    python -m src.discord.main --token <TOKEN> [options]
    
    # Or use environment variable:
    export DISCORD_BOT_TOKEN=<your_token>
    python -m src.discord.main [options]

Example:
    python -m src.discord.main \\
        --token abc123... \\
        --voice-channel-id 123456789 \\
        --text-channel-id 987654321 \\
        --src auto --tgt en \\
        --debug

Environment Variables:
    DISCORD_BOT_TOKEN   Discord bot token (fallback for --token)
    OPENAI_API_KEY      OpenAI API key (required)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from src.common.lang import parse_pairs, SUPPORTED_LANGS
from src.common.logging_utils import get_logger
from src.discord.bot import TranslationBot

logger = get_logger("discord.main")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for Discord bot CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m src.discord.main",
        description=(
            "Discord Bot for Realtime Voice Translation\n\n"
            "Joins Discord voice channels and provides live translation\n"
            "from Vietnamese, English, and Japanese."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ---- Discord connection ----
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        metavar="TOKEN",
        help="Discord bot token (fallback: env DISCORD_BOT_TOKEN)",
    )
    parser.add_argument(
        "--voice-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Auto-join this voice channel on startup (optional)",
    )
    parser.add_argument(
        "--text-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Send translation output to this text channel (optional)",
    )

    # ---- Language settings ----
    parser.add_argument(
        "--src",
        default="auto",
        choices=list(SUPPORTED_LANGS),
        help="Source language: auto (default), vi, en, ja",
    )
    parser.add_argument(
        "--tgt",
        default="auto",
        choices=list(SUPPORTED_LANGS),
        help="Target language: auto (default), vi, en, ja",
    )
    parser.add_argument(
        "--pairs",
        default="",
        metavar="PAIRS",
        help='Allowed pairs, e.g. "vi<->en,ja<->en". Default: all',
    )
    parser.add_argument(
        "--meeting-mode",
        default="locked",
        choices=["locked", "auto"],
        help="Meeting mode: locked (default) or auto",
    )

    # ---- Debug ----
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser


def validate_env(args: argparse.Namespace) -> tuple[str, str]:
    """
    Validate and return required environment variables.
    
    Returns:
        Tuple of (discord_token, openai_api_key)
    
    Raises:
        SystemExit if required variables are missing
    """
    # Discord token
    discord_token = args.token or os.getenv("DISCORD_BOT_TOKEN")
    if not discord_token:
        logger.error(
            "Discord bot token required. Provide via --token or DISCORD_BOT_TOKEN env variable."
        )
        sys.exit(1)

    # OpenAI API key
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY environment variable is required.")
        sys.exit(1)

    return discord_token, openai_api_key


async def auto_join_voice_channel(bot: TranslationBot, channel_id: int) -> None:
    """
    Auto-join a voice channel after bot is ready.
    
    Args:
        bot: The TranslationBot instance
        channel_id: Discord voice channel ID to join
    """
    await bot.wait_until_ready()
    
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Voice channel {channel_id} not found")
        return
    
    if not hasattr(channel, 'connect'):
        logger.error(f"Channel {channel_id} is not a voice channel")
        return
    
    try:
        from discord.ext.voice_recv import VoiceRecvClient
        from src.discord.audio import DiscordAudioInput
        from src.discord.bot import AudioSink
        
        logger.info(f"Auto-joining voice channel: {channel.name} ({channel_id})")
        
        # Connect to voice channel
        vc = await channel.connect(cls=VoiceRecvClient)
        
        # Create audio input adapter
        bot.audio_input = DiscordAudioInput()
        
        # Create and configure realtime client
        from src.realtime.client import RealtimeClient
        bot.realtime_client = RealtimeClient(
            api_key=bot.openai_api_key,
            audio_input=bot.audio_input,
            enable_speaker=False,
            debug=bot.debug,
            src_lang=bot.src_lang,
            tgt_lang=bot.tgt_lang,
            allowed_pairs=bot.allowed_pairs,
            meeting_mode=bot.meeting_mode,
        )
        
        # Start receiving audio
        sink = AudioSink(bot.audio_input, vc)
        vc.listen(sink)
        
        # Start realtime client in background thread
        import threading
        bot.realtime_thread = threading.Thread(
            target=bot.realtime_client.run,
            daemon=True,
        )
        bot.realtime_thread.start()
        
        logger.info(f"Auto-join successful: {channel.name}")
        
        # Send notification to text channel if configured
        if bot.translation_channel:
            await bot.translation_channel.send(
                f"🤖 Bot auto-joined voice channel: **{channel.name}**\n"
                f"📥 Source: `{bot.src_lang}` → 📤 Target: `{bot.tgt_lang}`"
            )
    
    except Exception as e:
        logger.error(f"Failed to auto-join voice channel: {e}", exc_info=True)


def main() -> None:
    """Main entry point for Discord bot."""
    parser = build_parser()
    args = parser.parse_args()

    # Validate environment
    discord_token, openai_api_key = validate_env(args)

    # Parse allowed pairs
    allowed_pairs = parse_pairs(args.pairs) if args.pairs else set()

    # Create bot
    bot = TranslationBot(
        openai_api_key=openai_api_key,
        text_channel_id=args.text_channel_id,
        voice_channel_id=args.voice_channel_id,
        src_lang=args.src,
        tgt_lang=args.tgt,
        allowed_pairs=allowed_pairs,
        meeting_mode=args.meeting_mode,
        debug=args.debug,
    )

    # Run bot
    logger.info("Starting Discord bot...")
    logger.info(f"Language: {args.src} -> {args.tgt} (mode: {args.meeting_mode})")
    
    try:
        bot.run(discord_token)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
