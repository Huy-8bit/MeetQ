"""
src/discord/main.py
Discord voice interpreter bot entrypoint.

Can be run directly:  python -m src.discord.main [flags]
Or via app.py:        python app.py --mode discord [flags]

Prerequisites:
  1. Create a Discord Application at https://discord.com/developers/applications
  2. Create a Bot and copy the token
  3. Enable these Privileged Gateway Intents:
     - Message Content Intent
     - Server Members Intent (optional)
  4. Invite bot to your server with permissions:
     - Connect, Speak, Use Voice Activity (voice)
     - Send Messages, Read Message History (text)
     Bot invite URL (replace CLIENT_ID):
     https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=3214336&scope=bot
  5. Install system dep:
     - libopus: brew install opus (macOS) / apt install libopus0 (Linux)
     (PyNaCl wheel bundles libsodium; FFmpeg is NOT required)

Environment:
  DISCORD_BOT_TOKEN   Required. Your Discord bot token.
  OPENAI_API_KEY      Required. Your OpenAI API key.

Example run:
  # Join a voice channel interactively via !join command
  python -m src.discord.main

  # Auto-join a specific voice channel on startup
  python -m src.discord.main --voice-channel-id 123456789012345678

  # With TTS speak-back disabled (text-only translation)
  python -m src.discord.main --no-tts

  # With specific language pair locked
  python -m src.discord.main --src ja --tgt vi --meeting-mode locked
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from src.common.lang import SUPPORTED_LANGS
from src.common.logging_utils import get_logger

logger = get_logger("discord.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "brseAI Discord interpreter bot — joins a voice channel and "
            "translates speech in real time (Vietnamese / English / Japanese)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ---- Discord ----
    p.add_argument(
        "--token",
        default=None,
        metavar="TOKEN",
        help="Discord bot token. Default: read from DISCORD_BOT_TOKEN env var.",
    )
    p.add_argument(
        "--voice-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Auto-join this voice channel on startup. If omitted, use !join command.",
    )
    p.add_argument(
        "--text-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Send translation text to this text channel. "
             "Default: auto-detect from the guild.",
    )

    # ---- Interpreter / language ----
    p.add_argument(
        "--model",
        default=None,
        help="Override OpenAI Realtime model ID.",
    )
    p.add_argument(
        "--src",
        default="auto",
        choices=sorted(SUPPORTED_LANGS),
        help="Source language (default: auto-detect).",
    )
    p.add_argument(
        "--tgt",
        default="auto",
        choices=sorted(SUPPORTED_LANGS),
        help="Target language (default: auto-infer from source).",
    )
    p.add_argument(
        "--pairs",
        default="",
        metavar="PAIRS",
        help='Allowed translation pairs, e.g. "vi<->en,ja<->en".',
    )
    p.add_argument(
        "--meeting-mode",
        default="locked",
        choices=["locked", "auto"],
        help=(
            "locked (default): fix language routing after first detection. "
            "auto: re-detect dynamically."
        ),
    )
    p.add_argument(
        "--tts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable TTS speak-back into voice channel. Default: ON. "
             "Use --no-tts for text-only translation.",
    )
    p.add_argument(
        "--show-input",
        action="store_true",
        help="Always print recognized input transcript.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Verbose event + Discord.py logging.",
    )

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve bot token
    token = args.token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        print(
            "Error: Discord bot token is required.\n"
            "  Set DISCORD_BOT_TOKEN environment variable, or pass --token <TOKEN>.\n"
            "  Create a bot at https://discord.com/developers/applications",
            file=sys.stderr,
        )
        return 1

    # Resolve OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    # Check libopus availability
    import ctypes.util
    if not ctypes.util.find_library("opus"):
        print(
            "Warning: libopus not found. Discord voice will not work.\n"
            "  Install: brew install opus (macOS) / apt install libopus0 (Linux)",
            file=sys.stderr,
        )

    from src.discord.bot import InterpreterBot

    # Verbose voice logging only in --debug mode
    if args.debug:
        import logging
        _voice_loggers = [
            "discord.ext.voice_recv",
            "discord.voice_state",
            "discord.voice_client",
            "discord.gateway",
        ]
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s"))
        for name in _voice_loggers:
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            if not lg.handlers:
                lg.addHandler(handler)

    bot = InterpreterBot(
        openai_api_key=api_key,
        model=args.model,
        src_lang=args.src,
        tgt_lang=args.tgt,
        pairs=args.pairs,
        meeting_mode=args.meeting_mode,
        enable_tts=args.tts,
        show_input=args.show_input,
        debug=args.debug,
        text_channel_id=args.text_channel_id,
        auto_join_voice_channel_id=args.voice_channel_id,
    )

    logger.info(
        f"[DiscordBot] Starting | src={args.src} tgt={args.tgt} "
        f"| mode={args.meeting_mode} | tts={'on' if args.tts else 'off'}"
        + (f" | auto-join={args.voice_channel_id}" if args.voice_channel_id else "")
    )

    try:
        bot.run(token, log_handler=None)  # log_handler=None: we use our own logger
    except KeyboardInterrupt:
        print("\n[DiscordBot] Interrupted.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
