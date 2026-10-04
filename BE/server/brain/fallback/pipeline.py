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
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

from server.shared.audio import record_clip, DEFAULT_SAMPLE_RATE
from server.brain.prompts.language import build_instructions, LANG_NAMES
from server.brain.prompts.translation_engine import wrap_source_text
from server.brain.realtime.source_policy import assess_source_transcript, validated_translation
from server.shared.logging_utils import get_logger, loggable_text

logger = get_logger("fallback.pipeline")

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"
DEFAULT_TRANSCRIBE_MODEL = "whisper-1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"


def _pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _save_wav(pcm_bytes: bytes, sample_rate: int) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RECORDINGS_DIR / f"clip_{ts}.wav"
    path.write_bytes(_pcm_to_wav_bytes(pcm_bytes, sample_rate))
    logger.info(f"Saved recording to {path}")
    return path


def _transcribe(wav_path: Path, api_key: str, model: str) -> str:
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
    logger.info(f"Transcription done in {elapsed:.2f}s: {loggable_text(transcript)}")
    return transcript


def _translate(transcript: str, api_key: str, model: str, system_prompt: str) -> str:
    import openai
    client = openai.OpenAI(api_key=api_key)
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": wrap_source_text(transcript)},
        ],
    )
    elapsed = time.monotonic() - t0
    translation = (resp.choices[0].message.content or "").strip()
    logger.info(f"Translation done in {elapsed:.2f}s: {loggable_text(translation)}")
    return validated_translation(
        translation,
        source_text=transcript,
        context="fallback",
        src_lang="auto",
        tgt_lang="auto",
    ) or ""


def run_fallback(
    seconds: float = 5.0,
    mic_device: Optional[int] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    api_key: Optional[str] = None,
    transcribe_model: str = DEFAULT_TRANSCRIBE_MODEL,
    chat_model: str = DEFAULT_CHAT_MODEL,
    src_lang: str = "auto",
    tgt_lang: str = "auto",
    meeting_mode: str = "locked",
) -> str:
    """
    Full fallback pipeline: record -> transcribe -> translate.
    Returns the final translation string.

    meeting_mode="locked": build routing from src/tgt before recording; never change.
    meeting_mode="auto":   detect language from transcript, then route dynamically.
    """
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    # In locked mode with explicit src/tgt, build instructions upfront.
    # In auto mode (or locked+auto src/tgt), we build after transcription.
    upfront_prompt: Optional[str] = None
    if meeting_mode == "locked" and src_lang != "auto" and tgt_lang != "auto":
        upfront_prompt = build_instructions(src_lang, tgt_lang)
        print(f"[MeetingMode] locked | src={src_lang} tgt={tgt_lang}", flush=True)
    elif meeting_mode == "locked":
        print(f"[MeetingMode] locked | src={src_lang} tgt={tgt_lang} (will detect on transcript)", flush=True)
    else:
        print(f"[MeetingMode] auto | src={src_lang} tgt={tgt_lang} (sticky enabled)", flush=True)

    logger.info(
        f"Recording {seconds}s | src={src_lang} tgt={tgt_lang} | meeting_mode={meeting_mode} | device={mic_device}"
    )
    print(f"Recording for {seconds:.0f} seconds... Speak now!", flush=True)

    t0 = time.monotonic()
    pcm = record_clip(seconds=seconds, device=mic_device, sample_rate=sample_rate)
    logger.info(f"Recorded {len(pcm)} bytes in {time.monotonic() - t0:.2f}s")

    wav_path = _save_wav(pcm, sample_rate)

    print("Transcribing...", flush=True)
    transcript = _transcribe(wav_path, api_key, transcribe_model)

    accepted, reason, _normalized, _signal = assess_source_transcript(
        transcript,
        duration_ms=None,
        final=True,
    )
    if not accepted:
        logger.warning(f"Transcript not translated: reason={reason}")
        return ""

    print(f"[You] {transcript}", flush=True)
    print("Translating...", flush=True)

    # Resolve system prompt: use upfront if locked+explicit, else build from src/tgt (model detects)
    system_prompt = upfront_prompt if upfront_prompt is not None else build_instructions(src_lang, tgt_lang)
    translation = _translate(transcript, api_key, chat_model, system_prompt)

    return translation
