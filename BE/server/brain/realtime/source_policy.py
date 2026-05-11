from __future__ import annotations

import re
from typing import Any, Dict, Optional

from server.brain.prompts.technical_terms import normalize_technical_terms
from server.brain.realtime.term_detector import detect_terms, is_short_but_valid_technical


SOURCE_MIN_FINAL_MEANINGFUL_CHARS = 5
SOURCE_MIN_FINAL_MEANINGFUL_TOKENS = 2
SOURCE_MIN_PARTIAL_MEANINGFUL_CHARS = 10
SOURCE_MIN_PARTIAL_MEANINGFUL_TOKENS = 2
SOURCE_MIN_SPEECH_DURATION_MS = 650
SOURCE_MIN_SHORT_MEANINGFUL_DURATION_MS = 320
SOURCE_QUALITY_HOLD_REASONS = frozenset(
    {
        "incomplete_fragment",
        "hanging_fragment",
        "low_confidence_technical_fragment",
        "too_few_meaningful_tokens",
    }
)
PUBLIC_RELAY_MIN_MEANINGFUL_CHARS = SOURCE_MIN_FINAL_MEANINGFUL_CHARS
PUBLIC_RELAY_MIN_MEANINGFUL_TOKENS = SOURCE_MIN_FINAL_MEANINGFUL_TOKENS
PUBLIC_RELAY_MIN_SPEECH_DURATION_MS = SOURCE_MIN_SPEECH_DURATION_MS

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
_SOURCE_SHORT_MEANINGFUL_PHRASES = {
    "ok",
    "okay",
    "yes",
    "no",
    "yeah",
    "yep",
    "yup",
    "sure",
    "thanks",
    "thank you",
    "sorry",
    "alright",
    "all right",
    "right",
    "got it",
    "i see",
    "uh huh",
    "not yet",
    "can't",
    "cannot",
    "vâng",
    "ok anh",
    "ok em",
    "đúng",
    "đúng rồi",
    "có",
    "được",
    "đồng ý",
    "cảm ơn",
    "xin lỗi",
    "được rồi",
    "rồi",
    "em hiểu",
    "anh hiểu",
    "hiểu rồi",
    "không",
    "chưa",
    "không được",
    "không thể",
    "はい",
    "うん",
    "いいえ",
    "まだです",
    "そうですね",
    "わかりました",
    "了解",
    "お願いします",
    "ありがとうございます",
    "すみません",
    "大丈夫です",
    "問題ないです",
    "無理",
    "ダメ",
    "네",
    "응",
    "감사합니다",
    "죄송합니다",
    "아니요",
    "안 됩니다",
    "알겠습니다",
    "嗯",
    "好的",
    "谢谢",
    "不好意思",
    "不",
    "不是",
    "不行",
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
_SOURCE_HANGING_FRAGMENT_RE = re.compile(
    r"(?:"
    r"\b(?:i\s+think|i\s+mean|we\s+need\s+to|we\s+should|i\s+want\s+to|"
    r"can\s+you|could\s+you|because|so|then|and|or|but)\s*$"
    r"|(?:em|anh|chị|tôi|mình|chúng\s+ta)\s+(?:nghĩ\s+là|cần|muốn)\s*$"
    r"|\b(?:bởi\s+vì|tại\s+vì|cho\s+nên|vì|nên|thì|là|và|nhưng)\s*$"
    r"|(?:けど|ので|えっと|あの)\s*$"
    r")",
    re.IGNORECASE,
)
_SOURCE_DANGLING_VI_RE = re.compile(
    r"(?:"
    r"\b(?:cái|con|bên|ở|với|cho|trên|lên|vào|ra|qua|từ|để|khi|nếu|mà|là|thì|và|nhưng|nên)\s*$"
    r"|(?:em|anh|chị|tôi|mình|chúng\s+ta|bọn\s+em|bên\s+em|bên\s+anh)\s*$"
    r")",
    re.IGNORECASE,
)
_SOURCE_ASR_UNCERTAIN_PHRASE_RE = re.compile(
    r"\b(?:"
    r"inaudible|unintelligible|unclear|không nghe rõ|nghe không rõ|không rõ|"
    r"tiếng ồn|tạp âm|âm thanh"
    r")\b",
    re.IGNORECASE,
)
_RELAY_META_OR_UNCLEAR_RE = re.compile(
    r"^\s*(?:"
    r"(?:sorry|i'?m\s+sorry|i\s+cannot|i\s+can't|cannot|can'?t)\s+"
    r"(?:hear|understand|translate|determine)|"
    r"(?:the\s+audio|the\s+speech|it)\s+(?:is|was)\s+(?:unclear|inaudible|unintelligible)|"
    r"(?:unclear|inaudible|unintelligible|not\s+enough\s+context|no\s+clear\s+speech)|"
    r"(?:(?:xin\s+lỗi[, ]+)?(?:không\s+nghe\s+rõ|không\s+rõ|không\s+thể\s+dịch|không\s+đủ\s+ngữ\s+cảnh))|"
    r"(?:聞き取れません|聞き取れない|不明です|翻訳できません|音声が不明)|"
    r"(?:들리지\s+않|명확하지\s+않|번역할\s+수\s+없)|"
    r"(?:听不清|不清楚|无法翻译|沒有聽清|无法确定)"
    r")",
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
    r"they|people|the\s+team|everyone|the\s+group)\s*$",
    re.IGNORECASE,
)
_PHRASE_EDGE_RE = re.compile(r"^[\s\"`*_.:,;!?。！？、，()\[\]{}-]+|[\s\"`*_.:,;!?。！？、，()\[\]{}-]+$")
_PHRASE_SPACE_RE = re.compile(r"[\s\"`*_.:,;!?。！？、，()\[\]{}-]+")


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
    overlap_level: str = "single",
) -> tuple[bool, str, Dict[str, Any]]:
    normalized = normalize_source_text(text)
    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_tokens = [
        token
        for token in tokens
        if token.lower() not in _SOURCE_FILLER_TOKENS
    ]
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    normalized_phrase = normalize_phrase_key(normalized)
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
        "overlap_level": overlap_level,
    }

    if not normalized:
        return False, "empty_public_relay", signal
    if relay_style == "summary":
        return True, "summary_fallback", signal
    if overlap_blocked:
        return False, "overlap_blocked_literal_relay_suppressed", signal
    if chaos or overlap_level == "heavy":
        return False, "heavy_overlap_literal_relay_suppressed", signal

    short_meaningful = normalized_phrase in _SOURCE_SHORT_MEANINGFUL_PHRASES
    high_value_short = short_meaningful or normalized_phrase in _PUBLIC_RELAY_HIGH_VALUE_SHORT_PHRASES
    if short_meaningful:
        signal["short_meaningful_turn"] = True
    if audience_count <= 0:
        signal["audience_unavailable_observed"] = True
    if _PUBLIC_RELAY_FRAGMENT_END_RE.search(normalized):
        return False, "incomplete_fragment", signal
    if (
        duration_ms is not None
        and duration_ms < PUBLIC_RELAY_MIN_SPEECH_DURATION_MS
        and not high_value_short
    ):
        return False, "speech_too_short_for_public_relay", signal
    if (
        len(meaningful_tokens) < PUBLIC_RELAY_MIN_MEANINGFUL_TOKENS
        and not high_value_short
        and meaningful_chars < PUBLIC_RELAY_MIN_MEANINGFUL_CHARS
    ):
        return False, "low_usefulness_short_turn", signal

    return True, "short_meaningful_turn" if short_meaningful else "ok", signal


def assess_relay_output_text(text: str) -> tuple[bool, str, Dict[str, Any]]:
    technical = normalize_technical_terms(text)
    normalized = normalize_source_text(technical.text)
    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    signal = {
        "chars": len(normalized),
        "meaningful_chars": meaningful_chars,
        "tokens": len(tokens),
        "technical_terms": technical.as_signal(),
    }

    if not normalized:
        return False, "empty_relay_output", signal
    if meaningful_chars == 0:
        return False, "punctuation_only_relay_output", signal
    if _RELAY_META_OR_UNCLEAR_RE.search(normalized):
        return False, "meta_or_unclear_relay_output", signal
    if technical.ambiguous_fragments:
        return False, "ambiguous_technical_relay_output", signal
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
    # Step 1: canonical normalization (ASR corrections, canonical form)
    technical = normalize_technical_terms(text)
    normalized = normalize_source_text(technical.text)

    # Step 2: rule-based term detection on normalized text
    # Provides richer signal than the flat protected_terms list alone
    term_analysis = detect_terms(normalized)

    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_tokens = [
        token
        for token in tokens
        if token.lower() not in _SOURCE_FILLER_TOKENS
    ]
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    normalized_phrase = normalize_phrase_key(normalized)
    short_meaningful = normalized_phrase in _SOURCE_SHORT_MEANINGFUL_PHRASES
    signal: Dict[str, Any] = {
        "chars": len(normalized),
        "meaningful_chars": meaningful_chars,
        "tokens": len(tokens),
        "meaningful_tokens": len(meaningful_tokens),
        "duration_ms": duration_ms,
        "final": final,
        "short_meaningful_turn": short_meaningful,
        "technical_terms": technical.as_signal(),
        "detected_terms": term_analysis.as_signal(),
    }

    if not normalized:
        return False, "empty_transcript", normalized, signal
    if _SOURCE_NOISE_ONLY_RE.match(normalized):
        return False, "noise_only_transcript", normalized, signal
    if _SOURCE_ASR_UNCERTAIN_PHRASE_RE.search(normalized):
        return False, "asr_uncertain_phrase", normalized, signal
    if meaningful_chars == 0:
        return False, "punctuation_only_transcript", normalized, signal

    collapsed_meaningful = "".join(char.lower() for char in normalized if char.isalnum())
    if (
        not short_meaningful
        and len(collapsed_meaningful) <= 3
        and len(set(collapsed_meaningful)) <= 1
    ):
        return False, "repetitive_low_signal_transcript", normalized, signal

    if not meaningful_tokens and not short_meaningful:
        return False, "filler_only_transcript", normalized, signal

    # Ambiguous fragment gate: reject when normalization found garbled ASR tech fragments
    # AND the rule-based detector did NOT find any confirmed technical terms in the same text.
    # This rejects "xem cái bg" (bg = unresolved) while passing "deploy k8s" (k8s = confirmed).
    if final and technical.ambiguous_fragments and not term_analysis.preserve_tokens:
        return False, "low_confidence_technical_fragment", normalized, signal

    if final and not short_meaningful:
        if _PUBLIC_RELAY_FRAGMENT_END_RE.search(normalized):
            return False, "incomplete_fragment", normalized, signal
        if _SOURCE_HANGING_FRAGMENT_RE.search(normalized):
            return False, "hanging_fragment", normalized, signal
        if _SOURCE_DANGLING_VI_RE.search(normalized):
            return False, "hanging_vietnamese_fragment", normalized, signal

    if final and short_meaningful:
        if (
            duration_ms is not None
            and duration_ms < SOURCE_MIN_SHORT_MEANINGFUL_DURATION_MS
        ):
            return False, "speech_too_short", normalized, signal
        return True, "short_meaningful_turn", normalized, signal

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

    # Short-but-valid technical bypass: allow confirmed technical terms through
    # even when they're short by alnum character count.
    # Uses rule-based detection (term_detector) rather than the flat curated list.
    has_confirmed_tech = is_short_but_valid_technical(normalized, term_analysis)
    if meaningful_chars < min_chars:
        if not has_confirmed_tech:
            return False, "too_short_transcript", normalized, signal
        signal["short_tech_term_bypass"] = True

    if len(meaningful_tokens) < min_tokens:
        longest_token = max((len(token) for token in meaningful_tokens), default=0)
        if longest_token < min_chars and not has_confirmed_tech:
            return False, "too_few_meaningful_tokens", normalized, signal

    if final and duration_ms is not None and duration_ms < SOURCE_MIN_SPEECH_DURATION_MS:
        if not has_confirmed_tech:
            return False, "speech_too_short", normalized, signal

    return True, "ok", normalized, signal


def source_transcript_needs_quality_hold(
    text: str,
    *,
    duration_ms: Optional[int],
) -> tuple[bool, str, str, Dict[str, Any]]:
    accepted, reason, normalized, signal = assess_source_transcript(
        text,
        duration_ms=duration_ms,
        final=True,
    )
    if accepted:
        term_signal = signal.get("detected_terms")
        if isinstance(term_signal, dict) and term_signal.get("ambiguous"):
            return True, "ambiguous_detected_terms", normalized, signal
        return False, "accepted_fast_path", normalized, signal
    if reason in SOURCE_QUALITY_HOLD_REASONS or reason == "hanging_vietnamese_fragment":
        return True, reason, normalized, signal
    return False, reason, normalized, signal


def normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_phrase_key(text: str) -> str:
    normalized = normalize_source_text(text).casefold()
    normalized = _PHRASE_EDGE_RE.sub("", normalized)
    return _PHRASE_SPACE_RE.sub(" ", normalized).strip()
