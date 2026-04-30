"""
src/realtime/main.py
Entrypoint for realtime interpreter mode.
Can be run directly:  python -m src.realtime.main [flags]
Or via app.py:        python app.py --mode realtime [flags]
"""
from __future__ import annotations

import argparse
import os
import sys

from src.common.audio import (
    AudioInput,
    DeviceLoopbackInput,
    MicInput,
    print_input_devices,
    print_output_devices,
)
from src.common.lang import SUPPORTED_LANGS, parse_pairs
from src.common.logging_utils import get_logger
from src.realtime.client import DEFAULT_MODEL, RealtimeClient

logger = get_logger("realtime.main")

VALID_INPUT_RATES = [8000, 16000, 24000, 44100, 48000]
DEFAULT_MODEL_ARG = os.environ.get("OPENAI_REALTIME_MODEL", DEFAULT_MODEL)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Realtime interpreter: audio input -> OpenAI Realtime API -> text + voice"
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL_ARG,
        help=f"Realtime model ID (default: {DEFAULT_MODEL_ARG})",
    )

    # ---- Audio input source ----
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
        help="Device index for --input=device (see --list-input-devices).",
    )
    p.add_argument(
        "--input-rate",
        type=int,
        default=16000,
        metavar="HZ",
        help=f"Sample rate for audio input in Hz (default 16000). Common: {VALID_INPUT_RATES}.",
    )
    p.add_argument(
        "--list-input-devices",
        action="store_true",
        help="List all input devices (mic and virtual/loopback) and exit.",
    )

    # ---- Legacy mic flags (kept for backwards compatibility) ----
    p.add_argument("--mic", type=int, default=None, metavar="INDEX",
                   help="[Legacy] Mic device index. Equivalent to --input=mic --input-device INDEX.")
    p.add_argument("--list-mics", action="store_true",
                   help="[Legacy] List input devices and exit. Equivalent to --list-input-devices.")
    p.add_argument("--sample-rate", type=int, default=None,
                   help="[Legacy] Mic sample rate Hz. Equivalent to --input-rate.")

    # ---- Speaker / output ----
    p.add_argument("--speaker", action=argparse.BooleanOptionalAction, default=None,
                   help=(
                       "Enable audio playback. Default: ON for --input=mic, OFF for --input=device "
                       "(to prevent echo). Override with --speaker or --no-speaker."
                   ))
    p.add_argument("--speaker-device", type=int, default=None, metavar="INDEX",
                   help="Output device index for speaker (see --list-speakers)")
    p.add_argument("--list-speakers", action="store_true",
                   help="List output devices and exit")

    # ---- Debug / language ----
    p.add_argument("--debug", action="store_true",
                   help="Enable verbose event logging and show input transcripts")
    p.add_argument("--src", default="auto", choices=sorted(SUPPORTED_LANGS),
                   help="Source language (default: auto). auto=detect from speech.")
    p.add_argument("--tgt", default="auto", choices=sorted(SUPPORTED_LANGS),
                   help="Target language (default: auto). auto=infer from source.")
    p.add_argument("--pairs", default="", metavar="PAIRS",
                   help='Allowed translation pairs, e.g. "vi<->en,ja<->en". Default: all allowed.')
    p.add_argument("--show-input", action="store_true",
                   help="Always print recognized input transcript (implied by --debug).")
    p.add_argument("--meeting-mode", default="locked", choices=["locked", "auto"],
                   help=(
                       "locked (default): fix language routing after first detection, never change mid-session. "
                       "auto: re-detect and re-route dynamically throughout the session."
                   ))
    return p.parse_args(argv)


def _resolve_audio_input(args: argparse.Namespace) -> tuple[AudioInput, int]:
    """
    Build the appropriate AudioInput from parsed args.
    Returns (audio_input, effective_sample_rate).
    """
    # Legacy --mic / --sample-rate -> map to new flags
    input_source = args.input_source
    input_device = args.input_device
    sample_rate = args.input_rate

    if args.mic is not None:
        # --mic overrides --input-device for backwards compat
        input_device = args.mic
        if input_source == "mic":
            input_source = "mic"  # stays mic, just with explicit device

    if args.sample_rate is not None:
        sample_rate = args.sample_rate

    if input_source == "device":
        if input_device is None:
            print(
                "Error: --input=device requires --input-device <index>.\n"
                "Run --list-input-devices to find the right index.",
                file=sys.stderr,
            )
            sys.exit(1)
        return DeviceLoopbackInput(device=input_device, sample_rate=sample_rate), sample_rate
    else:
        return MicInput(device=input_device, sample_rate=sample_rate), sample_rate


def _resolve_speaker(args: argparse.Namespace) -> bool:
    """
    Resolve effective speaker-enable value.
    Default: ON for mic input, OFF for device input (echo prevention).
    --speaker / --no-speaker always override the default.
    """
    if args.speaker is not None:
        return args.speaker
    # Safety default: disable speaker when capturing from a device to prevent echo/feedback
    return args.input_source != "device"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_input_devices or args.list_mics:
        print_input_devices()
        return 0

    if args.list_speakers:
        print_output_devices()
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is not set.")
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    audio_input, sample_rate = _resolve_audio_input(args)
    enable_speaker = _resolve_speaker(args)

    if args.input_source == "device" and enable_speaker:
        logger.warning(
            "WARNING: speaker is ON while --input=device is active. "
            "This may cause audio echo or feedback. Use --no-speaker to suppress."
        )
        print(
            "[WARNING] Speaker ON with device input — risk of echo/feedback loop. "
            "Use --no-speaker to suppress.",
            flush=True,
        )

    allowed_pairs = parse_pairs(args.pairs)

    logger.info(
        f"Starting realtime interpreter | model={args.model} | input={type(audio_input).__name__} "
        f"| rate={sample_rate} | src={args.src} tgt={args.tgt} | pairs={args.pairs or 'all'} "
        f"| meeting_mode={args.meeting_mode} "
        f"| speaker={'on' if enable_speaker else 'off'} | debug={args.debug}"
    )

    client = RealtimeClient(
        api_key=api_key,
        model=args.model,
        enable_speaker=enable_speaker,
        speaker_device=args.speaker_device,
        debug=args.debug,
        src_lang=args.src,
        tgt_lang=args.tgt,
        allowed_pairs=allowed_pairs,
        show_input=args.show_input,
        meeting_mode=args.meeting_mode,
        audio_input=audio_input,
    )
    client.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
