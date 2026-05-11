"""
Chat message translation helper.

Translates a single text string from src_lang to tgt_lang using the OpenAI
chat completions API (not realtime — deterministic, text-only, per-message).

Strategy: given the room language configuration and the sender's language,
derive zero or more cross-language targets. A one-language room returns no
translation targets; a two-language room preserves the legacy single "other
language" behavior; a multi-language room translates to each configured
non-source language.

This is intentionally separate from the audio relay path (realtime API).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from server.brain.prompts.language import LANG_NAMES
from server.brain.prompts.technical_terms import build_technical_translation_policy

logger = logging.getLogger(__name__)

_CHAT_TRANSLATE_MODEL = "gpt-4o-mini"
_CHAT_TRANSLATE_TEMPERATURE = 0.2


def resolve_chat_target_language(
    sender_language: str,
    meeting_languages: List[str],
) -> Optional[str]:
    """
    Return the first target language for legacy callers.

    Prefer resolve_chat_target_languages for new room-language-aware paths.
    """
    targets = resolve_chat_target_languages(sender_language, meeting_languages)
    return targets[0] if targets else None


def resolve_chat_target_languages(
    sender_language: str,
    room_languages: List[str],
) -> List[str]:
    """
    Return cross-language chat translation targets for the configured room.

    Participant.language is the source language for the message. room_languages
    is the room-level supported language list. Same-language rooms return an
    empty target list because no translation is needed.
    """
    normalized: List[str] = []
    for language in room_languages:
        if language not in normalized:
            normalized.append(language)
    if sender_language not in normalized:
        return []
    return [language for language in normalized if language != sender_language]


async def translate_chat_message(
    text: str,
    src_lang: str,
    tgt_lang: str,
    api_key: str,
    model: str = _CHAT_TRANSLATE_MODEL,
) -> Optional[str]:
    """
    Translate `text` from src_lang to tgt_lang.

    Returns the translated string on success, None on any failure (caller must
    treat None as a graceful degradation and keep the original message).
    """
    if src_lang == tgt_lang:
        return text

    system_prompt = _build_chat_translation_prompt(src_lang, tgt_lang)

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            temperature=_CHAT_TRANSLATE_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )
        result = resp.choices[0].message.content
        if result:
            return result.strip()
        return None
    except Exception as exc:
        logger.warning(
            "chat translation failed: src=%s tgt=%s error=%s",
            src_lang,
            tgt_lang,
            exc,
        )
        return None


def _build_chat_translation_prompt(src_lang: str, tgt_lang: str) -> str:
    src_name = LANG_NAMES.get(src_lang, src_lang)
    tgt_name = LANG_NAMES.get(tgt_lang, tgt_lang)
    return (
        f"You are a professional translator from {src_name} to {tgt_name}. "
        f"Translate the following chat message accurately and naturally. "
        + build_technical_translation_policy()
        + f"Output ONLY the {tgt_name} translation. "
        + "No explanations, no labels, no commentary."
    )
