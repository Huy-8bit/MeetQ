#!/usr/bin/env python3
"""
app.py — brseAI Google Meet interpreter bot.

Usage:
    python app.py --meeting-url "https://meet.google.com/xxx-xxxx-xxx"

Environment:
    OPENAI_API_KEY   Required. Your OpenAI API key.

Examples:
    # List audio devices
    python app.py --list-audio-devices

    # First-time Google sign-in (run once before joining meetings)
    python app.py --setup-profile

    # Join a meeting (manual-join: browser opens, you click Join)
    python app.py --meeting-url "https://meet.google.com/abc-defg-hij"

    # Join with auto-click (may need selector updates if Meet UI changes)
    python app.py --meeting-url "https://meet.google.com/abc-defg-hij" --no-manual-join

    # Join with TTS speak-back via virtual mic output device
    python app.py --meeting-url "https://meet.google.com/abc-defg-hij" --meet-mic-device 3

Migration from --mode meet-bot:
    Old: python app.py --mode meet-bot --meeting-url URL ...
    New: python app.py --meeting-url URL ...
    (--mode meet-bot still works for backward compatibility.)

Note:
    --mode realtime and --mode fallback are no longer supported in app.py.
    Use python -m src.realtime.main or python -m src.fallback.pipeline directly.
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
            "brseAI — Google Meet interpreter bot (Vietnamese / English / Japanese)\n"
            "Joins a meeting and translates speech in real time.\n\n"
            "Quick start:\n"
            "  python app.py --meeting-url \"https://meet.google.com/xxx-xxxx-xxx\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    p.add_argument(
        "--mode",
        choices=["meet-bot", "realtime", "fallback"],
        default="meet-bot",
        help=(
            "Operation mode. Default and only supported mode: 'meet-bot'. "
            "'realtime' and 'fallback' are legacy; use src.realtime.main / "
            "src.fallback.pipeline directly."
        ),
    )

    # ---- Meet-bot flags ----
    p.add_argument(
        "--meeting-url",
        default=None,
        metavar="URL",
        help="Google Meet URL to join. Required for normal operation.",
    )
    p.add_argument(
        "--profile-dir",
        default=None,
        metavar="PATH",
        help="Persistent Chromium profile directory (for Google sign-in). "
             "Default: ~/.brseai_profile",
    )
    p.add_argument(
        "--setup-profile",
        action="store_true",
        help="Open browser for first-time Google sign-in, then exit.",
    )
    p.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run Chromium headless. Default: false.",
    )
    p.add_argument(
        "--display-name",
        default="Interpreter Bot",
        metavar="NAME",
        help="Bot display name in meeting. Default: 'Interpreter Bot'.",
    )
    p.add_argument(
        "--join-timeout-seconds",
        type=int,
        default=90,
        metavar="N",
        help="Seconds to wait for meeting admission. Default: 90.",
    )
    p.add_argument(
        "--leave-after-minutes",
        type=int,
        default=None,
        metavar="N",
        help="Auto-leave after N minutes. Default: run until Ctrl+C.",
    )
    p.add_argument(
        "--manual-join",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Open the meeting URL in the browser and wait for the user to click "
            "Join by hand. Interpreter pipeline starts once in-call state is detected. "
            "Default: ON (more reliable than auto-click). "
            "Use --no-manual-join to enable auto-click."
        ),
    )
    p.add_argument(
        "--manual-join-timeout",
        type=int,
        default=300,
        metavar="N",
        help=(
            "With --manual-join: seconds to wait for the user to "
            "complete the join before giving up. Default: 300."
        ),
    )
    p.add_argument(
        "--sck",
        action="store_true",
        help=(
            "Use macOS ScreenCaptureKit to capture system audio directly — "
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
            "With --sck: capture only this app's audio (e.g. com.google.Chrome). "
            "Default: capture all system audio."
        ),
    )
    p.add_argument(
        "--meet-speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Input device index to capture meeting audio from (loopback device).",
    )
    p.add_argument(
        "--meet-mic-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Output device index to send translated TTS into (virtual mic device). "
             "Required to enable audio speak-back; omit for text-only translation.",
    )
    p.add_argument(
        "--meet-sample-rate",
        type=int,
        default=48000,
        choices=[16000, 24000, 44100, 48000],
        metavar="HZ",
        help="Meeting audio capture sample rate. Default: 48000.",
    )
    p.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="List all audio devices (input + output) and exit.",
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
        help='Allowed pairs, e.g. "vi<->en,ja<->en". Default: all.',
    )
    p.add_argument(
        "--show-input",
        action="store_true",
        help="Always print recognized input transcript.",
    )
    # ---- Legacy / realtime flags (kept for parser parity; not executed) ----
    p.add_argument(
        "--input",
        choices=["mic", "device"],
        default="mic",
        dest="input_source",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--input-device",
        type=int,
        default=None,
        metavar="INDEX",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--input-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--list-input-devices",
        action="store_true",
        help="Print all input devices and exit.",
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
        help="[Legacy] Print available input devices and exit.",
    )
    p.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        metavar="N",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        metavar="HZ",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override realtime model ID.",
    )
    p.add_argument(
        "--transcribe-model",
        default="whisper-1",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--chat-model",
        default="gpt-4o-mini",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--speaker",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--list-speakers",
        action="store_true",
        help="Print available output devices and exit.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose event logging.",
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

    if args.list_audio_devices:
        from src.meet.audio import print_all_audio_devices
        print_all_audio_devices()
        return 0

    if args.setup_profile:
        import asyncio
        from src.meet.main import _run_setup_profile
        profile_dir = args.profile_dir or str(Path.home() / ".brseai_profile")
        asyncio.run(_run_setup_profile(profile_dir))
        return 0

    # --- Reject unsupported legacy modes ---
    if args.mode in ("realtime", "fallback"):
        print(
            f"Error: --mode {args.mode!r} is not supported in app.py.\n"
            f"  For realtime: python -m src.realtime.main ...\n"
            f"  For fallback: python -m src.fallback.pipeline ...",
            file=sys.stderr,
        )
        return 1

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

    # --- meet-bot is the only remaining mode ---
    if not args.meeting_url:
        print(
            "Error: --meeting-url is required.\n"
            "  Example: python app.py --meeting-url https://meet.google.com/abc-defg-hij",
            file=sys.stderr,
        )
        return 1

    import asyncio
    from src.meet.main import _run_meet_bot
    from src.common.logging_utils import get_logger

    logger = get_logger("app")

    profile_dir = args.profile_dir or str(Path.home() / ".brseai_profile")
    args.profile_dir = profile_dir

    join_mode = f"manual(timeout={args.manual_join_timeout}s)" if args.manual_join else "auto"
    logger.info(
        f"Mode: meet-bot | url={args.meeting_url} | profile={profile_dir} "
        f"| src={args.src} tgt={args.tgt} | meeting_mode={args.meeting_mode} "
        f"| join={join_mode}"
    )

    try:
        asyncio.run(_run_meet_bot(args, api_key))
    except KeyboardInterrupt:
        print("\n[MeetBot] Interrupted.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
