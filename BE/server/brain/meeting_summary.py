from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from server.brain.prompts.language import LANG_NAMES


logger = logging.getLogger(__name__)

DEFAULT_MEETING_SUMMARY_MODEL = "gpt-4o-mini"
MEETING_SUMMARY_TEMPERATURE = 0.1
MEETING_SUMMARY_MAX_TOKENS = 3500


async def generate_meeting_summary(
    *,
    source: Dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MEETING_SUMMARY_MODEL,
    summary_language: str = "en",
    summary_type: str = "final",
) -> Dict[str, Any]:
    """Generate a grounded meeting recap package from archived or live room data."""
    import openai

    summary_language_name = LANG_NAMES.get(summary_language, summary_language)
    system_prompt = _build_system_prompt(
        summary_language_name,
        summary_language=summary_language,
        summary_type=summary_type,
    )
    user_prompt = _build_user_prompt(source, summary_type=summary_type)

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


def _build_system_prompt(
    summary_language_name: str,
    *,
    summary_language: str,
    summary_type: str,
) -> str:
    summary_label = "live checkpoint" if summary_type == "interim" else "post-meeting final"
    return (
        f"You create {summary_label} meeting recap packages for admins and participants. "
        f"Target language: {summary_language} ({summary_language_name}). "
        f"Write the summary in {summary_language_name}. "
        f"Do not default to English unless target language is English. "
        "All generated human-readable values must use the same target language, "
        "including the whole-meeting summary paragraph, key points, decisions, "
        "action items, risks or blockers, open questions, next steps, and participant summaries. "
        "Keep the JSON keys exactly as requested, but do not use English for "
        "the generated content unless the target language is English. "
        "If the source transcript contains multiple languages, still summarize "
        f"all grounded content in {summary_language_name}. "
        "Preserve technical terms, proper nouns, product names, module names, API paths, "
        "database names, code identifiers, numbers, dates, and acronyms exactly as they appear "
        "when translating surrounding prose. Examples include API, Docker, Redis, k8s, CI/CD, "
        "endpoint, database, room_id, and module names. "
        "Use only the provided room metadata, participant records, transcript lines, "
        "BRSE relay lines, translated transcript lines, and chat messages. "
        "Treat source transcript lines as primary evidence; relay and translated lines "
        "may help understand multilingual content but must not be double-counted as "
        "separate facts when they represent the same utterance. "
        "Do not infer, guess, or add facts that are not present in the source data. "
        "Be conservative. Do not invent decisions, owners, deadlines, risks, causes, "
        "or next steps. If a decision or action item is only ambiguous, implied, "
        "or unsupported by explicit source text, leave it out. "
        "Do not attribute a point to a participant unless the provided participant "
        "records and messages support that attribution. "
        "Do not write generic filler such as 'the team discussed the project and next steps'. "
        "Each non-empty item must name the actual topic, request, decision, issue, component, "
        "or follow-up found in the source. "
        "For a live checkpoint summary, describe only the meeting content available "
        "so far and do not imply that the meeting has ended; action_items and "
        "decisions may be empty. "
        "For a final summary, summarize the completed meeting content. "
        "If the data is too thin, say that there was not enough meeting content to "
        "summarize and keep structured lists empty. "
        "Return only valid JSON with exactly these keys: "
        "summary_text, key_points, decisions, action_items, action_item_details, "
        "risks_blockers, open_questions, next_steps, participant_highlights. "
        "summary_text is a concise but complete whole-meeting paragraph of 2 to 4 sentences. "
        "It must mention the concrete main topics and outcomes when available. "
        "key_points is an array of specific main discussion points, requirements, proposals, "
        "or technical details; not follow-up tasks. "
        "decisions is an array of strings for clearly agreed decisions only. "
        "action_items is an array of strings for explicit follow-up tasks only and must mirror "
        "the text values in action_item_details for backward compatibility. "
        "action_item_details is an array of objects with keys text, owner, due. "
        "Use owner and due only when explicitly stated; otherwise set them to null. "
        "risks_blockers is an array of explicit blockers, risks, issues, constraints, or failures. "
        "open_questions is an array of explicit unresolved questions or decisions still pending. "
        "next_steps is an array of explicit follow-ups, review steps, or checkpoints; keep it empty "
        "when no next step is grounded in the source. "
        "participant_highlights is an array of objects with keys participant_id, "
        "display_name, summary. Use null for unknown participant_id or display_name. "
        "For any array, return [] when the source does not provide grounded content for that section."
    )


def _build_user_prompt(source: Dict[str, Any], *, summary_type: str) -> str:
    compact_source = {
        "room": source.get("room") or {},
        "participants": source.get("participants") or [],
        "summary_type": summary_type,
        "source_window": source.get("source_window") or {},
        "source_stats": source.get("source_stats") or {},
        "messages": source.get("messages") or [],
    }
    return (
        f"Create a grounded {summary_type} meeting recap package from this room data.\n"
        "Remember: no source support means no claim; unsupported actions, decisions, owners, deadlines, "
        "blockers, open questions, and next steps must be omitted. If source_stats.truncated is true, "
        "summarize only the provided sampled records and do not infer missing gaps.\n\n"
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
    key_points = _clean_string_list(payload.get("key_points"))
    if not key_points:
        key_points = _clean_string_list(payload.get("highlights"))

    participant_highlights = _clean_participant_highlights(
        payload.get("participant_highlights")
    )
    if not participant_highlights:
        participant_highlights = _clean_participant_highlights(
            payload.get("participant_summary")
        )

    action_item_details = _clean_action_item_details(
        payload.get("action_item_details") or payload.get("action_items")
    )
    action_items = _clean_action_item_texts(payload.get("action_items"))
    if not action_items:
        action_items = [item["text"] for item in action_item_details if item.get("text")]

    return {
        "summary_text": _clean_string(payload.get("summary_text")),
        "key_points": key_points,
        "highlights": list(key_points),
        "decisions": _clean_string_list(payload.get("decisions")),
        "action_items": action_items,
        "action_item_details": action_item_details,
        "risks_blockers": _clean_first_string_list(
            payload,
            "risks_blockers",
            "blockers",
            "risks",
            "issues",
        ),
        "open_questions": _clean_first_string_list(
            payload,
            "open_questions",
            "unanswered_questions",
            "questions",
        ),
        "next_steps": _clean_first_string_list(
            payload,
            "next_steps",
            "follow_ups",
            "follow_up",
        ),
        "participant_highlights": participant_highlights,
        "participant_summary": list(participant_highlights),
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


def _clean_first_string_list(payload: Dict[str, Any], *keys: str) -> List[str]:
    for key in keys:
        result = _clean_string_list(payload.get(key))
        if result:
            return result
    return []


def _clean_action_item_texts(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _clean_string(item.get("text"))
        else:
            text = ""
        if text:
            result.append(text)
    return result


def _clean_action_item_details(value: Any) -> List[Dict[str, Optional[str]]]:
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


def _clean_participant_highlights(value: Any) -> List[Dict[str, Optional[str]]]:
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
