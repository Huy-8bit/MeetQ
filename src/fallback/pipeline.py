"""
src/fallback/pipeline.py
Non-realtime fallback pipeline:
  1. Record a short clip from mic
  2. Save to recordings/ as a WAV file
  3. Transcribe via OpenAI audio API
  4. Translate via OpenAI chat API
  5. Return final translation string
"""
from __future__ import annotations

import io
import os
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from src.common.audio import record_clip, DEFAULT_SAMPLE_RATE
from src.common.logging_utils import get_logger

logger = get_logger("fallback.pipeline")

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"
DEFAULT_TRANSCRIBE_MODEL = "whisper-1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"

TRANSLATION_SYSTEM_PROMPT = (
    "You are a bilingual interpreter between Vietnamese and English. "
    "Detect the language of the input text. "
    "If Vietnamese, translate to English. "
    "If English, translate to Vietnamese. "
    "Output the translation ONLY. No labels, no explanations."
)


def _pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw PCM16 bytes into a WAV container in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _save_wav(pcm_bytes: bytes, sample_rate: int) -> Path:
    """Save PCM bytes as a timestamped WAV file and return the path."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"clip_{ts}.wav"
    wav_bytes = _pcm_to_wav_bytes(pcm_bytes, sample_rate)
    path.write_bytes(wav_bytes)
    logger.info(f"Saved recording to {path}")
    return path


def _transcribe(wav_path: Path, api_key: str, model: str) -> str:
    """Call OpenAI Whisper transcription and return transcript text."""
    import openai
    client = openai.OpenAI(api_key=api_key)
    t0 = time.monotonic()
    with open(wav_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=model,
            file=f,
            response_format="text",
        )
    elapsed = time.monotonic() - t0
    transcript = result.strip() if isinstance(result, str) else result.text.strip()
    logger.info(f"Transcription done in {elapsed:.2f}s: {transcript!r}")
    return transcript


def _translate(transcript: str, api_key: str, model: str) -> str:
    """Call OpenAI chat API to translate transcript and return translated text."""
    import openai
    client = openai.OpenAI(api_key=api_key)
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    elapsed = time.monotonic() - t0
    translation = resp.choices[0].message.content.strip()
    logger.info(f"Translation done in {elapsed:.2f}s: {translation!r}")
    return translation


def run_fallback(
    seconds: float = 5.0,
    mic_device: Optional[int] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    api_key: Optional[str] = None,
    transcribe_model: str = DEFAULT_TRANSCRIBE_MODEL,
    chat_model: str = DEFAULT_CHAT_MODEL,
) -> str:
    """
    Full fallback pipeline: record -> transcribe -> translate.
    Returns the final translation string.
    """
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    logger.info(f"Recording {seconds}s from device {mic_device} at {sample_rate}Hz...")
    print(f"Recording for {seconds:.0f} seconds... Speak now!", flush=True)

    t0 = time.monotonic()
    pcm = record_clip(seconds=seconds, device=mic_device, sample_rate=sample_rate)
    record_elapsed = time.monotonic() - t0
    logger.info(f"Recorded {len(pcm)} bytes in {record_elapsed:.2f}s")

    wav_path = _save_wav(pcm, sample_rate)

    print("Transcribing...", flush=True)
    transcript = _transcribe(wav_path, api_key, transcribe_model)

    if not transcript:
        logger.warning("Empty transcript. No speech detected.")
        return ""

    print(f"Transcript: {transcript}", flush=True)
    print("Translating...", flush=True)
    translation = _translate(transcript, api_key, chat_model)

    return translation
