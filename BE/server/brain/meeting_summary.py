from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from server.brain.prompts.language import LANG_NAMES


logger = logging.getLogger(__name__)

DEFAULT_MEETING_SUMMARY_MODEL = "gpt-4o-mini"
MEETING_SUMMARY_TEMPERATURE = 0.1
MEETING_SUMMARY_MAX_TOKENS = 1800


async def generate_meeting_summary(
    *,
    source: Dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MEETING_SUMMARY_MODEL,
    summary_language: str = "en",
) -> Dict[str, Any]:
    """Generate a grounded post-meeting summary from archived room data."""
    import openai

    summary_language_name = LANG_NAMES.get(summary_language, summary_language)
    system_prompt = _build_system_prompt(summary_language_name)
    user_prompt = _build_user_prompt(source)

    client = openai.AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        temperature=MEETING_SUMMARY_TEMPERATURE,
        max_tokens=MEETING_SUMMARY_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content or ""
    parsed = _parse_summary_json(content)
    return _normalize_summary_payload(parsed)


def _build_system_prompt(summary_language_name: str) -> str:
    return (
        "You create post-meeting summaries for admins and meeting participants. "
        f"Write the entire output in {summary_language_name}. "
        "Use only the provided room metadata, participant records, transcript lines, "
        "BRSE relay lines, translated transcript lines, and chat messages. "
        "Treat source transcript lines as primary evidence; relay and translated lines "
        "may help understand multilingual content but must not be double-counted as "
        "separate facts when they represent the same utterance. "
        "Do not infer, guess, or add facts that are not present in the source data. "
        "Do not invent decisions, owners, deadlines, risks, causes, or next steps. "
        "If a decision or action item is only ambiguous or implied, leave it out. "
        "If the data is too thin, say that there was not enough meeting content to "
        "summarize and keep structured lists empty. "
        "Return only valid JSON with exactly these keys: "
        "summary_text, highlights, decisions, action_items, participant_summary. "
        "summary_text is a concise paragraph. highlights and decisions are arrays "
        "of strings. action_items is an array of objects with keys text, owner, due. "
        "participant_summary is an array of objects with keys participant_id, "
        "display_name, summary. Use null for unknown owner, due, or participant_id."
    )


def _build_user_prompt(source: Dict[str, Any]) -> str:
    compact_source = {
        "room": source.get("room") or {},
        "participants": source.get("participants") or [],
        "source_stats": source.get("source_stats") or {},
        "messages": source.get("messages") or [],
    }
    return (
        "Create a grounded post-meeting summary from this archived room data.\n"
        "Remember: no source support means no claim.\n\n"
        f"{json.dumps(compact_source, ensure_ascii=False, separators=(',', ':'))}"
    )


def _parse_summary_json(content: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        logger.warning("meeting summary model returned invalid JSON")
    raise ValueError("meeting summary model did not return a JSON object")


def _normalize_summary_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "summary_text": _clean_string(payload.get("summary_text")),
        "highlights": _clean_string_list(payload.get("highlights")),
        "decisions": _clean_string_list(payload.get("decisions")),
        "action_items": _clean_action_items(payload.get("action_items")),
        "participant_summary": _clean_participant_summary(payload.get("participant_summary")),
    }


def _clean_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _clean_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _clean_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        normalized = _clean_string(item)
        if normalized:
            result.append(normalized)
    return result


def _clean_action_items(value: Any) -> List[Dict[str, Optional[str]]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Optional[str]]] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            owner = None
            due = None
        elif isinstance(item, dict):
            text = _clean_string(item.get("text"))
            owner = _clean_optional_string(item.get("owner"))
            due = _clean_optional_string(item.get("due"))
        else:
            continue
        if text:
            result.append({"text": text, "owner": owner, "due": due})
    return result


def _clean_participant_summary(value: Any) -> List[Dict[str, Optional[str]]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Optional[str]]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        summary = _clean_string(item.get("summary"))
        if not summary:
            continue
        result.append(
            {
                "participant_id": _clean_optional_string(item.get("participant_id")),
                "display_name": _clean_optional_string(item.get("display_name")),
                "summary": summary,
            }
        )
    return result
