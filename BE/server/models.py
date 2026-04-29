from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime

# Enums (using Literal for simplicity as per contract)
RoomStatus = Literal["created", "active", "empty"]
ParticipantStatus = Literal["joining", "connected", "reconnecting", "disconnected"]
Language = Literal["vi", "en", "ja", "auto"]

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

class TranscriptEvent(BaseModel):
    transcript_id: str
    speaker_id: str
    speaker_display_name: str
    src_lang: Language
    source_text: str
    created_at: str
    # other fields might be specific to partial/final, but we store minimal in snapshot

# REST DTOs
class CreateRoomResponseRoom(BaseModel):
    room_id: str
    state: RoomStatus
    created_at: str
    expires_at: str
    participant_limit: int
    supported_languages: List[str]

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
