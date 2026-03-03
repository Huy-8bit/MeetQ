#!/usr/bin/env python3
"""
app.py — Main CLI entrypoint for the brseAI interpreter demo.

Usage:
    python app.py --mode realtime [--mic INDEX] [--list-mics]
    python app.py --mode fallback [--seconds 5] [--mic INDEX] [--list-mics]
    python app.py --list-mics

Environment:
    OPENAI_API_KEY   Required. Your OpenAI API key.

Examples:
    # List available microphones
    python app.py --list-mics

    # Start realtime interpreter with default mic
    python app.py --mode realtime

    # Start realtime interpreter with mic #2
    python app.py --mode realtime --mic 2

    # Run fallback mode (record 8 seconds, then translate)
    python app.py --mode fallback --seconds 8

    # Run fallback with specific mic
    python app.py --mode fallback --mic 1 --seconds 10
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
            "brseAI — Real-time bilingual interpreter (Vietnamese <-> English)\n"
            "Streams mic audio to OpenAI Realtime API and prints translation.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    p.add_argument(
        "--mode",
        choices=["realtime", "fallback"],
        default="realtime",
        help="Operation mode: 'realtime' (streaming WebSocket) or 'fallback' (clip-based). Default: realtime",
    )
    p.add_argument(
        "--input-lang",
        default="auto",
        metavar="LANG",
        help="Input language hint (default: auto). Informational only — model auto-detects.",
    )
    p.add_argument(
        "--output-lang",
        default="auto",
        metavar="LANG",
        help="Output language hint (default: auto). Informational only — model auto-detects.",
    )
    p.add_argument(
        "--mic",
        type=int,
        default=None,
        metavar="INDEX",
        help="Microphone device index (use --list-mics to discover). Default: system default.",
    )
    p.add_argument(
        "--list-mics",
        action="store_true",
        help="Print available input devices and exit.",
    )
    p.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        metavar="N",
        help="[fallback only] Duration in seconds to record. Default: 5.",
    )
    p.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help="Audio sample rate in Hz. Default: 16000.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="[realtime only] Override realtime model ID.",
    )
    p.add_argument(
        "--transcribe-model",
        default="whisper-1",
        help="[fallback only] Transcription model. Default: whisper-1.",
    )
    p.add_argument(
        "--chat-model",
        default="gpt-4o-mini",
        help="[fallback only] Translation chat model. Default: gpt-4o-mini.",
    )
    p.add_argument(
        "--speaker",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="[realtime only] Enable audio playback (default: on). Use --no-speaker to disable.",
    )
    p.add_argument(
        "--speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="[realtime only] Output device index (use --list-speakers to discover).",
    )
    p.add_argument(
        "--list-speakers",
        action="store_true",
        help="Print available output devices and exit.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="[realtime only] Enable verbose event logging and show input transcripts.",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Device listing can work without an API key
    if args.list_mics:
        from src.common.audio import print_input_devices
        print_input_devices()
        return 0

    if args.list_speakers:
        from src.common.audio import print_output_devices
        print_output_devices()
        return 0

    # Validate API key early
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "Error: OPENAI_API_KEY environment variable is not set.\n"
            "  export OPENAI_API_KEY='sk-...'\n"
            "or copy .env.example -> .env and set the key there.",
            file=sys.stderr,
        )
        return 1

    if args.mode == "realtime":
        from src.realtime.client import DEFAULT_MODEL, RealtimeClient
        from src.common.logging_utils import get_logger

        logger = get_logger("app")
        model = args.model or DEFAULT_MODEL
        logger.info(
            f"Mode: realtime | model={model} | mic={args.mic} | rate={args.sample_rate} "
            f"| speaker={'on' if args.speaker else 'off'} | debug={args.debug}"
        )

        client = RealtimeClient(
            api_key=api_key,
            model=model,
            mic_device=args.mic,
            sample_rate=args.sample_rate,
            enable_speaker=args.speaker,
            speaker_device=args.speaker_device,
            debug=args.debug,
        )
        try:
            client.run()
        except KeyboardInterrupt:
            pass
        return 0

    elif args.mode == "fallback":
        from src.fallback.pipeline import run_fallback
        from src.common.logging_utils import get_logger, print_translation

        logger = get_logger("app")
        logger.info(
            f"Mode: fallback | seconds={args.seconds} | mic={args.mic} | rate={args.sample_rate}"
        )

        try:
            translation = run_fallback(
                seconds=args.seconds,
                mic_device=args.mic,
                sample_rate=args.sample_rate,
                api_key=api_key,
                transcribe_model=args.transcribe_model,
                chat_model=args.chat_model,
            )
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if translation:
            print("\n--- Translation ---")
            print_translation(translation, end="\n")
        else:
            print("\n[No speech detected or empty transcript]")

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
