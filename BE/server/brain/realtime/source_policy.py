from __future__ import annotations

import re
from typing import Any, Dict, Optional


SOURCE_MIN_FINAL_MEANINGFUL_CHARS = 4
SOURCE_MIN_FINAL_MEANINGFUL_TOKENS = 1
SOURCE_MIN_PARTIAL_MEANINGFUL_CHARS = 8
SOURCE_MIN_PARTIAL_MEANINGFUL_TOKENS = 2
SOURCE_MIN_SPEECH_DURATION_MS = 420
PUBLIC_RELAY_MIN_MEANINGFUL_CHARS = 8
PUBLIC_RELAY_MIN_MEANINGFUL_TOKENS = 2
PUBLIC_RELAY_MIN_SPEECH_DURATION_MS = 650

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
_PUBLIC_RELAY_ACK_ONLY_PHRASES = {
    "ok",
    "okay",
    "yeah",
    "yep",
    "yup",
    "sure",
    "alright",
    "all right",
    "right",
    "got it",
    "i see",
    "uh huh",
    "vâng",
    "ừ",
    "ừm",
    "ờ",
    "ok anh",
    "ok em",
    "được rồi",
    "rồi",
    "hiểu rồi",
    "はい",
    "うん",
    "そうですね",
    "わかりました",
    "了解",
    "네",
    "응",
    "알겠습니다",
    "嗯",
    "好的",
}
_PUBLIC_RELAY_HIGH_VALUE_SHORT_PHRASES = {
    "no",
    "not yet",
    "can't",
    "cannot",
    "không",
    "chưa",
    "không được",
    "không thể",
    "いいえ",
    "まだです",
    "無理",
    "ダメ",
    "아니요",
    "안 됩니다",
    "不",
    "不是",
    "不行",
}
_PUBLIC_RELAY_FRAGMENT_END_RE = re.compile(
    r"(?:"
    r"\b(?:and|or|but|because|so|then|with|for|to|of|và|hoặc|nhưng|vì|nên|thì|là)\s*"
    r"|[,;:、，]\s*"
    r"|\.\.\.\s*|…\s*"
    r")$",
    re.IGNORECASE,
)
_NARRATOR_OPENING_PATTERNS = (
    re.compile(
        r"^\s*(?:the\s+speaker|this\s+speaker|that\s+speaker|someone|one\s+person|"
        r"he|she|they)\s+"
        r"(?:said|says|is\s+saying|was\s+saying|mentioned|explained|asked|is\s+asking|"
        r"told|is\s+telling|stated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*[\wÀ-ÖØ-öø-ÿ'.-]{1,40}\s+"
        r"(?:said|says|is\s+saying|was\s+saying|mentioned|explained|asked|is\s+asking|"
        r"told|is\s+telling|stated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:they|people|the\s+team|everyone|the\s+group)\s+"
        r"(?:are\s+)?(?:discussing|talking\s+about|going\s+over)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:người\s+nói|anh\s+ấy|cô\s+ấy|họ|mọi\s+người|cả\s+nhóm)\s+"
        r"(?:đang\s+)?(?:nói|trao\s+đổi|thảo\s+luận|bàn|cho\s+biết|giải\s+thích|hỏi)\b",
        re.IGNORECASE,
    ),
)
_NARRATOR_HOLD_OPENING_RE = re.compile(
    r"^\s*(?:the\s+speaker|this\s+speaker|that\s+speaker|someone|one\s+person|"
    r"he|she|they|người\s+nói|anh\s+ấy|cô\s+ấy|họ|mọi\s+người|"
    r"[\wÀ-ÖØ-öø-ÿ'.-]{1,40})\s*$",
    re.IGNORECASE,
)


def source_state_is_valid_for_output(state: Dict[str, Any]) -> bool:
    return bool(
        state.get("source_committed")
        and state.get("source_final")
        and state.get("source_valid")
        and state.get("source_text")
    )


def assess_public_relay_readiness(
    text: str,
    *,
    duration_ms: Optional[int],
    relay_style: str = "normal",
    overlap_blocked: bool = False,
    audience_count: int = 0,
    chaos: bool = False,
) -> tuple[bool, str, Dict[str, Any]]:
    normalized = normalize_source_text(text)
    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_tokens = [
        token
        for token in tokens
        if token.lower() not in _SOURCE_FILLER_TOKENS
    ]
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    normalized_phrase = normalized.casefold()
    signal = {
        "chars": len(normalized),
        "meaningful_chars": meaningful_chars,
        "tokens": len(tokens),
        "meaningful_tokens": len(meaningful_tokens),
        "duration_ms": duration_ms,
        "relay_style": relay_style,
        "overlap_blocked": overlap_blocked,
        "audience_count": audience_count,
        "chaos": chaos,
    }

    if not normalized:
        return False, "empty_public_relay", signal
    if audience_count <= 0:
        return False, "no_target_audience", signal
    if relay_style == "summary":
        return True, "summary_fallback", signal
    if overlap_blocked:
        return False, "overlap_secondary_literal_relay_suppressed", signal
    if chaos:
        return False, "chaotic_context_literal_relay_suppressed", signal
    if normalized_phrase in _PUBLIC_RELAY_ACK_ONLY_PHRASES:
        return False, "low_usefulness_acknowledgement", signal

    high_value_short = normalized_phrase in _PUBLIC_RELAY_HIGH_VALUE_SHORT_PHRASES
    if _PUBLIC_RELAY_FRAGMENT_END_RE.search(normalized):
        return False, "incomplete_fragment", signal
    if (
        duration_ms is not None
        and duration_ms < PUBLIC_RELAY_MIN_SPEECH_DURATION_MS
        and not high_value_short
        and meaningful_chars < PUBLIC_RELAY_MIN_MEANINGFUL_CHARS + 4
    ):
        return False, "speech_too_short_for_public_relay", signal
    if (
        len(meaningful_tokens) < PUBLIC_RELAY_MIN_MEANINGFUL_TOKENS
        and not high_value_short
        and meaningful_chars < PUBLIC_RELAY_MIN_MEANINGFUL_CHARS + 4
    ):
        return False, "low_usefulness_short_turn", signal

    return True, "ok", signal


def relay_text_has_narrator_opening(
    text: str,
    *,
    speaker_name: Optional[str] = None,
) -> bool:
    normalized = normalize_source_text(text)
    if len(normalized) < 4:
        return False

    for pattern in _NARRATOR_OPENING_PATTERNS:
        if pattern.search(normalized):
            return True

    if speaker_name:
        name = normalize_source_text(speaker_name).casefold()
        candidate = normalized.casefold()
        if name and candidate.startswith(name):
            remainder = candidate[len(name):].lstrip(" ,:：-")
            if re.match(
                r"^(?:said|says|is\s+saying|was\s+saying|mentioned|explained|asked|"
                r"nói|đang\s+nói|cho\s+biết|giải\s+thích|hỏi|さんは|は)",
                remainder,
                re.IGNORECASE,
            ):
                return True
    return False


def relay_text_needs_more_opening_context(
    text: str,
    *,
    speaker_name: Optional[str] = None,
) -> bool:
    normalized = normalize_source_text(text)
    if not normalized or len(normalized) > 32:
        return False
    if speaker_name:
        name = normalize_source_text(speaker_name)
        if name and normalized.casefold() == name.casefold():
            return True
    return bool(_NARRATOR_HOLD_OPENING_RE.search(normalized))


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
