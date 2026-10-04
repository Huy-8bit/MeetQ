"""Pure derivations for the admin portal (no I/O; unit tested).

Everything here works on documents that already exist (room state, relay
traces, summaries). Nothing invents numbers: percentiles need a minimum sample
size and health is ``unknown`` without recent traffic.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from server.meeting_modes import (
    BRSE_MODE_SILENT_SUMMARY,
    BRSE_OUTPUT_MODE_TEXT_ONLY,
)

# ── Shared vocabularies ─────────────────────────────────────────────────────

AI_MODE_OFF = "off"
AI_MODE_CAPTIONS = "captions"
AI_MODE_VOICE_TEXT = "voice_text"
AI_MODE_TEXT_ONLY = "text_only"
AI_MODE_SUMMARY_CAPTURE = "summary_capture"
AI_MODES = (AI_MODE_VOICE_TEXT, AI_MODE_TEXT_ONLY, AI_MODE_CAPTIONS, AI_MODE_SUMMARY_CAPTURE, AI_MODE_OFF)

ROOM_STATUS_LIVE = "live"
ROOM_STATUS_EMPTY = "empty"
ROOM_STATUS_ERROR = "error"
ROOM_STATUS_EXPIRED = "expired"
ROOM_STATUSES = (ROOM_STATUS_LIVE, ROOM_STATUS_EMPTY, ROOM_STATUS_ERROR, ROOM_STATUS_EXPIRED)

MEETING_STATUS_LIVE = "live"
MEETING_STATUS_ENDED = "ended"
MEETING_STATUSES = (MEETING_STATUS_LIVE, MEETING_STATUS_ENDED)

AI_STATE_RELAY_OFF = "relay_off"
AI_STATE_IDLE = "idle"
# Highest priority first: the room-level BRSE state is the most "active" speaker state.
AI_STATE_PRIORITY = (
    "error",
    "playing",
    "translating",
    "queued",
    "capturing",
    "blocked_due_to_overlap",
    "idle",
)

# A room is flagged "error" when it had an error-severity AI event this recently.
ROOM_ERROR_WINDOW_SECONDS = 120

# Minimum samples before a percentile is reported.
PERCENTILE_MIN_SAMPLES = {50: 5, 95: 20, 99: 100}

# Health thresholds (last 15 minutes of traffic).
HEALTH_WINDOW_MINUTES = 15
HEALTH_MIN_SAMPLES = 4
HEALTH_DEGRADED_ERROR_RATE = 0.10
HEALTH_DOWN_ERROR_RATE = 0.50
STAGE_P95_THRESHOLDS_MS = {
    "stt": 2500,
    "translation": 3000,
    "voice": 3500,
    "delivery": 6000,
}

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_DOWN = "down"
HEALTH_UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── Room / AI mode / state ─────────────────────────────────────────────────

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def room_languages_of(room: Any) -> List[str]:
    languages = _get(room, "room_languages") or _get(room, "meeting_languages") or []
    return [str(language) for language in languages]


def ai_mode_of(room: Any) -> str:
    """User-facing AI relay mode, consistent with docs/system-design/03 (R-20..R-24)."""
    if not _get(room, "brse_enabled"):
        return AI_MODE_OFF
    if _get(room, "brse_mode") == BRSE_MODE_SILENT_SUMMARY:
        return AI_MODE_SUMMARY_CAPTURE
    language_count = len(room_languages_of(room))
    if language_count == 1:
        return AI_MODE_CAPTIONS
    if language_count >= 3:
        return AI_MODE_TEXT_ONLY
    if _get(room, "brse_output_mode") == BRSE_OUTPUT_MODE_TEXT_ONLY:
        return AI_MODE_TEXT_ONLY
    return AI_MODE_VOICE_TEXT


def is_human(participant: Any) -> bool:
    return not _get(participant, "is_virtual") and _get(participant, "kind") != "virtual_brse"


def online_humans(participants: Iterable[Any]) -> List[Any]:
    return [
        participant
        for participant in participants
        if is_human(participant)
        and _get(participant, "status") in ("connected", "reconnecting", "joining")
        and not _get(participant, "left_at")
    ]


def aggregate_ai_state(brse_enabled: bool, statuses: Sequence[Dict[str, Any]]) -> Optional[str]:
    if not brse_enabled:
        return AI_STATE_RELAY_OFF
    present = {str(entry.get("status")) for entry in statuses if entry.get("status")}
    for state in AI_STATE_PRIORITY:
        if state in present:
            return state
    return AI_STATE_IDLE if not statuses else None


def room_status(
    *,
    expires_at: Any,
    online_human_count: int,
    ai_state: Optional[str],
    last_error_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    now = now or utc_now()
    expires = parse_dt(expires_at)
    if expires is not None and now >= expires:
        return ROOM_STATUS_EXPIRED
    if ai_state == "error" or (
        last_error_at is not None
        and (now - last_error_at).total_seconds() <= ROOM_ERROR_WINDOW_SECONDS
    ):
        return ROOM_STATUS_ERROR
    if online_human_count <= 0:
        return ROOM_STATUS_EMPTY
    return ROOM_STATUS_LIVE


def seconds_left(expires_at: Any, now: Optional[datetime] = None) -> Optional[int]:
    expires = parse_dt(expires_at)
    if expires is None:
        return None
    return max(0, int((expires - (now or utc_now())).total_seconds()))


def meeting_status(room_doc: Dict[str, Any], now: Optional[datetime] = None) -> str:
    now = now or utc_now()
    status_summary = room_doc.get("status_summary") or {}
    if status_summary.get("terminal"):
        return MEETING_STATUS_ENDED
    expires = parse_dt(room_doc.get("expires_at_dt") or room_doc.get("expires_at"))
    if expires is not None and now >= expires:
        return MEETING_STATUS_ENDED
    return MEETING_STATUS_LIVE


def meeting_end_reason(room_doc: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    status_summary = room_doc.get("status_summary") or {}
    if status_summary.get("terminal"):
        return str(status_summary.get("state") or room_doc.get("state") or "ended")
    if meeting_status(room_doc, now) == MEETING_STATUS_ENDED:
        return "expired"
    return None


# ── Latency / stage statistics ─────────────────────────────────────────────

def percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def latency_summary(values: Iterable[Any]) -> Dict[str, Optional[float]]:
    samples = [float(value) for value in values if isinstance(value, (int, float))]
    summary: Dict[str, Optional[float]] = {
        "samples": len(samples),
        "avg": round(sum(samples) / len(samples)) if samples else None,
    }
    for q, minimum in PERCENTILE_MIN_SAMPLES.items():
        value = percentile(samples, q) if len(samples) >= minimum else None
        summary[f"p{q}"] = round(value) if value is not None else None
    return summary


def _rate(part: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return round(part / total, 4)


def _stage(requests: int, success: int, errors: int, latencies: List[Any], breakdown: Counter) -> Dict[str, Any]:
    return {
        "requests": requests,
        "success": success,
        "errors": errors,
        "success_rate": _rate(success, requests),
        "error_rate": _rate(errors, requests),
        "latency": latency_summary(latencies),
        "error_breakdown": [
            {"reason": reason, "count": count}
            for reason, count in breakdown.most_common(8)
        ],
    }


def _metric(doc: Dict[str, Any], key: str) -> Optional[float]:
    value = (doc.get("metrics") or {}).get(key)
    return value if isinstance(value, (int, float)) else None


def compute_stage_stats(traces: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-stage request/success/error counts and latency from relay traces.

    * stt — speech commit -> transcript (gpt-4o-transcribe inside the realtime session)
    * translation — relay request -> first translated text (realtime) or caption text
    * voice — relay request -> first AI voice audio (same realtime response)
    * delivery — end of speech -> final relay text published (approved relays only)
    """
    stt_req = stt_ok = stt_err = 0
    stt_lat: List[Any] = []
    stt_breakdown: Counter = Counter()

    tr_req = tr_ok = tr_err = 0
    tr_lat: List[Any] = []
    tr_breakdown: Counter = Counter()

    voice_req = voice_ok = voice_err = 0
    voice_lat: List[Any] = []
    voice_breakdown: Counter = Counter()

    del_req = del_ok = del_err = 0
    del_lat: List[Any] = []
    del_breakdown: Counter = Counter()

    for doc in traces:
        outcome = doc.get("outcome")
        reason = doc.get("reason") or outcome or "unknown"
        if outcome == "superseded":
            continue

        stt_ms = _metric(doc, "stt_ms")
        if outcome == "stt_failed":
            stt_req += 1
            stt_err += 1
            stt_breakdown[reason] += 1
        elif outcome == "stt_empty":
            stt_req += 1
            stt_ok += 1
        elif stt_ms is not None:
            stt_req += 1
            stt_ok += 1
            stt_lat.append(stt_ms)

        if doc.get("translation_requested"):
            tr_req += 1
            first_text = _metric(doc, "first_text_ms")
            if outcome == "delivered" or (outcome != "output_rejected" and first_text is not None):
                tr_ok += 1
            else:
                tr_err += 1
                tr_breakdown[doc.get("output_rejected_reason") or reason] += 1
            if first_text is not None:
                tr_lat.append(first_text)
        for caption in doc.get("captions") or []:
            tr_req += 1
            if caption.get("ok"):
                tr_ok += 1
                tr_lat.append(caption.get("latency_ms"))
            else:
                tr_err += 1
                tr_breakdown["caption_translation_failed"] += 1

        if doc.get("audio_requested") and outcome == "delivered":
            voice_req += 1
            if doc.get("audio_delivered"):
                voice_ok += 1
            else:
                voice_err += 1
                voice_breakdown["no_audio_for_delivered_relay"] += 1
            first_audio = _metric(doc, "first_audio_ms")
            if first_audio is not None:
                voice_lat.append(first_audio)

        if doc.get("policy_decision") == "publish" or outcome == "caption_delivered" or (
            doc.get("captions") and outcome == "relay_dropped"
        ):
            del_req += 1
            if outcome in ("delivered", "caption_delivered"):
                del_ok += 1
                total = _metric(doc, "total_ms")
                if total is not None:
                    del_lat.append(total)
            else:
                del_err += 1
                del_breakdown[reason] += 1

    return {
        "stt": _stage(stt_req, stt_ok, stt_err, stt_lat, stt_breakdown),
        "translation": _stage(tr_req, tr_ok, tr_err, tr_lat, tr_breakdown),
        "voice": _stage(voice_req, voice_ok, voice_err, voice_lat, voice_breakdown),
        "delivery": _stage(del_req, del_ok, del_err, del_lat, del_breakdown),
    }


def stage_health(stats: Dict[str, Any], stage: str, *, blocking_errors: int = 0) -> Dict[str, Any]:
    if blocking_errors > 0:
        return {
            "status": HEALTH_DOWN,
            "reason": f"{blocking_errors} realtime session failure(s) in the last {HEALTH_WINDOW_MINUTES} min",
        }
    requests = int(stats.get("requests") or 0)
    errors = int(stats.get("errors") or 0)
    if requests == 0:
        return {"status": HEALTH_UNKNOWN, "reason": f"No traffic in the last {HEALTH_WINDOW_MINUTES} min"}
    error_rate = errors / requests
    p95 = (stats.get("latency") or {}).get("p95")
    threshold = STAGE_P95_THRESHOLDS_MS.get(stage)
    if requests >= HEALTH_MIN_SAMPLES and error_rate >= HEALTH_DOWN_ERROR_RATE:
        return {"status": HEALTH_DOWN, "reason": f"{round(error_rate * 100)}% errors"}
    if (requests >= HEALTH_MIN_SAMPLES and error_rate >= HEALTH_DEGRADED_ERROR_RATE) or errors >= 2:
        return {"status": HEALTH_DEGRADED, "reason": f"{errors} error(s) of {requests}"}
    if p95 is not None and threshold is not None and p95 > threshold:
        return {"status": HEALTH_DEGRADED, "reason": f"p95 {int(p95)} ms > {threshold} ms"}
    return {"status": HEALTH_HEALTHY, "reason": f"{requests} request(s), {errors} error(s)"}


def summary_stats(summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Counter = Counter()
    latencies: List[float] = []
    by_type: Dict[str, Counter] = defaultdict(Counter)
    for doc in summaries:
        status = str(doc.get("status") or "unknown")
        counts[status] += 1
        by_type[str(doc.get("summary_type") or "final")][status] += 1
        if status == "completed":
            created = parse_dt(doc.get("created_at_dt") or doc.get("created_at"))
            generated = parse_dt(doc.get("generated_at_dt") or doc.get("generated_at"))
            if created and generated and generated >= created:
                latencies.append((generated - created).total_seconds() * 1000)
    total = sum(counts.values())
    return {
        "requests": total,
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "pending": counts.get("pending", 0),
        "failure_rate": _rate(counts.get("failed", 0), total),
        "latency": latency_summary(latencies),
        "by_type": {key: dict(value) for key, value in by_type.items()},
    }


def summary_health(stats: Dict[str, Any]) -> Dict[str, Any]:
    total = int(stats.get("requests") or 0)
    failed = int(stats.get("failed") or 0)
    if total == 0:
        return {"status": HEALTH_UNKNOWN, "reason": "No summaries in the last 24 h"}
    if failed >= 2 and failed / total >= HEALTH_DOWN_ERROR_RATE:
        return {"status": HEALTH_DOWN, "reason": f"{failed} of {total} failed"}
    if failed > 0:
        return {"status": HEALTH_DEGRADED, "reason": f"{failed} of {total} failed"}
    return {"status": HEALTH_HEALTHY, "reason": f"{total} generated"}


def language_pair_stats(traces: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"relays": 0, "delivered": 0, "errors": 0, "latencies": []}
    )

    for doc in traces:
        outcome = doc.get("outcome")
        if doc.get("policy_decision") == "publish" and doc.get("language_pair"):
            bucket = buckets[doc["language_pair"]]
            bucket["relays"] += 1
            if outcome == "delivered":
                bucket["delivered"] += 1
                total = _metric(doc, "total_ms")
                if total is not None:
                    bucket["latencies"].append(total)
            else:
                bucket["errors"] += 1
        src = doc.get("src_lang")
        for caption in doc.get("captions") or []:
            target = caption.get("target_lang")
            if not src or not target:
                continue
            bucket = buckets[f"{src}>{target}"]
            bucket["relays"] += 1
            if caption.get("ok"):
                bucket["delivered"] += 1
                if isinstance(caption.get("latency_ms"), (int, float)):
                    bucket["latencies"].append(caption["latency_ms"])
            else:
                bucket["errors"] += 1

    rows = []
    for pair, bucket in buckets.items():
        src, _, tgt = pair.partition(">")
        latency = latency_summary(bucket["latencies"])
        rows.append(
            {
                "pair": pair,
                "source_language": src,
                "target_language": tgt,
                "relays": bucket["relays"],
                "delivered": bucket["delivered"],
                "errors": bucket["errors"],
                "success_rate": _rate(bucket["delivered"], bucket["relays"]),
                "error_rate": _rate(bucket["errors"], bucket["relays"]),
                "avg_latency_ms": latency["avg"],
                "p95_latency_ms": latency["p95"],
                "latency_samples": latency["samples"],
            }
        )
    rows.sort(key=lambda row: row["relays"], reverse=True)
    return rows


# ── Relay timeline stages ─────────────────────────────────────────────────

def _stage_row(key: str, label: str, status: str, ms: Optional[float] = None, note: Optional[str] = None) -> Dict[str, Any]:
    return {"key": key, "label": label, "status": status, "ms": ms, "note": note}


def build_trace_stages(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Explain where an utterance went: STT -> validation -> policy -> translation -> voice -> delivery."""
    outcome = doc.get("outcome")
    reason = doc.get("reason")
    metrics = doc.get("metrics") or {}
    stages: List[Dict[str, Any]] = []

    if outcome == "stt_failed":
        stages.append(_stage_row("stt", "STT", "failed", note=reason))
        return stages
    if outcome == "stt_empty":
        stages.append(_stage_row("stt", "STT", "warning", note="No speech recognized"))
        return stages
    if outcome == "superseded":
        stages.append(_stage_row("stt", "STT", "skipped", note="Speaker resumed during the quality hold; fragment dropped"))
        return stages
    stages.append(_stage_row("stt", "STT", "ok", metrics.get("stt_ms")))

    if doc.get("source_accepted") is False or outcome == "source_rejected":
        stages.append(_stage_row("validation", "Validation", "failed", note=doc.get("source_reason") or reason))
        return stages
    stages.append(_stage_row("validation", "Validation", "ok"))

    policy = doc.get("policy_decision")
    captions = doc.get("captions") or []
    if policy == "source_only" and not captions:
        stages.append(_stage_row("policy", "Policy", "skipped", note=doc.get("policy_reason") or "No translation needed"))
        return stages
    if policy == "suppress":
        stages.append(_stage_row("policy", "Policy", "failed", note=doc.get("policy_reason") or reason))
        return stages
    if policy == "publish":
        stages.append(_stage_row("policy", "Policy", "ok", note=doc.get("relay_style")))

    if captions:
        for caption in captions:
            stages.append(
                _stage_row(
                    f"caption:{caption.get('target_lang')}",
                    f"Caption → {str(caption.get('target_lang') or '').upper()}",
                    "ok" if caption.get("ok") else "failed",
                    caption.get("latency_ms"),
                )
            )
    elif doc.get("translation_requested"):
        if metrics.get("queue_ms") is not None:
            stages.append(_stage_row("queue", "Queue", "ok", metrics.get("queue_ms")))
        if outcome == "output_rejected":
            stages.append(
                _stage_row("translation", "Translation", "failed", metrics.get("first_text_ms"), doc.get("output_rejected_reason") or reason)
            )
        elif metrics.get("first_text_ms") is not None:
            stages.append(_stage_row("translation", "Translation", "ok", metrics.get("first_text_ms")))
        else:
            stages.append(_stage_row("translation", "Translation", "failed", note="No translated text"))
        if doc.get("audio_requested"):
            if doc.get("audio_delivered"):
                stages.append(_stage_row("voice", "AI voice", "ok", metrics.get("first_audio_ms")))
            elif outcome == "delivered":
                stages.append(_stage_row("voice", "AI voice", "failed", note="No audio produced"))
            else:
                stages.append(_stage_row("voice", "AI voice", "skipped"))
    elif policy == "publish":
        stages.append(_stage_row("translation", "Translation", "skipped", note="Not started"))

    if outcome in ("delivered", "caption_delivered"):
        status = "warning" if reason == "partial_caption_failure" else "ok"
        stages.append(_stage_row("delivery", "Delivered", status, metrics.get("total_ms"), reason))
    elif outcome == "abandoned":
        stages.append(_stage_row("delivery", "Delivery", "skipped", note=reason))
    else:
        stages.append(_stage_row("delivery", "Delivery", "failed", metrics.get("age_ms"), reason))
    return stages


# ── Analytics ──────────────────────────────────────────────────────────────

LANGUAGE_LABELS = {
    "vi": "Vietnamese",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "fr": "French",
    "es": "Spanish",
}


def language_combo(languages: Sequence[str]) -> Dict[str, str]:
    ordered = sorted(set(languages))
    if not ordered:
        return {"key": "unknown", "label": "Unknown"}
    if len(ordered) == 1:
        return {"key": ordered[0], "label": f"{LANGUAGE_LABELS.get(ordered[0], ordered[0])} only"}
    if len(ordered) == 2:
        return {
            "key": "+".join(ordered),
            "label": " ⇄ ".join(LANGUAGE_LABELS.get(code, code) for code in ordered),
        }
    return {"key": "multi", "label": "3+ languages"}


def build_analytics(
    rooms: Sequence[Dict[str, Any]],
    *,
    range_start: datetime,
    range_end: datetime,
    tz_offset_minutes: int = 0,
) -> Dict[str, Any]:
    offset = timedelta(minutes=tz_offset_minutes)
    meetings = [room for room in rooms if int(room.get("participant_count_total") or 0) > 0]
    durations = [
        int(room["duration_seconds"])
        for room in meetings
        if isinstance(room.get("duration_seconds"), (int, float))
    ]
    participant_counts = [int(room.get("participant_count_total") or 0) for room in meetings]

    by_day: Counter = Counter()
    for room in meetings:
        created = parse_dt(room.get("created_at_dt") or room.get("created_at"))
        if created is not None:
            by_day[(created + offset).date().isoformat()] += 1
    days = []
    cursor = (range_start + offset).date()
    last_day = (range_end + offset).date()
    while cursor <= last_day and len(days) < 400:
        key = cursor.isoformat()
        days.append({"date": key, "meetings": by_day.get(key, 0)})
        cursor += timedelta(days=1)

    combos: Dict[str, Dict[str, Any]] = {}
    for room in meetings:
        combo = language_combo(room_languages_of(room))
        entry = combos.setdefault(combo["key"], {**combo, "count": 0})
        entry["count"] += 1

    modes: Counter = Counter(ai_mode_of(room) for room in meetings)

    def kind_count(room: Dict[str, Any], kind: str) -> int:
        return int((room.get("transcript_kind_counts") or {}).get(kind) or 0)

    def summary_completed(room: Dict[str, Any], summary_type: str) -> bool:
        entry = (room.get("meeting_summaries") or {}).get(summary_type) or {}
        return entry.get("status") == "completed"

    return {
        "totals": {
            "rooms_created": len(rooms),
            "meetings": len(meetings),
            "avg_duration_seconds": round(sum(durations) / len(durations)) if durations else None,
            "avg_participants": round(sum(participant_counts) / len(participant_counts), 1) if participant_counts else None,
            "total_participants": sum(participant_counts),
            "source_lines": sum(kind_count(room, "source") for room in meetings),
            "relay_lines": sum(kind_count(room, "relay") for room in meetings),
            "chat_messages": sum(int(room.get("chat_message_count") or 0) for room in meetings),
            "live_summaries": sum(1 for room in meetings if summary_completed(room, "interim")),
            "final_summaries": sum(1 for room in meetings if summary_completed(room, "final")),
        },
        "meetings_over_time": days,
        "language_distribution": sorted(combos.values(), key=lambda entry: entry["count"], reverse=True),
        "ai_mode_usage": [{"mode": mode, "count": modes.get(mode, 0)} for mode in AI_MODES],
    }
