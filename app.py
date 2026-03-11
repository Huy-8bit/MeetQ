#!/usr/bin/env python3
"""
app.py — brseAI Realtime Interpreter

Usage:
    python app.py --mode realtime [options]
    python app.py --mode fallback [options]
    python app.py --mode discord [options]

Environment:
    OPENAI_API_KEY       Required. Your OpenAI API key.
    DISCORD_BOT_TOKEN    Required for Discord mode.

Examples:
    # Realtime mode with microphone input
    python app.py --mode realtime --input mic

    # Realtime mode with device input
    python app.py --mode realtime --input device --input-device 1

    # Fallback mode for testing
    python app.py --mode fallback --input-device 1

    # Discord bot mode
    python app.py --mode discord --token YOUR_DISCORD_TOKEN

    # List audio devices
    python app.py --list-input-devices
    python app.py --list-speakers

Note:
    This is a simple CLI wrapper. For advanced usage, call the modules directly:
    - python -m src.realtime.main [options]
    - python -m src.fallback.pipeline [options]
    - python -m src.discord.main [options]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure project root is importable regardless of cwd
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env from project root (required for OPENAI_API_KEY)
from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="app.py",
        description=(
            "brseAI — Realtime interpreter (Vietnamese / English / Japanese)\n"
            "Supports Realtime API, Fallback, and Discord bot modes.\n\n"
            "Quick start:\n"
            "  Realtime:  python app.py --mode realtime --input mic\n"
            "  Fallback:  python app.py --mode fallback --input-device 1\n"
            "  Discord:   python app.py --mode discord --token YOUR_TOKEN\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    p.add_argument(
        "--mode",
        choices=["realtime", "fallback", "discord"],
        default="realtime",
        help="Operation mode: 'realtime' (default), 'fallback', or 'discord'.",
    )

    # ---- Input flags ----
    p.add_argument(
        "--input",
        choices=["mic", "device"],
        default="mic",
        dest="input_source",
        help="Input source: 'mic' (default) or 'device'.",
    )
    p.add_argument(
        "--input-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Input device index (required with --input device).",
    )
    p.add_argument(
        "--input-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help="Input sample rate (default: 16000).",
    )
    p.add_argument(
        "--list-input-devices",
        action="store_true",
        help="List all input devices and exit.",
    )
    p.add_argument(
        "--mic",
        type=int,
        default=None,
        metavar="INDEX",
        help="[Legacy] Microphone device index.",
    )
    p.add_argument(
        "--list-mics",
        action="store_true",
        help="[Legacy] List all input devices and exit.",
    )

    # ---- Output flags ----
    p.add_argument(
        "--speaker",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable speaker output.",
    )
    p.add_argument(
        "--speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Output device index.",
    )
    p.add_argument(
        "--list-speakers",
        action="store_true",
        help="List all output devices and exit.",
    )

    # ---- Language flags ----
    p.add_argument(
        "--src",
        default="auto",
        choices=["auto", "vi", "en", "ja"],
        help="Source language: auto (default), vi, en, ja.",
    )
    p.add_argument(
        "--tgt",
        default="auto",
        choices=["auto", "vi", "en", "ja"],
        help="Target language: auto (default), vi, en, ja.",
    )
    p.add_argument(
        "--pairs",
        default="",
        metavar="PAIRS",
        help='Allowed pairs, e.g. "vi<->en,ja<->en". Default: all.',
    )
    p.add_argument(
        "--meeting-mode",
        default="locked",
        choices=["locked", "auto"],
        help=(
            "locked (default): fix language routing after first detection. "
            "auto: re-detect dynamically throughout the session."
        ),
    )
    p.add_argument(
        "--show-input",
        action="store_true",
        help="Always print recognized input transcript.",
    )

    # ---- Fallback-specific flags ----
    p.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        metavar="N",
        help="Fallback mode: audio clip duration in seconds (default: 5.0).",
    )
    p.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        metavar="HZ",
        help="[Legacy] Fallback sample rate.",
    )

    # ---- Model flags ----
    p.add_argument(
        "--model",
        default=None,
        help="Override realtime model ID.",
    )
    p.add_argument(
        "--transcribe-model",
        default="whisper-1",
        help="Fallback transcription model.",
    )
    p.add_argument(
        "--chat-model",
        default="gpt-4o-mini",
        help="Fallback chat model.",
    )

    # ---- Debug ----
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose event logging.",
    )
# ---- Discord-specific flags ----
    p.add_argument(
        "--token",
        type=str,
        default=None,
        metavar="TOKEN",
        help="Discord bot token (required for Discord mode).",
    )
    p.add_argument(
        "--voice-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Discord voice channel ID for auto-join.",
    )
    p.add_argument(
        "--text-channel-id",
        type=int,
        default=None,
        metavar="ID",
        help="Discord text channel ID for translation output.",
    )

    
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # --- Early-exit utilities (no API key needed) ---
    if args.list_input_devices or args.list_mics:
        from src.common.audio import print_input_devices
        print_input_devices()
        return 0

    if args.list_speakers:
        from src.common.audio import print_output_devices
        print_output_devices()
        return 0

    # --- Validate API key ---
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "Error: OPENAI_API_KEY environment variable is not set.\n"
            "  export OPENAI_API_KEY='sk-...'\n"
            "or copy .env.example -> .env and set the key there.",
            file=sys.stderr,
        )
        return 1

    # --- Realtime mode ---
    if args.mode == "realtime":
        from src.realtime.main import main as realtime_main
        from src.common.logging_utils import get_logger
        logger = get_logger("app")
        logger.info(
            f"Mode: realtime | input={args.input_source} | "
            f"src={args.src} tgt={args.tgt} | meeting_mode={args.meeting_mode}"
        )
        
        # Build argv for realtime.main
        argv = []
        argv += ["--input", args.input_source]
        if args.input_device is not None:
            argv += ["--input-device", str(args.input_device)]
        if args.input_rate:
            argv += ["--input-rate", str(args.input_rate)]
        if args.speaker is not None:
            if args.speaker:
                argv += ["--speaker"]
            else:
                argv += ["--no-speaker"]
        if args.speaker_device is not None:
            argv += ["--speaker-device", str(args.speaker_device)]
        if args.model:
            argv += ["--model", args.model]
        argv += ["--src", args.src, "--tgt", args.tgt]
        if args.pairs:
            argv += ["--pairs", args.pairs]
        argv += ["--meeting-mode", args.meeting_mode]
        if args.show_input:
            argv += ["--show-input"]
        if args.debug:
            argv += ["--debug"]
        
        return realtime_main(argv)

    # --- Fallback mode ---
    if args.mode == "fallback":
        from src.fallback.pipeline import main as fallback_main
        from src.common.logging_utils import get_logger
        logger = get_logger("app")
        logger.info(
            f"Mode: fallback | seconds={args.seconds} | "
            f"src={args.src} tgt={args.tgt} | meeting_mode={args.meeting_mode}"
        )
        
        # Build argv for fallback.pipeline
    # --- Discord mode ---
    if args.mode == "discord":
        from src.discord.main import main as discord_main
        from src.common.logging_utils import get_logger
        logger = get_logger("app")
        logger.info(
            f"Mode: discord | src={args.src} tgt={args.tgt} | meeting_mode={args.meeting_mode}"
        )
        
        # Discord mode needs to replace sys.argv for its own parser
        # Build new argv
        argv = ["discord"]  # program name placeholder
        if args.token:
            argv += ["--token", args.token]
        if args.voice_channel_id:
            argv += ["--voice-channel-id", str(args.voice_channel_id)]
        if args.text_channel_id:
            argv += ["--text-channel-id", str(args.text_channel_id)]
        argv += ["--src", args.src, "--tgt", args.tgt]
        if args.pairs:
            argv += ["--pairs", args.pairs]
        argv += ["--meeting-mode", args.meeting_mode]
        if args.debug:
            argv += ["--debug"]
        
        # Replace sys.argv temporarily
        old_argv = sys.argv
        sys.argv = argv
        try:
            discord_main()
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
        finally:
            sys.argv = old_argv

        argv = []
        if args.input_device is not None:
            argv += ["--mic", str(args.input_device)]
        argv += ["--seconds", str(args.seconds)]
        if args.sample_rate:
            argv += ["--sample-rate", str(args.sample_rate)]
        elif args.input_rate:
            argv += ["--sample-rate", str(args.input_rate)]
        if args.transcribe_model:
            argv += ["--transcribe-model", args.transcribe_model]
        if args.chat_model:
            argv += ["--chat-model", args.chat_model]
        argv += ["--src", args.src, "--tgt", args.tgt]
        if args.pairs:
            argv += ["--pairs", args.pairs]
        argv += ["--meeting-mode", args.meeting_mode]
        if args.show_input:
            argv += ["--show-input"]
        if args.debug:
            argv += ["--debug"]
        
        return fallback_main(argv)

    print(f"Error: Unknown mode '{args.mode}'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
