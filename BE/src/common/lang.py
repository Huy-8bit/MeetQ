"""
src/common/lang.py
Language constants, heuristic detection, and instruction building.

Supported language codes: "auto", "vi", "en", "ja"
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------

SUPPORTED_LANGS = {"auto", "vi", "en", "ja"}

LANG_NAMES = {
    "vi": "Vietnamese",
    "en": "English",
    "ja": "Japanese",
    "auto": "auto",
}

# Default target when src is detected (auto-routing table)
DEFAULT_TGT: dict[str, str] = {
    "vi": "en",
    "en": "vi",
    "ja": "en",
}

# ---------------------------------------------------------------------------
# Heuristic language detector
# ---------------------------------------------------------------------------

# Japanese: Hiragana U+3040–U+309F, Katakana U+30A0–U+30FF, CJK U+4E00–U+9FFF
_RE_JAPANESE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")

# Vietnamese: letters with specific diacritics not present in standard Latin
# Key markers: ắ ặ ầ ề ộ ử ỳ ơ ư đ and their case variants
_RE_VIETNAMESE = re.compile(
    r"[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
    r"ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
)


def detect_lang(text: str) -> Optional[str]:
    """
    Lightweight heuristic language detector.
    Returns "ja", "vi", "en", or None if the text is too short / ambiguous.

    Confidence threshold: at least 2 marker characters for ja/vi,
    or at least 5 plain-ASCII words for en fallback.
    """
    if not text or len(text.strip()) < 3:
        return None

    ja_hits = len(_RE_JAPANESE.findall(text))
    vi_hits = len(_RE_VIETNAMESE.findall(text))

    if ja_hits >= 2:
        return "ja"
    if vi_hits >= 2:
        return "vi"

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

def build_instructions(src: str, tgt: str) -> str:
    """
    Build the session instruction string for the given src/tgt pair.
    src/tgt may be "auto" or a specific lang code.
    """
    if src == "auto" and tgt == "auto":
        return (
            "You are a live interpreter between Vietnamese, English, and Japanese. "
            "Detect the language the user spoke. "
            "If Vietnamese, output ONLY the English translation. "
            "If English, output ONLY the Vietnamese translation. "
            "If Japanese, output ONLY the English translation. "
            "Output the translation text only. No explanations, no labels, no commentary."
        )

    if src == "auto":
        # tgt is fixed
        tgt_name = LANG_NAMES[tgt]
        return (
            f"You are a live interpreter. Detect the language the user spoke "
            f"and translate it to {tgt_name}. "
            + (_JA_TONE if tgt == "ja" else "")
            + "Output the translation text only. No explanations, no labels, no commentary."
        )

    src_name = LANG_NAMES[src]

    if tgt == "auto":
        # Derive default tgt from src
        effective_tgt = DEFAULT_TGT.get(src, "en")
        tgt_name = LANG_NAMES[effective_tgt]
    else:
        tgt_name = LANG_NAMES[tgt]

    tone = _JA_TONE if (tgt == "ja" or (tgt == "auto" and DEFAULT_TGT.get(src) == "ja")) else ""

    return (
        f"You are a live interpreter from {src_name} to {tgt_name}. "
        f"The user will always speak {src_name}. "
        f"Output ONLY the {tgt_name} translation. {tone}"
        "No explanations, no labels, no commentary."
    )


# ---------------------------------------------------------------------------
# Pair validation
# ---------------------------------------------------------------------------

def parse_pairs(pairs_str: str) -> set[frozenset[str]]:
    """
    Parse a pairs string like "vi<->en,ja<->en,vi<->ja"
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
