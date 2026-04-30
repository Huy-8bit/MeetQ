from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime

# Enums (using Literal for simplicity as per contract)
RoomStatus = Literal["created", "active", "empty"]
ParticipantStatus = Literal["joining", "connected", "reconnecting", "disconnected"]
Language = Literal["vi", "en", "ja", "auto"]
MeetingAudioModel = Literal["translated_audio_first"]
CrossLanguageAudioPolicy = Literal["interpreter_track"]
SameLanguageAudioPolicy = Literal["human_passthrough"]
TranscriptKind = Literal["source", "translated"]


class RoomAudioRouting(BaseModel):
    model: MeetingAudioModel = "translated_audio_first"
    cross_language_remote_audio: CrossLanguageAudioPolicy = "interpreter_track"
    canonical_remote_audio: Literal["interpreter_track_for_cross_language"] = (
        "interpreter_track_for_cross_language"
    )
    same_language_policy: SameLanguageAudioPolicy = "human_passthrough"

# Redis Models
class ParticipantState(BaseModel):
    participant_id: str
    session_id: str
    display_name: str
    language: Language
    status: ParticipantStatus
    joined_at: str
    left_at: Optional[str] = None
    media_connected: bool = False

class RoomState(BaseModel):
    room_id: str
    state: RoomStatus
    created_at: str
    expires_at: str
    participant_limit: int = 8
    supported_languages: List[str] = ["vi", "en", "ja"]
    audio_routing: RoomAudioRouting = Field(default_factory=RoomAudioRouting)


class TranscriptSpeakerRef(BaseModel):
    participant_id: str
    display_name: str
    language: Language
    source_language: Language


class TranscriptListenerRef(BaseModel):
    participant_id: str
    target_language: Language


class TranscriptEvent(BaseModel):
    transcript_id: str
    utterance_id: Optional[str] = None
    kind: TranscriptKind = "translated"
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
    audio_track_name: Optional[str] = None
    audio_output: Optional[Dict[str, Any]] = None
    speaker: Optional[TranscriptSpeakerRef] = None
    listener: Optional[TranscriptListenerRef] = None
    # other fields might be specific to partial/final, but we store minimal in snapshot

# REST DTOs
class CreateRoomResponseRoom(BaseModel):
    room_id: str
    state: RoomStatus
    created_at: str
    expires_at: str
    participant_limit: int
    supported_languages: List[str]
    audio_routing: RoomAudioRouting

class CreateRoomResponseJoin(BaseModel):
    api_path: str
    share_url: str

class CreateRoomResponse(BaseModel):
    room: CreateRoomResponseRoom
    join: CreateRoomResponseJoin

class JoinRoomRequestClient(BaseModel):
    sdk: str
    version: str

class JoinRoomRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=40)
    language: Language
    client: Optional[JoinRoomRequestClient] = None

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

class ParticipantSnapshot(BaseModel):
    participant_id: str
    display_name: str
    language: Language
    status: ParticipantStatus
    joined_at: Optional[str] = None

class SnapshotData(BaseModel):
    participants: List[ParticipantSnapshot]
    recent_transcripts: List[TranscriptEvent]

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


# ---------------------------------------------------------------------------
# Test session models
# ---------------------------------------------------------------------------

TestSessionStatus = Literal[
    "created", "active", "stopped", "expired",          # mic test
    "listening", "translating", "completed",             # translation test
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


# REST DTOs for test session creation

class CreateMicTestSessionResponse(BaseModel):
    session_id: str
    status: TestSessionStatus
    created_at: str
    expires_at: str
    websocket: Dict[str, str]


class CreateTranslationTestRequest(BaseModel):
    src_lang: Language
    tgt_lang: Language


class CreateTranslationTestSessionResponse(BaseModel):
    session_id: str
    src_lang: Language
    tgt_lang: Language
    status: TestSessionStatus
    created_at: str
    expires_at: str
    websocket: Dict[str, str]
