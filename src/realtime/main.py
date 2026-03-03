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

from src.common.audio import print_input_devices, print_output_devices
from src.common.lang import SUPPORTED_LANGS, parse_pairs
from src.common.logging_utils import get_logger
from src.realtime.client import DEFAULT_MODEL, RealtimeClient

logger = get_logger("realtime.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Realtime interpreter: mic -> OpenAI Realtime API -> text + voice"
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help="Realtime model ID")
    p.add_argument("--mic", type=int, default=None, metavar="INDEX",
                   help="Input device index (see --list-mics)")
    p.add_argument("--list-mics", action="store_true",
                   help="List input devices and exit")
    p.add_argument("--sample-rate", type=int, default=16000,
                   help="Mic sample rate Hz (default 16000)")
    p.add_argument("--speaker", action=argparse.BooleanOptionalAction, default=True,
                   help="Enable audio playback (default: on). Use --no-speaker to disable.")
    p.add_argument("--speaker-device", type=int, default=None, metavar="INDEX",
                   help="Output device index for speaker (see --list-speakers)")
    p.add_argument("--list-speakers", action="store_true",
                   help="List output devices and exit")
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_mics:
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

    allowed_pairs = parse_pairs(args.pairs)

    logger.info(
        f"Starting realtime interpreter | model={args.model} | mic={args.mic} "
        f"| src={args.src} tgt={args.tgt} | pairs={args.pairs or 'all'} "
        f"| meeting_mode={args.meeting_mode} "
        f"| speaker={'on' if args.speaker else 'off'} | debug={args.debug}"
    )

    client = RealtimeClient(
        api_key=api_key,
        model=args.model,
        mic_device=args.mic,
        sample_rate=args.sample_rate,
        enable_speaker=args.speaker,
        speaker_device=args.speaker_device,
        debug=args.debug,
        src_lang=args.src,
        tgt_lang=args.tgt,
        allowed_pairs=allowed_pairs,
        show_input=args.show_input,
        meeting_mode=args.meeting_mode,
    )
    client.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
