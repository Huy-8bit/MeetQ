from __future__ import annotations

import logging
from typing import Optional

from server.brain.prompts.language import LANG_NAMES
from server.brain.prompts.technical_terms import build_technical_translation_policy
from server.brain.prompts.translation_engine import (
    build_text_translation_system_prompt,
    wrap_source_text,
)
from server.brain.realtime.source_policy import (
    source_text_is_translatable,
    validated_translation,
)

logger = logging.getLogger(__name__)

_RUNTIME_TEXT_TRANSLATE_MODEL = "gpt-4o-mini"
_RUNTIME_TEXT_TRANSLATE_TEMPERATURE = 0.2


async def translate_caption_text(
    *,
    text: str,
    src_lang: str,
    tgt_lang: str,
    api_key: str,
    model: str = _RUNTIME_TEXT_TRANSLATE_MODEL,
) -> Optional[str]:
    source_text = (text or "").strip()
    if not source_text_is_translatable(source_text):
        return None
    if src_lang == tgt_lang:
        return source_text

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            temperature=_RUNTIME_TEXT_TRANSLATE_TEMPERATURE,
            messages=[
                {"role": "system", "content": _build_caption_translation_prompt(src_lang, tgt_lang)},
                {"role": "user", "content": wrap_source_text(source_text)},
            ],
        )
        translated = (response.choices[0].message.content or "").strip()
        if translated:
            return validated_translation(
                translated,
                source_text=source_text,
                context="caption",
                src_lang=src_lang,
                tgt_lang=tgt_lang,
            )
    except Exception as exc:
        logger.warning(
            "runtime caption translation failed: src=%s tgt=%s error=%s",
            src_lang,
            tgt_lang,
            exc,
        )
    return None


def _build_caption_translation_prompt(src_lang: str, tgt_lang: str) -> str:
    src_name = LANG_NAMES.get(src_lang, src_lang)
    tgt_name = LANG_NAMES.get(tgt_lang, tgt_lang)
    return build_text_translation_system_prompt(
        src_name,
        tgt_name,
        medium="validated live speech transcript shown as a meeting caption",
        extra_policy=build_technical_translation_policy(),
    )
