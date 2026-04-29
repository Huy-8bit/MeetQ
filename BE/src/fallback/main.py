"""
src/fallback/main.py
Entrypoint for fallback (non-realtime) interpreter mode.
Can be run directly:  python -m src.fallback.main [flags]
Or via app.py:        python app.py --mode fallback [flags]
"""
from __future__ import annotations

import argparse
import os
import sys

from src.common.audio import print_input_devices
from src.common.lang import SUPPORTED_LANGS
from src.common.logging_utils import get_logger, print_translation
from src.fallback.pipeline import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_TRANSCRIBE_MODEL,
    run_fallback,
)

logger = get_logger("fallback.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fallback interpreter: record clip -> transcribe -> translate"
    )
    p.add_argument("--seconds", type=float, default=5.0, help="Duration to record (default 5s)")
    p.add_argument("--mic", type=int, default=None, metavar="INDEX", help="Input device index")
    p.add_argument("--list-mics", action="store_true", help="List input devices and exit")
    p.add_argument("--sample-rate", type=int, default=16000, help="Sample rate (default 16000)")
    p.add_argument("--transcribe-model", default=DEFAULT_TRANSCRIBE_MODEL)
    p.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    p.add_argument("--src", default="auto", choices=sorted(SUPPORTED_LANGS),
                   help="Source language (default: auto)")
    p.add_argument("--tgt", default="auto", choices=sorted(SUPPORTED_LANGS),
                   help="Target language (default: auto)")
    p.add_argument("--meeting-mode", default="locked", choices=["locked", "auto"],
                   help="locked (default): single routing for the whole clip. auto: detect per-clip.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_mics:
        print_input_devices()
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is not set.")
        print("Error: OPENAI_API_KEY is not set. Export it before running.", file=sys.stderr)
        return 1

    try:
        translation = run_fallback(
            seconds=args.seconds,
            mic_device=args.mic,
            sample_rate=args.sample_rate,
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
        logger.error(f"Fallback pipeline failed: {exc}", exc_info=True)
        return 1

    if translation:
        print("\n--- Translation ---")
        print_translation(translation, end="\n")
    else:
        print("\n[No speech detected or empty transcript]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
