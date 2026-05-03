"""
Chat message translation helper.

Translates a single text string from src_lang to tgt_lang using the OpenAI
chat completions API (not realtime — deterministic, text-only, per-message).

Strategy: given a room language pair (e.g. ["vi", "en"]) and the sender's
language, derive the single target language as the other language in the pair.
For a vi-en room with a vi sender -> translate to en, and vice versa.

This is intentionally separate from the audio relay path (realtime API).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from server.brain.prompts.language import LANG_NAMES, build_instructions

logger = logging.getLogger(__name__)

_CHAT_TRANSLATE_MODEL = "gpt-4o-mini"
_CHAT_TRANSLATE_TEMPERATURE = 0.2


def resolve_chat_target_language(
    sender_language: str,
    meeting_languages: List[str],
) -> Optional[str]:
    """
    Return the target language for a chat translation given the room pair.

    For a 2-language room, the target is the language in meeting_languages that
    is NOT the sender's language.  Returns None if sender language is not in the
    pair or the pair has fewer than 2 elements.
    """
    if len(meeting_languages) < 2:
        return None
    others = [lang for lang in meeting_languages if lang != sender_language]
    return others[0] if others else None


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
        f"Output ONLY the {tgt_name} translation. "
        "No explanations, no labels, no commentary."
    )
