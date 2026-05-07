from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ChatTranslationMode = Literal["original_only", "translate"]

from server.meeting_modes import (
    BRSE_PARTICIPANT_ID,
    BRSE_MODE_RELAY,
    DEFAULT_BRSE_ENABLED,
    DEFAULT_BRSE_MODE,
    DEFAULT_RELAY_LANGUAGE_MAP,
    DEFAULT_ROOM_MEETING_LANGUAGES,
    INTERPRETER_MODE_BRSE_PARTICIPANT,
    MEETING_MODE_BRSE_RELAY,
    PARTICIPANT_KIND_HUMAN,
    SUPPORTED_MEETING_LANGUAGES,
)


RoomStatus = Literal["created", "active", "empty"]
ParticipantStatus = Literal["joining", "connected", "reconnecting", "disconnected"]
Language = Literal["vi", "en", "ja", "zh", "ko", "fr", "es", "auto"]
MeetingLanguage = Literal["vi", "en", "ja", "zh", "ko", "fr", "es"]
BrseMode = Literal["relay", "silent_summary"]
MeetingMode = Literal["direct_translation", "brse_relay", "brse_silent_summary"]
InterpreterMode = Literal["per_listener", "brse_participant"]
ParticipantKind = Literal["human", "virtual_brse"]
MeetingAudioModel = Literal["translated_audio_first", "brse_participant_audio", "brse_silent_listener"]
CrossLanguageAudioPolicy = Literal["interpreter_track", "human_original_plus_brse", "human_original_only"]
CanonicalRemoteAudioPolicy = Literal[
    "interpreter_track_for_cross_language",
    "human_original_track",
]
SameLanguageAudioPolicy = Literal["human_passthrough"]
AiRelayAudioPolicy = Literal["listener_private_track", "virtual_participant_track", "disabled"]
RelayTranscriptPolicy = Literal["publish_realtime", "source_only_internal"]
TranscriptKind = Literal["source", "translated", "relay"]
RelayStyle = Literal["normal", "summary"]
ScreenShareSource = Literal["screen_share"]
MeetingSummaryStatus = Literal["pending", "completed", "failed", "skipped"]
MeetingSummaryType = Literal["interim", "final"]


class RoomAudioRouting(BaseModel):
    model: MeetingAudioModel = "brse_participant_audio"
    cross_language_remote_audio: CrossLanguageAudioPolicy = "human_original_plus_brse"
    canonical_remote_audio: CanonicalRemoteAudioPolicy = "human_original_track"
    same_language_policy: SameLanguageAudioPolicy = "human_passthrough"
    ai_relay_audio: AiRelayAudioPolicy = "virtual_participant_track"
    interpreter_mode: InterpreterMode = INTERPRETER_MODE_BRSE_PARTICIPANT
    bridge_strategy: Literal["speaker_language_map"] = "speaker_language_map"
    relay_language_map: Dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_RELAY_LANGUAGE_MAP)
    )
    virtual_participant_id: str = BRSE_PARTICIPANT_ID
    brse_mode: BrseMode = BRSE_MODE_RELAY
    ai_audio_output_enabled: bool = True
    source_transcript_capture: bool = True
    relay_transcript_policy: RelayTranscriptPolicy = "publish_realtime"


class ParticipantState(BaseModel):
    participant_id: str
    session_id: str
    display_name: str
    language: Language
    status: ParticipantStatus
    joined_at: str
    last_seen_at: Optional[str] = None
    left_at: Optional[str] = None
    ws_connected: bool = False
    media_connected: bool = False
    kind: ParticipantKind = PARTICIPANT_KIND_HUMAN
    is_virtual: bool = False
    livekit_identity: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    is_screen_sharing: bool = False
    screen_share: Optional["ScreenShareTrackInfo"] = None


class ParticipantSnapshot(BaseModel):
    participant_id: str
    display_name: str
    language: Language
    status: ParticipantStatus
    joined_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    ws_connected: bool = False
    kind: ParticipantKind = PARTICIPANT_KIND_HUMAN
    is_virtual: bool = False
    livekit_identity: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    is_screen_sharing: bool = False
    screen_share: Optional["ScreenShareTrackInfo"] = None


class ScreenShareTrackInfo(BaseModel):
    active: bool = True
    source: ScreenShareSource = "screen_share"
    track_sid: Optional[str] = None
    track_name: Optional[str] = None
    started_at: str


class RoomState(BaseModel):
    room_id: str
    state: RoomStatus
    created_at: str
    activated_at: Optional[str] = None
    emptied_at: Optional[str] = None
    expires_at: str
    brse_enabled: bool = DEFAULT_BRSE_ENABLED
    brse_mode: BrseMode = DEFAULT_BRSE_MODE
    participant_limit: Optional[int] = None  # None = no backend participant cap
    supported_languages: List[MeetingLanguage] = Field(
        default_factory=lambda: list(SUPPORTED_MEETING_LANGUAGES)
    )
    meeting_languages: List[MeetingLanguage] = Field(
        default_factory=lambda: list(DEFAULT_ROOM_MEETING_LANGUAGES)
    )
    meeting_mode: MeetingMode = MEETING_MODE_BRSE_RELAY
    interpreter_mode: InterpreterMode = INTERPRETER_MODE_BRSE_PARTICIPANT
    audio_routing: RoomAudioRouting = Field(default_factory=RoomAudioRouting)
    virtual_participants: List[ParticipantSnapshot] = Field(default_factory=list)


class TranscriptParticipantRef(BaseModel):
    participant_id: str
    display_name: str
    language: Language
    source_language: Language
    kind: ParticipantKind = PARTICIPANT_KIND_HUMAN
    is_virtual: bool = False
    livekit_identity: Optional[str] = None


class TranscriptTargetRef(BaseModel):
    target_language: Language
    participant_ids: List[str] = Field(default_factory=list)


class TranscriptEvent(BaseModel):
    transcript_id: str
    utterance_id: Optional[str] = None
    kind: TranscriptKind = "relay"
    speaker_id: str
    speaker_display_name: str
    speaker_language: Language = "auto"
    src_lang: Language
    text: str = ""
    source_text: str
    created_at: str
    is_final: bool = True
    fallback_used: bool = False
    listener_id: Optional[str] = None
    target_lang: Optional[Language] = None
    translated_text: Optional[str] = None
    brse_text: Optional[str] = None
    audio_track_name: Optional[str] = None
    audio_output: Optional[Dict[str, Any]] = None
    relay_mode: Optional[InterpreterMode] = None
    relay_style: Optional[RelayStyle] = None
    speaker: Optional[TranscriptParticipantRef] = None
    original_speaker: Optional[TranscriptParticipantRef] = None
    listener: Optional[Dict[str, Any]] = None
    brse_participant: Optional[TranscriptParticipantRef] = None
    relay_target: Optional[TranscriptTargetRef] = None


class ChatTranslation(BaseModel):
    language: MeetingLanguage
    text: str


class ChatMessage(BaseModel):
    message_id: str
    room_id: str
    participant_id: str
    display_name: str
    language: Language
    text: str
    created_at: str
    client_event_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_display_name: Optional[str] = None
    sender_language: Optional[Language] = None
    sent_at: Optional[str] = None
    # Translation fields — additive, default to original_only for backward compat
    translation_mode: ChatTranslationMode = "original_only"
    translations: List[ChatTranslation] = Field(default_factory=list)


class CreateRoomResponseRoom(BaseModel):
    room_id: str
    state: RoomStatus
    created_at: str
    expires_at: str
    brse_enabled: bool
    brse_mode: BrseMode = DEFAULT_BRSE_MODE
    participant_limit: Optional[int] = None
    supported_languages: List[MeetingLanguage]
    meeting_languages: List[MeetingLanguage]
    meeting_mode: MeetingMode
    interpreter_mode: InterpreterMode
    audio_routing: RoomAudioRouting


class CreateRoomResponseJoin(BaseModel):
    api_path: str
    share_url: str


class CreateRoomResponse(BaseModel):
    room: CreateRoomResponseRoom
    join: CreateRoomResponseJoin


class CreateRoomRequest(BaseModel):
    meeting_languages: List[str] = Field(
        default_factory=lambda: list(DEFAULT_ROOM_MEETING_LANGUAGES)
    )
    brse_enabled: bool = DEFAULT_BRSE_ENABLED
    brse_mode: BrseMode = DEFAULT_BRSE_MODE


class JoinRoomRequestClient(BaseModel):
    sdk: str
    version: str


class JoinRoomRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=40)
    language: Language
    client: Optional[JoinRoomRequestClient] = None


class ScreenShareStartRequest(BaseModel):
    track_sid: Optional[str] = None
    track_name: Optional[str] = None
    source: ScreenShareSource = "screen_share"


class ScreenShareStateResponse(BaseModel):
    participant_id: str
    display_name: str
    active: bool
    timestamp: str
    track_sid: Optional[str] = None
    track_name: Optional[str] = None


class JoinRoomResponseParticipant(BaseModel):
    participant_id: str
    session_id: str
    display_name: str
    language: Language


class JoinRoomResponseRoomToken(BaseModel):
    token: str
    expires_at: str


class JoinRoomResponseWebsocket(BaseModel):
    url: str


class JoinRoomResponseLivekit(BaseModel):
    url: str
    room_name: str
    participant_identity: str
    participant_name: str
    token: str


class SnapshotData(BaseModel):
    participants: List[ParticipantSnapshot]
    recent_transcripts: List[TranscriptEvent]
    recent_messages: List[ChatMessage] = Field(default_factory=list)


class JoinRoomResponse(BaseModel):
    room: CreateRoomResponseRoom
    participant: JoinRoomResponseParticipant
    room_token: JoinRoomResponseRoomToken
    websocket: JoinRoomResponseWebsocket
    livekit: JoinRoomResponseLivekit
    snapshot: SnapshotData


class RoomSnapshotResponseRoom(CreateRoomResponseRoom):
    participant_count: int


class RoomSnapshotResponse(BaseModel):
    room: RoomSnapshotResponseRoom
    participants: List[ParticipantSnapshot]
    recent_transcripts: List[TranscriptEvent]
    recent_messages: List[ChatMessage] = Field(default_factory=list)


class MeetingSummaryActionItem(BaseModel):
    text: str
    owner: Optional[str] = None
    due: Optional[str] = None


class MeetingSummaryParticipantItem(BaseModel):
    participant_id: Optional[str] = None
    display_name: Optional[str] = None
    summary: str


class MeetingSummaryResponse(BaseModel):
    room_id: str
    summary_id: Optional[str] = None
    summary_type: MeetingSummaryType = "final"
    status: MeetingSummaryStatus
    created_at: str
    generated_at: Optional[str] = None
    summary_language: str = "en"
    summary_text: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    action_items: List[MeetingSummaryActionItem] = Field(default_factory=list)
    participant_summary: List[MeetingSummaryParticipantItem] = Field(default_factory=list)
    duration_seconds: Optional[int] = None
    source_window: Dict[str, Any] = Field(default_factory=dict)
    source_stats: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


TestSessionStatus = Literal[
    "created",
    "active",
    "stopped",
    "expired",
    "listening",
    "translating",
    "completed",
]


class MicTestSession(BaseModel):
    session_id: str
    status: TestSessionStatus = "created"
    created_at: str
    expires_at: str


class TranslationTestSession(BaseModel):
    session_id: str
    src_lang: Language
    tgt_lang: Language
    status: TestSessionStatus = "created"
    created_at: str
    expires_at: str


class CreateMicTestSessionResponse(BaseModel):
    session_id: str
    status: TestSessionStatus
    created_at: str
    expires_at: str
    websocket: Dict[str, str]


class CreateTranslationTestRequest(BaseModel):
    src_lang: str
    tgt_lang: str


class CreateTranslationTestSessionResponse(BaseModel):
    session_id: str
    src_lang: Language
    tgt_lang: Language
    status: TestSessionStatus
    created_at: str
    expires_at: str
    websocket: Dict[str, str]
