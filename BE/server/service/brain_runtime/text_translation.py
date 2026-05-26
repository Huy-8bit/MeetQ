from __future__ import annotations

import logging
from typing import Optional

from server.brain.prompts.language import LANG_NAMES
from server.brain.prompts.technical_terms import build_technical_translation_policy

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
    if not source_text:
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
                {"role": "user", "content": source_text},
            ],
        )
        translated = response.choices[0].message.content
        if translated:
            return translated.strip()
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
    return (
        f"You are a live meeting caption translator from {src_name} to {tgt_name}. "
        "Translate the validated source transcript faithfully and naturally for meeting captions. "
        "Preserve names, numbers, code terms, product names, dates, constraints, uncertainty, and speaker intent. "
        + build_technical_translation_policy()
        + f"Output only the {tgt_name} translation. "
        "No labels, no explanations, no markdown, no commentary."
    )
