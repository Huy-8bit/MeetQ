"""
src/meet/main.py
Meet-bot mode entrypoint: joins Google Meet via Playwright, captures meeting
audio through a virtual loopback device, translates via Realtime API, and
injects translated TTS back into the meeting through a virtual mic device.

Can be run directly:  python -m src.meet.main [flags]
Or via app.py:        python app.py --mode meet-bot [flags]

Virtual audio device setup (macOS — required):
  1. Install BlackHole 2ch (free):  https://existential.audio/blackhole/
     Or Loopback (paid):            https://rogueamoeba.com/loopback/
  2. In Chrome (Meet): set speaker output to BlackHole 2ch
     --meet-speaker-device = BlackHole 2ch INPUT side index
  3. For bot speech back into Meet:
     In Chrome (Meet): set mic input to a second virtual device
     --meet-mic-device = that virtual OUTPUT device index
  4. python app.py --list-audio-devices  to find device indexes

First-time Google sign-in:
  python app.py --mode meet-bot --meeting-url <url> --profile-dir ~/.brseai_profile --setup-profile
  (Opens browser without joining — log in to Google, then close browser)

Example run:
  python app.py --mode meet-bot \\
    --meeting-url https://meet.google.com/abc-defg-hij \\
    --profile-dir ~/.brseai_profile \\
    --meet-speaker-device 4 \\
    --meet-mic-device 5 \\
    --src ja --tgt vi --meeting-mode locked
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from src.common.lang import SUPPORTED_LANGS, parse_pairs
from src.common.logging_utils import get_logger
from src.meet.audio import MeetAudioListenerInput, MeetAudioMicOutput, SCKAudioInput, print_all_audio_devices

logger = get_logger("meet.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Google Meet interpreter bot — joins a meeting as a participant, "
            "listens to audio, and speaks translations back via virtual devices."
        )
    )

    # ---- Meeting ----
    p.add_argument(
        "--meeting-url",
        required=False,
        default=None,
        metavar="URL",
        help="Google Meet URL to join (e.g. https://meet.google.com/abc-defg-hij).",
    )
    p.add_argument(
        "--profile-dir",
        default=str(Path.home() / ".brseai_profile"),
        metavar="PATH",
        help="Persistent Chromium profile directory for Google sign-in. Default: ~/.brseai_profile",
    )
    p.add_argument(
        "--setup-profile",
        action="store_true",
        help=(
            "Open browser for manual Google sign-in without joining a meeting. "
            "Use once to authenticate, then run normally."
        ),
    )
    p.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run Chromium headless. Default: false (Meet often blocks headless).",
    )
    p.add_argument(
        "--display-name",
        default="Interpreter Bot",
        metavar="NAME",
        help="Bot's display name in the meeting. Default: 'Interpreter Bot'.",
    )
    p.add_argument(
        "--join-timeout-seconds",
        type=int,
        default=90,
        metavar="N",
        help="Seconds to wait for admission to meeting. Default: 90.",
    )
    p.add_argument(
        "--leave-after-minutes",
        type=int,
        default=None,
        metavar="N",
        help="Auto-leave after N minutes. Default: run until Ctrl+C.",
    )

    # ---- Audio devices ----
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
        help=(
            "Input device index to capture meeting audio from "
            "(the loopback/virtual device Chrome plays into). "
            "See --list-audio-devices. Not needed when using --sck."
        ),
    )
    p.add_argument(
        "--meet-mic-device",
        type=int,
        default=None,
        metavar="INDEX",
        help=(
            "Output device index to play translated TTS into "
            "(the virtual device configured as Chrome's microphone input). "
            "See --list-audio-devices. Omit to disable bot speech output."
        ),
    )
    p.add_argument(
        "--meet-sample-rate",
        type=int,
        default=None,
        metavar="HZ",
        choices=[16000, 24000, 44100, 48000],
        help=(
            "Sample rate for meeting audio capture. "
            "Default: 16000 with --sck, 48000 with --meet-speaker-device."
        ),
    )
    p.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="List all audio devices (input + output) with indexes and exit.",
    )

    # ---- Interpreter / language ----
    p.add_argument(
        "--model",
        default=None,
        help="Override realtime model ID.",
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
        "--show-input",
        action="store_true",
        help="Always print recognized input transcript.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Verbose event + Playwright logging.",
    )

    return p.parse_args(argv)


async def _run_setup_profile(profile_dir: str) -> None:
    """Open Chromium at accounts.google.com for first-time sign-in."""
    from playwright.async_api import async_playwright
    print(
        f"\n[MeetBot] Setup profile mode.\n"
        f"  Profile dir: {profile_dir}\n"
        f"  Sign in to your Google account in the browser that opens.\n"
        f"  Close the browser when done.\n",
        flush=True,
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        pages = browser.pages
        page = pages[0] if pages else await browser.new_page()
        await page.goto("https://accounts.google.com/")
        print("[MeetBot] Sign in, then close the browser window.", flush=True)
        # Wait until the browser context is closed by the user
        await browser.wait_for_event("close")
    print("[MeetBot] Profile saved. You can now run in normal mode.", flush=True)


async def _run_meet_bot(args: argparse.Namespace, api_key: str) -> None:
    from src.meet.bot import MeetBot, MeetBotError
    from src.realtime.client import DEFAULT_MODEL, RealtimeClient

    model = args.model or DEFAULT_MODEL

    # ---- Build audio input ----
    if args.sck:
        sample_rate = args.meet_sample_rate or 16000
        audio_input = SCKAudioInput(
            sample_rate=sample_rate,
            app_bundle_id=args.sck_app,
        )
        print(
            f"[MeetBot] Audio capture: ScreenCaptureKit (macOS built-in) "
            f"| rate={sample_rate}Hz"
            + (f" | app={args.sck_app}" if args.sck_app else " | all system audio"),
            flush=True,
        )
    elif args.meet_speaker_device is not None:
        sample_rate = args.meet_sample_rate or 48000
        audio_input = MeetAudioListenerInput(
            device=args.meet_speaker_device,
            sample_rate=sample_rate,
        )
    else:
        print(
            "Error: specify either --sck (recommended, no drivers needed) or "
            "--meet-speaker-device <INDEX>.\n"
            "  --sck captures system audio via macOS ScreenCaptureKit (macOS 13+).\n"
            "  --meet-speaker-device requires a virtual loopback device (BlackHole/Loopback).\n"
            "Run --list-audio-devices to find device indexes.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ---- Build audio output (optional) ----
    mic_output: Optional[MeetAudioMicOutput] = None
    if args.meet_mic_device is not None:
        mic_output = MeetAudioMicOutput(
            device=args.meet_mic_device,
            sample_rate=24000,  # Realtime API TTS is always 24kHz
        )

    # ---- Build interpreter client ----
    from src.common.lang import parse_pairs
    allowed_pairs = parse_pairs(args.pairs)

    client = RealtimeClient(
        api_key=api_key,
        model=model,
        enable_speaker=(mic_output is not None),
        # We override the SpeakerPlayer with MeetAudioMicOutput below
        debug=args.debug,
        src_lang=args.src,
        tgt_lang=args.tgt,
        allowed_pairs=allowed_pairs,
        show_input=args.show_input,
        meeting_mode=args.meeting_mode,
        audio_input=audio_input,
    )

    # Patch: replace the internal SpeakerPlayer with MeetAudioMicOutput
    # Both share the same push()/flush()/stop()/restart() interface
    if mic_output is not None:
        client._player = mic_output
        mic_output.start()

    # ---- Build and start Playwright bot ----
    bot = MeetBot(
        meeting_url=args.meeting_url,
        profile_dir=args.profile_dir,
        display_name=args.display_name,
        headless=args.headless,
        join_timeout=args.join_timeout_seconds,
        leave_after_minutes=args.leave_after_minutes,
        debug=args.debug,
    )

    audio_input_desc = "sck" if args.sck else f"device={args.meet_speaker_device}"
    print(
        f"\n[MeetBot] Starting | url={args.meeting_url}"
        f" | src={args.src} tgt={args.tgt} | mode={args.meeting_mode}"
        f" | audio-in={audio_input_desc}"
        f" | mic-out={args.meet_mic_device or 'disabled'}",
        flush=True,
    )

    # Join the meeting
    try:
        await bot.start()
    except Exception as exc:
        logger.error(f"[MeetBot] Failed to join: {exc}")
        print(f"[MeetBot] Error: {exc}", file=sys.stderr)
        await bot.stop()
        if mic_output:
            mic_output.stop()
        sys.exit(1)

    print(f"[MeetBot] joined | url={args.meeting_url} | listening...", flush=True)

    # Run interpreter in a task; run bot.wait_until_done concurrently
    interpreter_task = asyncio.create_task(_run_interpreter_async(client))
    wait_task = asyncio.create_task(bot.wait_until_done())

    try:
        done, pending = await asyncio.wait(
            [interpreter_task, wait_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        client._running = False
        await bot.stop()
        if mic_output:
            mic_output.stop()
        print("\n[MeetBot] Stopped.", flush=True)


async def _run_interpreter_async(client) -> None:
    """Run the RealtimeClient coroutine loop inside the meet-bot async context."""
    client._running = True
    try:
        await client._run_with_retry()
    except KeyboardInterrupt:
        pass
    finally:
        client._running = False
        if client._player:
            client._player.stop()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_audio_devices:
        print_all_audio_devices()
        return 0

    if args.setup_profile:
        asyncio.run(_run_setup_profile(args.profile_dir))
        return 0

    if not args.meeting_url:
        print(
            "Error: --meeting-url is required in meet-bot mode.\n"
            "Example: --meeting-url https://meet.google.com/abc-defg-hij",
            file=sys.stderr,
        )
        return 1

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        asyncio.run(_run_meet_bot(args, api_key))
    except KeyboardInterrupt:
        print("\n[MeetBot] Interrupted.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
