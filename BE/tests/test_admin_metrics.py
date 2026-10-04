from datetime import datetime, timedelta, timezone

from server.service.admin import metrics
from server.service.brain_runtime.trace import build_trace_payload, trace_init, trace_mark
from server.service.ops.catalog import classify_ai_error, classify_relay_trace, sanitize_message

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def trace(outcome, **extra):
    doc = {
        "outcome": outcome,
        "reason": extra.pop("reason", None),
        "metrics": extra.pop("metrics", {}),
        "translation_requested": extra.pop("translation_requested", False),
        "audio_requested": extra.pop("audio_requested", False),
        "audio_delivered": extra.pop("audio_delivered", False),
        "policy_decision": extra.pop("policy_decision", None),
        "source_accepted": extra.pop("source_accepted", True),
        "language_pair": extra.pop("language_pair", None),
    }
    doc.update(extra)
    return doc


def test_percentiles_require_minimum_samples():
    assert metrics.latency_summary([100, 200, 300]) == {"samples": 3, "avg": 200, "p50": None, "p95": None, "p99": None}
    summary = metrics.latency_summary(list(range(1, 21)))
    assert summary["p50"] == 10 or summary["p50"] == 11
    assert summary["p95"] is not None
    assert summary["p99"] is None
    assert metrics.latency_summary([None, "x"])["samples"] == 0


def test_ai_mode_follows_product_rules():
    assert metrics.ai_mode_of({"brse_enabled": False, "room_languages": ["vi", "ja"]}) == "off"
    assert metrics.ai_mode_of({"brse_enabled": True, "room_languages": ["vi"], "brse_output_mode": "voice_text"}) == "captions"
    assert metrics.ai_mode_of({"brse_enabled": True, "room_languages": ["vi", "ja"], "brse_output_mode": "voice_text"}) == "voice_text"
    assert metrics.ai_mode_of({"brse_enabled": True, "room_languages": ["vi", "ja"], "brse_output_mode": "text_only"}) == "text_only"
    assert metrics.ai_mode_of({"brse_enabled": True, "room_languages": ["vi", "ja", "en"], "brse_output_mode": "voice_text"}) == "text_only"
    assert metrics.ai_mode_of({"brse_enabled": True, "brse_mode": "silent_summary", "room_languages": ["vi", "ja"]}) == "summary_capture"


def test_room_status_mapping():
    future = (NOW + timedelta(minutes=10)).isoformat()
    past = (NOW - timedelta(seconds=1)).isoformat()
    assert metrics.room_status(expires_at=past, online_human_count=3, ai_state="idle", last_error_at=None, now=NOW) == "expired"
    assert metrics.room_status(expires_at=future, online_human_count=2, ai_state="error", last_error_at=None, now=NOW) == "error"
    assert metrics.room_status(expires_at=future, online_human_count=2, ai_state="idle", last_error_at=NOW - timedelta(seconds=30), now=NOW) == "error"
    assert metrics.room_status(expires_at=future, online_human_count=2, ai_state="idle", last_error_at=NOW - timedelta(minutes=30), now=NOW) == "live"
    assert metrics.room_status(expires_at=future, online_human_count=0, ai_state="idle", last_error_at=None, now=NOW) == "empty"


def test_ai_state_aggregation_prefers_most_active_state():
    assert metrics.aggregate_ai_state(False, [{"status": "playing"}]) == "relay_off"
    assert metrics.aggregate_ai_state(True, []) == "idle"
    assert metrics.aggregate_ai_state(True, [{"status": "idle"}, {"status": "translating"}, {"status": "capturing"}]) == "translating"
    assert metrics.aggregate_ai_state(True, [{"status": "playing"}, {"status": "error"}]) == "error"


def test_meeting_status_uses_terminal_flag_or_expiry():
    assert metrics.meeting_status({"status_summary": {"terminal": True, "state": "empty"}}, NOW) == "ended"
    assert metrics.meeting_status({"expires_at": (NOW - timedelta(minutes=1)).isoformat()}, NOW) == "ended"
    assert metrics.meeting_end_reason({"expires_at": (NOW - timedelta(minutes=1)).isoformat()}, NOW) == "expired"
    assert metrics.meeting_status({"expires_at": (NOW + timedelta(minutes=1)).isoformat()}, NOW) == "live"


def test_stage_stats_count_requests_success_and_errors():
    traces = [
        trace("delivered", policy_decision="publish", translation_requested=True, audio_requested=True, audio_delivered=True,
              metrics={"stt_ms": 400, "first_text_ms": 300, "first_audio_ms": 500, "total_ms": 1800}),
        trace("delivered", policy_decision="publish", translation_requested=True, audio_requested=True, audio_delivered=False,
              metrics={"stt_ms": 500, "first_text_ms": 350, "total_ms": 2100}),
        trace("output_rejected", policy_decision="publish", translation_requested=True, output_rejected_reason="meta_or_unclear_relay_output",
              metrics={"stt_ms": 450, "first_text_ms": 280}),
        trace("stt_failed", reason="input_transcription_failed", source_accepted=False),
        trace("source_rejected", reason="filler_only_transcript", metrics={"stt_ms": 300}),
        trace("superseded"),
        trace("relay_dropped", reason="stale_public_relay", policy_decision="publish", metrics={"stt_ms": 600}),
    ]
    stages = metrics.compute_stage_stats(traces)
    assert stages["stt"]["requests"] == 6
    assert stages["stt"]["errors"] == 1
    assert stages["translation"]["requests"] == 3
    assert stages["translation"]["errors"] == 1
    assert stages["translation"]["error_breakdown"][0]["reason"] == "meta_or_unclear_relay_output"
    assert stages["voice"]["requests"] == 2
    assert stages["voice"]["errors"] == 1
    assert stages["delivery"]["requests"] == 4
    assert stages["delivery"]["success"] == 2
    assert {row["reason"] for row in stages["delivery"]["error_breakdown"]} == {"stale_public_relay", "output_rejected"}


def test_stage_health_thresholds():
    assert metrics.stage_health({"requests": 0}, "stt")["status"] == "unknown"
    assert metrics.stage_health({"requests": 10, "errors": 0, "latency": {"p95": 900}}, "stt")["status"] == "healthy"
    assert metrics.stage_health({"requests": 10, "errors": 2, "latency": {}}, "stt")["status"] == "degraded"
    assert metrics.stage_health({"requests": 10, "errors": 6, "latency": {}}, "stt")["status"] == "down"
    assert metrics.stage_health({"requests": 30, "errors": 0, "latency": {"p95": 9000}}, "translation")["status"] == "degraded"
    assert metrics.stage_health({"requests": 30, "errors": 0}, "stt", blocking_errors=1)["status"] == "down"


def test_trace_stages_explain_where_relay_stopped():
    delivered = metrics.build_trace_stages(
        trace("delivered", policy_decision="publish", translation_requested=True, audio_requested=True, audio_delivered=True,
              metrics={"stt_ms": 620, "first_text_ms": 410, "first_audio_ms": 730, "total_ms": 1920})
    )
    assert [stage["key"] for stage in delivered] == ["stt", "validation", "policy", "translation", "voice", "delivery"]
    assert all(stage["status"] == "ok" for stage in delivered)
    assert delivered[-1]["ms"] == 1920

    late = metrics.build_trace_stages(
        trace("relay_dropped", reason="stale_public_relay", policy_decision="publish", metrics={"stt_ms": 500, "age_ms": 8720})
    )
    assert late[-1] == {"key": "delivery", "label": "Delivery", "status": "failed", "ms": 8720, "note": "stale_public_relay"}

    rejected = metrics.build_trace_stages(trace("source_rejected", source_accepted=False, source_reason="filler_only_transcript", metrics={"stt_ms": 300}))
    assert rejected[-1]["key"] == "validation" and rejected[-1]["status"] == "failed"


def test_issue_classification_and_sanitizing():
    assert classify_relay_trace(trace("relay_dropped", reason="stale_public_relay")) == ("RELAY_TOO_LATE", "warning")
    assert classify_relay_trace(trace("delivered", audio_requested=True, audio_delivered=False)) == ("TTS_NO_AUDIO", "warning")
    assert classify_relay_trace(trace("delivered", metrics={"total_ms": 9000})) == ("RELAY_SLOW", "warning")
    assert classify_relay_trace(trace("delivered", metrics={"total_ms": 1500})) == (None, None)
    assert classify_relay_trace(trace("relay_suppressed", reason="overlap_blocked_literal_relay_suppressed"))[0] == "RELAY_SUPPRESSED_OVERLAP"
    assert classify_ai_error("realtime_auth_error", "x") == ("REALTIME_AUTH_FAILED", "error")
    assert classify_ai_error("interpreter_unavailable", "BRSE relay audio track failure: boom")[0] == "AUDIO_TRACK_FAILURE"
    cleaned = sanitize_message("Incorrect API key provided: sk-proj-abcdefghijklmnop. Bearer abc.def")
    assert "sk-proj" not in cleaned and "abc.def" not in cleaned


def test_trace_payload_has_timings_but_no_text():
    state = {
        "utterance_id": "seg_1",
        "speaker_id": "pt_1",
        "src_lang": "vi",
        "target_lang": "ja",
        "source_text": "secret meeting content",
        "brse_text": "秘密",
        "created_at": "2026-10-03T00:00:00Z",
    }
    trace_init(state, speech_started_at=None, speech_stopped_at=None, audio_requested=True)
    for milestone in ("transcript_completed_at", "policy_at", "response_started_at", "first_text_at", "first_audio_at", "text_gate_passed_at", "final_published_at"):
        trace_mark(state, milestone)
    payload = build_trace_payload(state, outcome="delivered", reason=None, speaker_name="Huy")
    assert payload["audio_delivered"] is True
    assert payload["metrics"]["stt_ms"] is not None
    serialized = str(payload)
    assert "secret meeting content" not in serialized and "秘密" not in serialized


def test_analytics_aggregation():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 4, tzinfo=timezone.utc)
    rooms = [
        {"created_at_dt": datetime(2026, 10, 1, 9, tzinfo=timezone.utc), "participant_count_total": 2, "duration_seconds": 600,
         "room_languages": ["vi", "ja"], "brse_enabled": True, "brse_output_mode": "voice_text",
         "transcript_kind_counts": {"source": 10, "relay": 9}, "chat_message_count": 3,
         "meeting_summaries": {"final": {"status": "completed"}, "interim": {"status": "completed"}}},
        {"created_at_dt": datetime(2026, 10, 3, 9, tzinfo=timezone.utc), "participant_count_total": 4, "duration_seconds": 1200,
         "room_languages": ["ja", "vi"], "brse_enabled": True, "brse_output_mode": "text_only",
         "transcript_kind_counts": {"source": 5, "relay": 5}, "meeting_summaries": {"final": {"status": "failed"}}},
        {"created_at_dt": datetime(2026, 10, 3, 10, tzinfo=timezone.utc), "participant_count_total": 0,
         "room_languages": ["en"], "brse_enabled": True},
    ]
    result = metrics.build_analytics(rooms, range_start=start, range_end=end)
    totals = result["totals"]
    assert totals["rooms_created"] == 3
    assert totals["meetings"] == 2
    assert totals["avg_duration_seconds"] == 900
    assert totals["avg_participants"] == 3.0
    assert totals["relay_lines"] == 14
    assert totals["final_summaries"] == 1 and totals["live_summaries"] == 1
    assert result["language_distribution"] == [{"key": "ja+vi", "label": "Japanese ⇄ Vietnamese", "count": 2}]
    usage = {row["mode"]: row["count"] for row in result["ai_mode_usage"]}
    assert usage["voice_text"] == 1 and usage["text_only"] == 1 and usage["captions"] == 0
    assert [day["meetings"] for day in result["meetings_over_time"]] == [1, 0, 1, 0]
