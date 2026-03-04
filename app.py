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
        choices=["realtime", "fallback", "meet-bot"],
        default="realtime",
        help=(
            "Operation mode: 'realtime' (streaming WebSocket), "
            "'fallback' (clip-based), or 'meet-bot' (Google Meet interpreter bot). "
            "Default: realtime"
        ),
    )

    # ---- Meet-bot flags (only used when --mode meet-bot) ----
    p.add_argument(
        "--meeting-url",
        default=None,
        metavar="URL",
        help="[meet-bot] Google Meet URL to join.",
    )
    p.add_argument(
        "--profile-dir",
        default=None,
        metavar="PATH",
        help="[meet-bot] Persistent Chromium profile directory (for Google sign-in).",
    )
    p.add_argument(
        "--setup-profile",
        action="store_true",
        help="[meet-bot] Open browser for first-time Google sign-in, then exit.",
    )
    p.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="[meet-bot] Run Chromium headless. Default: false.",
    )
    p.add_argument(
        "--display-name",
        default="Interpreter Bot",
        metavar="NAME",
        help="[meet-bot] Bot display name in meeting. Default: 'Interpreter Bot'.",
    )
    p.add_argument(
        "--join-timeout-seconds",
        type=int,
        default=90,
        metavar="N",
        help="[meet-bot] Seconds to wait for meeting admission. Default: 90.",
    )
    p.add_argument(
        "--leave-after-minutes",
        type=int,
        default=None,
        metavar="N",
        help="[meet-bot] Auto-leave after N minutes. Default: run until Ctrl+C.",
    )
    p.add_argument(
        "--manual-join",
        action="store_true",
        help=(
            "[meet-bot] Do not auto-click the Join button. Open the meeting URL "
            "in the browser and wait for the user to join by hand. "
            "Interpreter pipeline starts once in-call state is detected. "
            "See --manual-join-timeout."
        ),
    )
    p.add_argument(
        "--manual-join-timeout",
        type=int,
        default=300,
        metavar="N",
        help=(
            "[meet-bot] With --manual-join: seconds to wait for the user to "
            "complete the join before giving up. Default: 300."
        ),
    )
    p.add_argument(
        "--sck",
        action="store_true",
        help=(
            "[meet-bot] Use macOS ScreenCaptureKit to capture system audio directly — "
            "no virtual audio device (BlackHole/Loopback) required. "
            "Requires macOS 13+ and Screen Recording permission. "
            "When set, --meet-speaker-device is ignored."
        ),
    )
    p.add_argument(
        "--sck-app",
        default=None,
        metavar="BUNDLE_ID",
        help=(
            "[meet-bot] With --sck: capture only this app's audio (e.g. com.google.Chrome). "
            "Default: capture all system audio."
        ),
    )
    p.add_argument(
        "--meet-speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="[meet-bot] Input device index to capture meeting audio from (loopback device).",
    )
    p.add_argument(
        "--meet-mic-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="[meet-bot] Output device index to send translated TTS into (virtual mic device).",
    )
    p.add_argument(
        "--meet-sample-rate",
        type=int,
        default=48000,
        choices=[16000, 24000, 44100, 48000],
        metavar="HZ",
        help="[meet-bot] Meeting audio capture sample rate. Default: 48000.",
    )
    p.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="[meet-bot] List all audio devices (input + output) and exit.",
    )
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
        help='[realtime] Allowed pairs, e.g. "vi<->en,ja<->en". Default: all.',
    )
    p.add_argument(
        "--show-input",
        action="store_true",
        help="[realtime] Always print recognized input transcript.",
    )
    p.add_argument(
        "--input",
        choices=["mic", "device"],
        default="mic",
        dest="input_source",
        help=(
            "Audio input source: 'mic' (default) = local microphone; "
            "'device' = any sounddevice input (e.g. BlackHole/Loopback for meeting capture). "
            "Requires --input-device <index>."
        ),
    )
    p.add_argument(
        "--input-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Device index for --input=device (use --list-input-devices to discover).",
    )
    p.add_argument(
        "--input-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help="[realtime] Sample rate for audio input in Hz. Default: 16000.",
    )
    p.add_argument(
        "--list-input-devices",
        action="store_true",
        help="Print all input devices (mic and virtual/loopback) and exit.",
    )
    p.add_argument(
        "--mic",
        type=int,
        default=None,
        metavar="INDEX",
        help="[Legacy] Microphone device index. Equivalent to --input=mic --input-device INDEX.",
    )
    p.add_argument(
        "--list-mics",
        action="store_true",
        help="[Legacy] Print available input devices and exit. Equivalent to --list-input-devices.",
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
        default=None,
        metavar="HZ",
        help="[Legacy] Audio sample rate in Hz. For realtime use --input-rate instead.",
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
        default=None,
        help=(
            "[realtime only] Enable audio playback. "
            "Default: ON for --input=mic, OFF for --input=device (echo prevention). "
            "Override with --speaker or --no-speaker."
        ),
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
    p.add_argument(
        "--meeting-mode",
        default="locked",
        choices=["locked", "auto"],
        help=(
            "locked (default): fix language routing after first detection, never change mid-session. "
            "auto: re-detect and re-route dynamically throughout the session."
        ),
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Device listing can work without an API key
    if args.list_input_devices or args.list_mics:
        from src.common.audio import print_input_devices
        print_input_devices()
        return 0

    if args.list_speakers:
        from src.common.audio import print_output_devices
        print_output_devices()
        return 0

    if args.list_audio_devices:
        from src.meet.audio import print_all_audio_devices
        print_all_audio_devices()
        return 0

    # Setup profile can work without an API key
    if args.setup_profile:
        import asyncio
        from src.meet.main import _run_setup_profile
        profile_dir = args.profile_dir or str(Path.home() / ".brseai_profile")
        asyncio.run(_run_setup_profile(profile_dir))
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
        from src.realtime.main import _resolve_audio_input, _resolve_speaker
        from src.common.logging_utils import get_logger
        from src.common.lang import parse_pairs

        logger = get_logger("app")
        model = args.model or DEFAULT_MODEL

        audio_input, sample_rate = _resolve_audio_input(args)
        enable_speaker = _resolve_speaker(args)

        if args.input_source == "device" and enable_speaker:
            print(
                "[WARNING] Speaker ON with device input — risk of echo/feedback loop. "
                "Use --no-speaker to suppress.",
                flush=True,
            )

        logger.info(
            f"Mode: realtime | model={model} | input={type(audio_input).__name__} "
            f"| rate={sample_rate} | src={args.src} tgt={args.tgt} "
            f"| speaker={'on' if enable_speaker else 'off'} | debug={args.debug}"
        )

        client = RealtimeClient(
            api_key=api_key,
            model=model,
            enable_speaker=enable_speaker,
            speaker_device=args.speaker_device,
            debug=args.debug,
            src_lang=args.src,
            tgt_lang=args.tgt,
            allowed_pairs=parse_pairs(args.pairs),
            show_input=args.show_input,
            meeting_mode=args.meeting_mode,
            audio_input=audio_input,
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
        fallback_rate = args.sample_rate or args.input_rate or 16000
        fallback_mic = args.mic or args.input_device
        logger.info(
            f"Mode: fallback | seconds={args.seconds} | mic={fallback_mic} | rate={fallback_rate}"
        )

        try:
            translation = run_fallback(
                seconds=args.seconds,
                mic_device=fallback_mic,
                sample_rate=fallback_rate,
                api_key=api_key,
                transcribe_model=args.transcribe_model,
                chat_model=args.chat_model,
                src_lang=args.src,
                tgt_lang=args.tgt,
                meeting_mode=args.meeting_mode,
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

    elif args.mode == "meet-bot":
        import asyncio
        from src.meet.main import _run_meet_bot, parse_args as _meet_parse_args
        from src.common.logging_utils import get_logger

        logger = get_logger("app")

        if not args.meeting_url:
            print(
                "Error: --meeting-url is required for meet-bot mode.\n"
                "Example: python app.py --mode meet-bot "
                "--meeting-url https://meet.google.com/abc-defg-hij "
                "--profile-dir ~/.brseai_profile",
                file=sys.stderr,
            )
            return 1

        # Re-parse using meet.main's parser to fill any defaults it knows about,
        # then pass the current args object directly since it has all the same attrs.
        profile_dir = args.profile_dir or str(Path.home() / ".brseai_profile")
        args.profile_dir = profile_dir

        logger.info(
            f"Mode: meet-bot | url={args.meeting_url} | profile={profile_dir} "
            f"| src={args.src} tgt={args.tgt} | meeting_mode={args.meeting_mode}"
        )

        try:
            asyncio.run(_run_meet_bot(args, api_key))
        except KeyboardInterrupt:
            print("\n[MeetBot] Interrupted.", flush=True)

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
