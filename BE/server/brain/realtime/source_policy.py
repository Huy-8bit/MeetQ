from __future__ import annotations

import re
from typing import Any, Dict, Optional


SOURCE_MIN_FINAL_MEANINGFUL_CHARS = 4
SOURCE_MIN_FINAL_MEANINGFUL_TOKENS = 1
SOURCE_MIN_PARTIAL_MEANINGFUL_CHARS = 8
SOURCE_MIN_PARTIAL_MEANINGFUL_TOKENS = 2
SOURCE_MIN_SPEECH_DURATION_MS = 420

_SOURCE_TOKEN_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+|[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)
_SOURCE_NOISE_ONLY_RE = re.compile(
    r"^[\s\[\]\(\)\{\}\"'`*_.:,;!?。！？、-]*"
    r"(?:background\s+noise|noise|silence|silent|inaudible|unintelligible|"
    r"music|typing|keyboard|cough(?:ing)?|laugh(?:s|ter|ing)?|breath(?:ing)?|"
    r"no\s+speech|speech\s+unclear)"
    r"[\s\[\]\(\)\{\}\"'`*_.:,;!?。！？、-]*$",
    re.IGNORECASE,
)
_SOURCE_FILLER_TOKENS = {
    "a",
    "ah",
    "aha",
    "eh",
    "er",
    "erm",
    "hm",
    "hmm",
    "hmmm",
    "mm",
    "mmm",
    "mhm",
    "oh",
    "uh",
    "uhh",
    "um",
    "umm",
    "ờ",
    "ừ",
    "ừm",
    "à",
    "ờm",
    "àh",
    "ừh",
    "え",
    "えー",
    "えっと",
    "あの",
    "음",
    "어",
    "嗯",
    "啊",
    "呃",
}


def source_state_is_valid_for_output(state: Dict[str, Any]) -> bool:
    return bool(
        state.get("source_committed")
        and state.get("source_final")
        and state.get("source_valid")
        and state.get("source_text")
    )


def assess_source_transcript(
    text: str,
    *,
    duration_ms: Optional[int],
    final: bool,
) -> tuple[bool, str, str, Dict[str, Any]]:
    normalized = normalize_source_text(text)
    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_tokens = [
        token
        for token in tokens
        if token.lower() not in _SOURCE_FILLER_TOKENS
    ]
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    signal = {
        "chars": len(normalized),
        "meaningful_chars": meaningful_chars,
        "tokens": len(tokens),
        "meaningful_tokens": len(meaningful_tokens),
        "duration_ms": duration_ms,
        "final": final,
    }

    if not normalized:
        return False, "empty_transcript", normalized, signal
    if _SOURCE_NOISE_ONLY_RE.match(normalized):
        return False, "noise_only_transcript", normalized, signal
    if meaningful_chars == 0:
        return False, "punctuation_only_transcript", normalized, signal

    collapsed_meaningful = "".join(char.lower() for char in normalized if char.isalnum())
    if len(collapsed_meaningful) <= 3 and len(set(collapsed_meaningful)) <= 1:
        return False, "repetitive_low_signal_transcript", normalized, signal

    if not meaningful_tokens:
        return False, "filler_only_transcript", normalized, signal

    min_chars = (
        SOURCE_MIN_FINAL_MEANINGFUL_CHARS
        if final
        else SOURCE_MIN_PARTIAL_MEANINGFUL_CHARS
    )
    min_tokens = (
        SOURCE_MIN_FINAL_MEANINGFUL_TOKENS
        if final
        else SOURCE_MIN_PARTIAL_MEANINGFUL_TOKENS
    )
    if meaningful_chars < min_chars:
        return False, "too_short_transcript", normalized, signal
    if len(meaningful_tokens) < min_tokens:
        longest_token = max((len(token) for token in meaningful_tokens), default=0)
        if longest_token < min_chars:
            return False, "too_few_meaningful_tokens", normalized, signal

    if final and duration_ms is not None and duration_ms < SOURCE_MIN_SPEECH_DURATION_MS:
        return False, "speech_too_short", normalized, signal

    return True, "ok", normalized, signal


def normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())
