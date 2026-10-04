"""Response/request models for /api/admin (mirrored in FE/src/admin/api/types.ts)."""
from __future__ import annotations

from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, Field

T = TypeVar("T")

HealthStatus = Literal["healthy", "degraded", "down", "unknown"]
RoomStatus = Literal["live", "empty", "error", "expired"]
AiMode = Literal["voice_text", "text_only", "captions", "summary_capture", "off"]
MeetingStatus = Literal["live", "ended"]
Severity = Literal["info", "warning", "error"]


class Page(BaseModel, Generic[T]):
    items: List[T]
    page: int
    page_size: int
    total: int


# ── Session ────────────────────────────────────────────────────────────────

# ── Health ─────────────────────────────────────────────────────────────────

class HealthComponent(BaseModel):
    key: str
    label: str
    status: HealthStatus
    detail: Optional[str] = None


class SystemHealth(BaseModel):
    checked_at: str
    overall: HealthStatus
    components: List[HealthComponent]


class StageHealth(BaseModel):
    status: HealthStatus
    reason: Optional[str] = None


class AiHealth(BaseModel):
    window_minutes: int
    stt: StageHealth
    translation: StageHealth
    voice: StageHealth
    summary: StageHealth


# ── Live rooms ─────────────────────────────────────────────────────────────

class LiveRoomRow(BaseModel):
    room_id: str
    state: str
    status: RoomStatus
    room_languages: List[str]
    participants_online: int
    participants_total: int
    ai_mode: AiMode
    brse_enabled: bool
    brse_state: Optional[str] = None
    runtime_attached: Optional[bool] = None
    created_at: Optional[str] = None
    activated_at: Optional[str] = None
    expires_at: Optional[str] = None
    seconds_left: Optional[int] = None
    recent_error_count: int = 0
    last_error_at: Optional[str] = None
    # Access only (Password protected / Public link); the password itself is never exposed.
    password_protected: bool = False


class LiveRoomsResponse(Page[LiveRoomRow]):
    counts_by_status: Dict[str, int] = Field(default_factory=dict)
    runtime_online: Optional[bool] = None


class ParticipantMedia(BaseModel):
    connection: Optional[str] = None
    microphone: Optional[str] = None
    camera: Optional[str] = None
    screen_share: Optional[str] = None


class LiveParticipant(BaseModel):
    participant_id: str
    display_name: str
    language: str
    kind: str
    is_virtual: bool
    status: str
    ws_connected: bool = False
    media_connected: bool = False
    joined_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    is_screen_sharing: bool = False
    media: Optional[ParticipantMedia] = None


class SpeakerAiStatus(BaseModel):
    speaker_id: str
    speaker_name: Optional[str] = None
    status: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    pending_relay_count: Optional[int] = None
    overlap_level: Optional[str] = None
    audience_count: Optional[int] = None
    message: Optional[str] = None
    updated_at: Optional[str] = None


class AiErrorSummary(BaseModel):
    occurred_at: Optional[str] = None
    code: Optional[str] = None
    issue_code: Optional[str] = None
    message: Optional[str] = None


class RoomBrseState(BaseModel):
    enabled: bool
    ai_mode: AiMode
    runtime_attached: Optional[bool] = None
    state: Optional[str] = None
    current_speaker_id: Optional[str] = None
    current_speaker_name: Optional[str] = None
    queue_depth: Optional[int] = None
    speakers: List[SpeakerAiStatus] = Field(default_factory=list)
    latency: Dict[str, Any] = Field(default_factory=dict)
    last_success_at: Optional[str] = None
    last_error: Optional[AiErrorSummary] = None
    output_mode_downgrade_reason: Optional[str] = None
    audio_suppressed_reason: Optional[str] = None


class LiveRoomDetail(BaseModel):
    room: LiveRoomRow
    participants: List[LiveParticipant]
    media_source: Literal["livekit", "unavailable"]
    brse: RoomBrseState


class TraceStage(BaseModel):
    key: str
    label: str
    status: str
    ms: Optional[float] = None
    note: Optional[str] = None


class TimelineItem(BaseModel):
    event_id: str
    event_type: str
    occurred_at: Optional[str] = None
    room_id: Optional[str] = None
    utterance_id: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    src_lang: Optional[str] = None
    target_lang: Optional[str] = None
    outcome: Optional[str] = None
    reason: Optional[str] = None
    issue_code: Optional[str] = None
    severity: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None
    relay_style: Optional[str] = None
    stages: List[TraceStage] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    source_text: Optional[str] = None
    relay_text: Optional[str] = None


class TimelineResponse(BaseModel):
    items: List[TimelineItem]
    source: Literal["live", "history"]


class TranscriptLine(BaseModel):
    id: str
    kind: Literal["source", "relay", "translated", "chat", "system"]
    created_at: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    language: Optional[str] = None
    target_language: Optional[str] = None
    text: str
    source_text: Optional[str] = None
    translations: List[Dict[str, Any]] = Field(default_factory=list)


class TranscriptResponse(BaseModel):
    items: List[TranscriptLine]
    limit_note: Optional[str] = None


# ── Overview ───────────────────────────────────────────────────────────────

Number = Union[int, float]


class Kpi(BaseModel):
    value: Optional[Number] = None
    previous: Optional[Number] = None
    available: bool = True
    note: Optional[str] = None


class IssueOccurrence(BaseModel):
    event_id: str
    occurred_at: Optional[str] = None
    room_id: Optional[str] = None
    issue_code: str
    title: str
    severity: str
    speaker_name: Optional[str] = None
    language_pair: Optional[str] = None
    detail: Optional[str] = None


class OverviewResponse(BaseModel):
    generated_at: str
    history_available: bool
    kpis: Dict[str, Kpi]
    live_rooms: List[LiveRoomRow]
    system_health: SystemHealth
    ai_health: AiHealth
    recent_issues: List[IssueOccurrence]


# ── Meetings ───────────────────────────────────────────────────────────────

class MeetingRow(BaseModel):
    room_id: str
    status: MeetingStatus
    end_reason: Optional[str] = None
    created_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    room_languages: List[str]
    participant_count: int
    ai_mode: AiMode
    final_summary_status: Optional[str] = None
    live_summary_status: Optional[str] = None
    password_protected: bool = False


class MeetingDetail(BaseModel):
    meeting: MeetingRow
    activated_at: Optional[str] = None
    expires_at: Optional[str] = None
    brse_mode: Optional[str] = None
    brse_output_mode: Optional[str] = None
    counts: Dict[str, int]
    summaries: Dict[str, Optional[Dict[str, Any]]]
    is_live_in_runtime_store: bool


class RelayRow(BaseModel):
    id: str
    created_at: Optional[str] = None
    utterance_id: Optional[str] = None
    speaker_name: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    original: Optional[str] = None
    translation: str
    relay_style: Optional[str] = None
    delivery_state: Optional[str] = None
    delivery_reason: Optional[str] = None
    latency_ms: Optional[float] = None
    voice_delivered: Optional[bool] = None


class MeetingParticipantRow(BaseModel):
    participant_id: str
    display_name: Optional[str] = None
    language: Optional[str] = None
    kind: Optional[str] = None
    is_virtual: bool = False
    first_joined_at: Optional[str] = None
    last_joined_at: Optional[str] = None
    last_left_at: Optional[str] = None
    join_count: int = 0


class RegenerateSummaryRequest(BaseModel):
    language: Optional[str] = None


# ── AI metrics / issues / analytics / config ─────────────────────────────

class AiMetricsResponse(BaseModel):
    window: str
    range_start: str
    range_end: str
    sample_limit: int
    sampled: int
    truncated: bool
    history_available: bool
    stages: Dict[str, Dict[str, Any]]
    summary: Dict[str, Any]
    language_pairs: List[Dict[str, Any]]
    health: AiHealth
    percentile_min_samples: Dict[str, int]


class IssueAggregate(BaseModel):
    code: str
    title: str
    stage: str
    severity: str
    description: str
    occurrences: int
    affected_rooms: int
    first_at: Optional[str] = None
    latest_at: Optional[str] = None
    top_language_pair: Optional[str] = None


class IssuesResponse(BaseModel):
    window: str
    history_available: bool
    truncated: bool
    items: List[IssueAggregate]


class IssueDetailResponse(BaseModel):
    window: str
    issue: IssueAggregate
    occurrences: Page[IssueOccurrence]


class AnalyticsResponse(BaseModel):
    range_start: str
    range_end: str
    history_available: bool
    truncated: bool
    totals: Dict[str, Optional[Number]]
    meetings_over_time: List[Dict[str, Any]]
    language_distribution: List[Dict[str, Any]]
    ai_mode_usage: List[Dict[str, Any]]
    feature_usage: Dict[str, Kpi]


class ConfigItem(BaseModel):
    key: str
    label: str
    value: Any
    unit: Optional[str] = None
    source: str
    note: Optional[str] = None


class AdminConfigResponse(BaseModel):
    editable: bool
    room: List[ConfigItem]
    ai: List[ConfigItem]
    languages: List[Dict[str, Any]]
    notifications: List[Dict[str, Any]]
    operations: List[ConfigItem]
