from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from server.brain.prompts.technical_terms import normalize_technical_terms
from server.brain.realtime.term_detector import detect_terms, is_short_but_valid_technical

_logger = logging.getLogger(__name__)


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
    "hello",
    "hi",
    "bye",
    "good morning",
    "good afternoon",
    "dạ",
    "dạ vâng",
    "đúng vậy",
    "đúng thế",
    "chào",
    "xin chào",
    "chào anh",
    "chào chị",
    "chào em",
    "chào mọi người",
    "tạm biệt",
    "こんにちは",
    "おはようございます",
    "お疲れ様です",
    "そうです",
    "안녕하세요",
    "你好",
}
# Vietnamese/Japanese politeness particles that do not change a short reply's
# meaning ("Đúng ạ" == "Đúng", "OK nhé" == "OK", "はいです" is not covered).
_SHORT_PHRASE_TRAILING_PARTICLES = ("ạ", "nhé", "nha", "nhá", "ha", "à", "luôn", "ね", "よ")
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
# Phrases speech-to-text models are known to emit for silence, music or room
# noise (subtitle/video-outro artefacts from their training data). A meeting
# participant does not say these, so they never reach translation.
_SOURCE_ASR_HALLUCINATION_RE = re.compile(
    r"(?:"
    r"thanks?\s+(?:you\s+)?for\s+watching|"
    r"(?:please\s+)?(?:like\s+and\s+)?subscribe\s+(?:to\s+)?(?:my|our|the)\s+channel|"
    r"subtitles?\s+(?:by|created\s+by|provided\s+by)|amara\.org|"
    r"(?:cảm\s+ơn|cám\s+ơn)\s+(?:các\s+bạn\s+)?(?:đã\s+)?(?:theo\s+dõi|xem\s+video)|"
    r"(?:hãy\s+)?(?:đăng\s+ký|subscribe)\s+(?:cho\s+)?kênh|"
    r"ご視聴ありがとうございました|チャンネル登録|字幕(?:作成|提供)|"
    r"시청해\s*주셔서\s*감사합니다|구독과\s*좋아요|"
    r"请不吝点赞|订阅.{0,4}频道|字幕由"
    r")",
    re.IGNORECASE,
)
_SOURCE_TRANSLATABLE_RE = re.compile(r"[^\W_]", re.UNICODE)

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
_NARRATOR_OPENING_PATTERNS = _NARRATOR_OPENING_PATTERNS + (
    re.compile(
        r"^\s*(?:the\s+user|the\s+participant|the\s+source(?:\s+text)?|the\s+transcript)\s+"
        r"(?:said|says|is\s+saying|asked|asks|wrote|writes|mentioned|reads)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:người\s+dùng|người\s+tham\s+gia|văn\s+bản\s+gốc)\s+(?:đã\s+)?(?:nói|hỏi|viết)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:ユーザー|話者|参加者)(?:さん)?(?:は|が)"),
    re.compile(r"^\s*(?:translation|bản\s+dịch|翻訳)\s*[:：]", re.IGNORECASE),
)
# Speech acts an interpreter never produces on its own behalf. The output gate
# rejects a relay that performs one of them unless the source text performs the
# same act (in any room language), so a participant who really says
# "please go ahead" is still relayed. Families are matched per speech act, not
# per sentence.
_ASSISTANT_SPEECH_ACT_PATTERNS: Dict[str, re.Pattern[str]] = {
    "self_describes_translation": re.compile(
        r"(?:"
        r"\b(?:i\s*'?\s*a?m|i\s+will|i\s*'?\s*ll|i\s+can|let\s+me|i\s+am\s+going\s+to)\b"
        r"[^.!?\n]{0,40}\b(?:translat|interpret|relay)\w*|"
        r"\b(?:tôi|mình|em|anh|chị|chúng\s+tôi|bọn\s+em)\s+(?:sẽ|có\s+thể|đang|ở\s+đây\s+để|sẵn\s+sàng)[^.!?\n]{0,30}\b(?:dịch|phiên\s+dịch|chuyển\s+ngữ)|"
        r"(?:翻訳|通訳)(?:します|いたします|しましょう|の準備|させていただきます)|"
        r"(?:번역|통역)(?:해\s*드리겠|하겠습니다|해\s*드릴게)|"
        r"我(?:会|来|可以|将)(?:为您|帮您)?(?:翻译|口译)"
        r")",
        re.IGNORECASE,
    ),
    "offers_help": re.compile(
        r"(?:"
        r"\bhow\s+(?:can|may)\s+i\s+(?:help|assist)|"
        r"\b(?:ready|happy|glad|here)\s+to\s+(?:help|assist)|"
        r"\blet\s+me\s+know\s+(?:what|how)\s+(?:you\s*'?\s*d|you\s+would|i\s+can)\b|"
        r"\bwhat\s+would\s+you\s+like\s+me\s+to\b|"
        r"\b(?:is\s+there\s+)?anything\s+(?:else\s+)?i\s+can\s+(?:do|help)|"
        r"\b(?:tôi|mình|em|anh|chị)\s+(?:có\s+thể\s+)?giúp\s+(?:gì|được\s+gì)|"
        r"\bsẵn\s+sàng\s+(?:hỗ\s+trợ|giúp)|\brất\s+vui\s+được\s+(?:giúp|hỗ\s+trợ)|"
        r"\bcho\s+(?:tôi|mình|em|anh|chị)\s+biết\s+(?:cần|muốn)|"
        r"喜んで(?:お手伝い|手伝)|"
        r"お手伝い(?:します|しましょう|できること)|何かございましたら|"
        r"도와\s*드릴|무엇을\s+도와|"
        r"有什么(?:可以)?(?:帮|帮助)"
        r")",
        re.IGNORECASE,
    ),
    "invites_speech": re.compile(
        r"(?:"
        r"\bplease\s+(?:go\s+ahead|speak|say\s+something|start\s+speaking|continue\s+speaking)|"
        r"\bgo\s+ahead\s+and\s+(?:speak|talk|start)|"
        r"\b(?:speak|talk|start)\s+whenever\b|"
        r"\bwhenever\s+you\s*'?\s*(?:re|are)\s+ready|"
        r"\bi\s*'?\s*a?m\s+listening\b|"
        r"\bi\s+didn\s*'?\s*t\s+(?:catch|hear)|"
        r"\b(?:could|can|would)\s+you\s+(?:please\s+)?(?:repeat|say\s+(?:that|it)\s+again)|"
        r"\b(?:xin\s+)?(?:mời|vui\s+lòng|hãy)\s+(?:anh\s+|chị\s+|bạn\s+|em\s+)?(?:nói|bắt\s+đầu\s+nói|nói\s+tiếp)|"
        r"\b(?:anh|chị|bạn|em)\s+cứ\s+nói|"
        r"\b(?:nói|nhắc)\s+lại\b|\b(?:tôi|mình|em|anh|chị)\s+đang\s+(?:nghe|lắng\s+nghe)|"
        r"\b(?:chưa|không)\s+nghe\s+(?:kịp|thấy|được)|"
        r"(?:どうぞ)?お話しください|話してください|もう一度(?:お願い|言って)|聞いています|"
        r"말씀해\s*주세요|다시\s+말씀|"
        r"请(?:说|讲|再说一遍)"
        r")",
        re.IGNORECASE,
    ),
    "self_identifies_as_ai": re.compile(
        r"(?:"
        r"\bas\s+(?:an|your)\s+(?:ai|assistant|interpreter|translator|language\s+model)\b|"
        r"\bi\s*'?\s*a?m\s+(?:an?\s+|your\s+)?(?:ai|assistant|interpreter|translator|language\s+model|brse)\b|"
        r"\b(?:tôi|mình|em|anh|chị)\s+là\s+(?:một\s+)?(?:ai|trợ\s+lý|phiên\s+dịch\s+viên|thông\s+dịch\s+viên|brse)\b|"
        r"(?:私は|わたしは)(?:AI|アシスタント|通訳|翻訳者)|"
        r"저는\s*(?:AI|어시스턴트|통역사)|"
        r"我是(?:AI|人工智能|助手|翻译)"
        r")",
        re.IGNORECASE,
    ),
}
# Translation length is bounded by the source: an interpreted relay can expand
# (Japanese -> English roughly triples the character count), but not by an
# unrelated sentence. CJK characters are weighted to compare across scripts.
RELAY_OUTPUT_MAX_LENGTH_RATIO = 4.0
SOURCE_UNBOUND_OUTPUT_REASONS = frozenset(
    {
        "assistant_reply_relay_output",
        "relay_output_not_source_bound",
        "relay_output_without_source",
    }
)
RELAY_OUTPUT_LENGTH_SLACK = 40
_CJK_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]")

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

    short_meaningful = is_short_meaningful_phrase(normalized_phrase)
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


def assess_relay_output_text(
    text: str,
    *,
    source_text: Optional[str] = None,
    final: bool = True,
    relay_style: str = "normal",
) -> tuple[bool, str, Dict[str, Any]]:
    """Validate model output before it becomes public text or TTS audio.

    With ``source_text`` the output is also checked against its source
    utterance: an assistant speech act the source does not contain, or a
    length the source cannot explain, means the model replied instead of
    translating, and the output is rejected.
    """
    technical = normalize_technical_terms(text)
    normalized = normalize_source_text(technical.text)
    tokens = _SOURCE_TOKEN_RE.findall(normalized)
    meaningful_chars = sum(1 for char in normalized if char.isalnum())
    signal: Dict[str, Any] = {
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
    if source_text is not None:
        bound_ok, bound_reason = _relay_output_is_source_bound(
            normalized,
            source_text,
            final=final,
            relay_style=relay_style,
            signal=signal,
        )
        if not bound_ok:
            return False, bound_reason, signal
    if technical.ambiguous_fragments:
        return False, "ambiguous_technical_relay_output", signal
    return True, "ok", signal


def assistant_speech_acts(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    return [
        family
        for family, pattern in _ASSISTANT_SPEECH_ACT_PATTERNS.items()
        if pattern.search(normalized)
    ]


def weighted_text_length(text: str) -> int:
    normalized = normalize_source_text(text)
    cjk = len(_CJK_CHAR_RE.findall(normalized))
    return len(normalized) - cjk + cjk * 3


def _relay_output_is_source_bound(
    output: str,
    source_text: str,
    *,
    final: bool,
    relay_style: str,
    signal: Dict[str, Any],
) -> tuple[bool, str]:
    source = normalize_source_text(source_text)
    if not source_text_is_translatable(source):
        signal["source_chars"] = len(source)
        return False, "relay_output_without_source"

    output_acts = assistant_speech_acts(output)
    if output_acts:
        source_acts = set(assistant_speech_acts(source))
        unsupported = [act for act in output_acts if act not in source_acts]
        if unsupported:
            signal["assistant_speech_acts"] = unsupported
            return False, "assistant_reply_relay_output"

    if relay_style != "summary":
        source_len = weighted_text_length(source)
        output_len = weighted_text_length(output)
        max_len = int(source_len * RELAY_OUTPUT_MAX_LENGTH_RATIO + RELAY_OUTPUT_LENGTH_SLACK)
        signal["source_weighted_chars"] = source_len
        signal["output_weighted_chars"] = output_len
        if output_len > max_len:
            # Partial text only grows, so an over-long partial is final already.
            signal["max_weighted_chars"] = max_len
            return False, "relay_output_not_source_bound"
    return True, "ok"


def source_text_is_translatable(text: str) -> bool:
    """True when text contains at least one letter or digit to translate."""
    return bool(_SOURCE_TRANSLATABLE_RE.search(normalize_source_text(text)))


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
    short_meaningful = is_short_meaningful_phrase(normalized_phrase)
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
    if _SOURCE_ASR_HALLUCINATION_RE.search(normalized):
        return False, "asr_hallucination_transcript", normalized, signal

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


def is_short_meaningful_phrase(phrase_key: str) -> bool:
    """Short replies that carry meaning on their own ("OK", "Vâng", "はい", "Đúng ạ")."""
    if phrase_key in _SOURCE_SHORT_MEANINGFUL_PHRASES:
        return True
    words = phrase_key.split(" ")
    while len(words) > 1 and words[-1] in _SHORT_PHRASE_TRAILING_PARTICLES:
        words.pop()
        if " ".join(words) in _SOURCE_SHORT_MEANINGFUL_PHRASES:
            return True
    for particle in _SHORT_PHRASE_TRAILING_PARTICLES:
        # Japanese particles attach without a space ("はいね" is rare; "そうですね" is listed).
        if not particle.isascii() and phrase_key.endswith(particle) and len(phrase_key) > len(particle):
            if phrase_key[: -len(particle)] in _SOURCE_SHORT_MEANINGFUL_PHRASES:
                return True
    return False


def validated_translation(
    translated: str,
    *,
    source_text: str,
    context: str,
    src_lang: str,
    tgt_lang: str,
) -> Optional[str]:
    """Return the translation only when it is bound to its source text."""
    accepted, reason, signal = assess_relay_output_text(translated, source_text=source_text)
    if accepted:
        return translated
    _logger.warning(
        "%s translation rejected: src=%s tgt=%s reason=%s signal=%s",
        context,
        src_lang,
        tgt_lang,
        reason,
        {key: value for key, value in signal.items() if key != "technical_terms"},
    )
    return None
