"""
server/brain/prompts/language.py
Language constants, heuristic detection, and instruction building.

Supported language codes: "auto", "vi", "en", "ja", "zh", "ko", "fr", "es"
"""
from __future__ import annotations

import re
from typing import Optional

from server.brain.prompts.technical_terms import build_technical_translation_policy
from server.brain.prompts.translation_engine import TRANSLATION_ENGINE_NO_SELF_SPEECH_POLICY

# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------

PLATFORM_SUPPORTED_LANGS = ("vi", "en", "ja", "zh", "ko", "fr", "es")
SUPPORTED_LANGUAGE_CODES = ("auto",) + PLATFORM_SUPPORTED_LANGS
SUPPORTED_LANGS = set(SUPPORTED_LANGUAGE_CODES)

LANG_NAMES = {
    "vi": "Vietnamese",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "fr": "French",
    "es": "Spanish",
    "auto": "auto",
}

# Default target when src is detected (auto-routing table)
DEFAULT_TGT: dict[str, str] = {
    "vi": "en",
    "en": "vi",
    "ja": "en",
    "zh": "en",
    "ko": "en",
    "fr": "en",
    "es": "en",
}

# ---------------------------------------------------------------------------
# Heuristic language detector
# ---------------------------------------------------------------------------

# Japanese kana: Hiragana U+3040–U+309F, Katakana U+30A0–U+30FF
_RE_JAPANESE_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")

# Chinese Han ideographs (also used in Japanese Kanji; kana detection runs first)
_RE_CJK_HAN = re.compile(r"[\u4e00-\u9fff]")

# Korean Hangul syllables + Jamo
_RE_KOREAN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")

# Vietnamese: letters with specific diacritics not present in standard Latin
# Key markers: ắ ặ ầ ề ộ ử ỳ ơ ư đ and their case variants
_RE_VIETNAMESE = re.compile(
    r"[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
    r"ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
)

_RE_FRENCH_MARKERS = re.compile(r"[àâæçéèêëîïôœùûüÿÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸ]")
_RE_SPANISH_MARKERS = re.compile(r"[áéíñóúü¡¿ÁÉÍÑÓÚÜ]")
_RE_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÿ']+")

_FRENCH_COMMON_WORDS = {
    "bonjour",
    "merci",
    "avec",
    "pour",
    "dans",
    "mais",
    "pas",
    "est",
    "une",
    "des",
    "nous",
    "vous",
    "je",
    "les",
    "que",
}
_SPANISH_COMMON_WORDS = {
    "hola",
    "gracias",
    "con",
    "para",
    "pero",
    "que",
    "una",
    "uno",
    "los",
    "las",
    "estoy",
    "estamos",
    "porque",
    "como",
}


def _common_word_hits(text: str, markers: set[str]) -> int:
    return sum(1 for token in _RE_LATIN_WORD.findall(text.lower()) if token in markers)


def detect_lang(text: str) -> Optional[str]:
    """
    Lightweight heuristic language detector.
    Returns a supported non-auto language code or None if the text is too short / ambiguous.

    Confidence threshold:
    - Japanese: at least 1 kana character
    - Korean / Chinese / Vietnamese: at least 2 marker characters
    - French / Spanish: at least 1 accented marker or 3 common word hits
    - English fallback: at least 5 plain-ASCII letters
    """
    if not text or len(text.strip()) < 3:
        return None

    ja_hits = len(_RE_JAPANESE_KANA.findall(text))
    zh_hits = len(_RE_CJK_HAN.findall(text))
    ko_hits = len(_RE_KOREAN.findall(text))
    vi_hits = len(_RE_VIETNAMESE.findall(text))
    fr_hits = len(_RE_FRENCH_MARKERS.findall(text))
    es_hits = len(_RE_SPANISH_MARKERS.findall(text))

    if ja_hits >= 1:
        return "ja"
    if ko_hits >= 2:
        return "ko"
    if vi_hits >= 2:
        return "vi"
    if zh_hits >= 2:
        return "zh"
    if fr_hits >= 1 or _common_word_hits(text, _FRENCH_COMMON_WORDS) >= 3:
        return "fr"
    if es_hits >= 1 or _common_word_hits(text, _SPANISH_COMMON_WORDS) >= 3:
        return "es"

    # English fallback: mostly ASCII alpha characters
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    if ascii_alpha >= 5:
        return "en"

    return None  # uncertain


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def resolve_tgt(detected_src: str, requested_tgt: str) -> str:
    """
    Return the effective target language.
    - If tgt is explicit (not "auto"), honor it always.
    - If tgt is "auto", use DEFAULT_TGT for the detected src.
    """
    if requested_tgt != "auto":
        return requested_tgt
    return DEFAULT_TGT.get(detected_src, "en")


# ---------------------------------------------------------------------------
# Instruction builder
# ---------------------------------------------------------------------------

# Tone note for Japanese output
_JA_TONE = "丁寧すぎないが失礼でもない自然な日本語で翻訳してください。"


def _auto_detect_routing_policy() -> str:
    return " ".join(
        f"If the speaker uses {LANG_NAMES[src]}, output ONLY the {LANG_NAMES[DEFAULT_TGT[src]]} translation."
        for src in PLATFORM_SUPPORTED_LANGS
    )


def build_instructions(src: str, tgt: str) -> str:
    """
    Build the session instruction string for the given src/tgt pair.
    src/tgt may be "auto" or a specific lang code.
    """
    return _build_language_instructions(src, tgt) + " " + _NOT_AN_ASSISTANT + TRANSLATION_ENGINE_NO_SELF_SPEECH_POLICY


_NOT_AN_ASSISTANT = (
    "You are a translation engine, not an assistant: the user's words are addressed to other people, never to you. "
)


def _build_language_instructions(src: str, tgt: str) -> str:
    if src == "auto" and tgt == "auto":
        return (
            "You are a live interpreter across Vietnamese, English, Japanese, Chinese, Korean, French, and Spanish. "
            "Detect the language the user spoke. "
            + _auto_detect_routing_policy()
            + " "
            + build_technical_translation_policy()
            + "Output the translation text only. No explanations, no labels, no commentary."
        )

    if src == "auto":
        # tgt is fixed
        tgt_name = LANG_NAMES.get(tgt, tgt)
        return (
            f"You are a live interpreter. Detect the language the user spoke "
            f"and translate it to {tgt_name}. "
            + build_technical_translation_policy()
            + (_JA_TONE if tgt == "ja" else "")
            + "Output the translation text only. No explanations, no labels, no commentary."
        )

    src_name = LANG_NAMES.get(src, src)

    if tgt == "auto":
        # Derive default tgt from src
        effective_tgt = DEFAULT_TGT.get(src, "en")
        tgt_name = LANG_NAMES.get(effective_tgt, effective_tgt)
    else:
        tgt_name = LANG_NAMES.get(tgt, tgt)

    tone = _JA_TONE if (tgt == "ja" or (tgt == "auto" and DEFAULT_TGT.get(src) == "ja")) else ""

    return (
        f"You are a live interpreter from {src_name} to {tgt_name}. "
        f"The user will always speak {src_name}. "
        + build_technical_translation_policy()
        + f"Output ONLY the {tgt_name} translation. {tone}"
        + "No explanations, no labels, no commentary."
    )


# ---------------------------------------------------------------------------
# Pair validation
# ---------------------------------------------------------------------------

def parse_pairs(pairs_str: str) -> set[frozenset[str]]:
    """
    Parse a pairs string like "vi<->en,zh<->ko,fr<->es"
    into a set of frozensets for O(1) lookup.
    Returns empty set if pairs_str is empty (means "allow all").
    """
    if not pairs_str.strip():
        return set()
    result = set()
    for part in pairs_str.split(","):
        part = part.strip()
        if "<->" in part:
            a, b = part.split("<->", 1)
            result.add(frozenset({a.strip(), b.strip()}))
    return result


def pair_allowed(src: str, tgt: str, allowed_pairs: set[frozenset[str]]) -> bool:
    """Return True if the src<->tgt pair is in the allowed set (or set is empty = all allowed)."""
    if not allowed_pairs:
        return True
    return frozenset({src, tgt}) in allowed_pairs
