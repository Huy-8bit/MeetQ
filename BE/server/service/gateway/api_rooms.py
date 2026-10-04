from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse
from server.service.gateway.room_service import (
    BrseToggleForbiddenError,
    InvalidLanguageError,
    InvalidMeetingLanguagesError,
    InvalidMeetingSummaryLanguageError,
    InvalidMeetingSummaryTypeError,
    MeetingSummaryNotFoundError,
    MeetingSummaryNotReadyError,
    MeetingSummaryUnavailableError,
    ParticipantNotFoundError,
    RelayModeNotSupportedError,
    RoomExpiredError,
    RoomFullError,
    RoomNotFoundError,
    RoomService,
)
from server.service.auth.dependencies import require_user
from server.service.gateway.room_access import (
    InvalidRoomPasswordError,
    RoomPasswordRateLimitedError,
    RoomPasswordRequiredError,
)
from server.service.gateway.app_state import app_state
from server.service.gateway.dependencies import (
    get_room_service,
    optional_token_dependency,
    verify_token_dependency,
)
from server.models import (
    CreateRoomRequest,
    CreateRoomResponse,
    CreateRoomResponseRoom,
    RoomSnapshotResponse,
    JoinRoomRequest,
    JoinRoomResponse,
    MeetingSummaryResponse,
    ScreenShareStartRequest,
    ScreenShareStateResponse,
    UpdateRelayModeRequest,
)
from typing import Dict, Any
from typing import Optional

router = APIRouter()

def _error_response(code: str, message: str, status_code: int = 400, details: dict = None):
    err = {
        "error": {
            "code": code,
            "message": message
        }
    }
    if details:
        err["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=err)

# Creating, viewing, joining rooms and their summaries needs a signed-in user (USER_AUTH_REQUIRED).
# Calls made inside a room are authorized by the room token issued at join.
signed_in = [Depends(require_user)]


@router.post("/api/rooms", response_model=CreateRoomResponse, dependencies=signed_in)
async def create_room(
    req: Optional[CreateRoomRequest] = Body(default=None),
    service: RoomService = Depends(get_room_service),
):
    try:
        payload = req or CreateRoomRequest()
        return await service.create_room(
            payload.requested_room_languages(),
            payload.brse_enabled,
            payload.brse_mode,
            payload.brse_output_mode,
            password=payload.password if payload.access == "password" else None,
        )
    except InvalidMeetingLanguagesError as exc:
        return _error_response("invalid_meeting_languages", str(exc), 422, exc.details)

def _session_user_id(session: Optional[Dict[str, Any]]) -> Optional[str]:
    return ((session or {}).get("user") or {}).get("id")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _may_read_protected_room(
    service: RoomService,
    room_id: str,
    claims: Optional[Dict[str, Any]],
    session: Optional[Dict[str, Any]],
) -> bool:
    """Public rooms: any signed-in user. Protected rooms: a room token, or someone who joined it."""
    if claims is not None or not await service.is_password_protected(room_id):
        return True
    user_id = _session_user_id(session)
    history = service.room_history
    if not user_id or history is None or not history.enabled:
        return False
    return bool(await history.db["room_participants"].find_one({"room_id": room_id, "user_id": user_id}, {"_id": 1}))


@router.get("/api/rooms/{room_id}", response_model=RoomSnapshotResponse, dependencies=signed_in)
async def get_room(
    room_id: str,
    claims: Optional[Dict[str, Any]] = Depends(optional_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    try:
        # Without a room token, a protected room shows only its settings (lobby view).
        snapshot = await service.get_room(room_id, include_private=claims is not None)
        recordings = app_state.recording_service
        if recordings is not None:
            snapshot.room.recording = await recordings.current(room_id)
            snapshot.room.recording_available = bool(recordings.available)
        return snapshot
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)


@router.get("/api/rooms/{room_id}/summary", response_model=MeetingSummaryResponse, dependencies=signed_in)
async def get_room_summary(
    room_id: str,
    type: str = "final",
    claims: Optional[Dict[str, Any]] = Depends(optional_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
    service: RoomService = Depends(get_room_service),
):
    if not await _may_read_protected_room(service, room_id, claims, session):
        return _error_response("meeting_summary_not_found", "Meeting summary not found", 404)
    try:
        return await service.get_meeting_summary(room_id, type)
    except MeetingSummaryNotFoundError:
        return _error_response("meeting_summary_not_found", "Meeting summary not found", 404)
    except InvalidMeetingSummaryTypeError:
        return _error_response("invalid_summary_type", "summary type must be interim or final", 422)


@router.post("/api/rooms/{room_id}/summary", response_model=MeetingSummaryResponse, dependencies=signed_in)
async def generate_room_summary(
    room_id: str,
    type: Optional[str] = None,
    language: Optional[str] = None,
    summary_language: Optional[str] = None,
    claims: Optional[Dict[str, Any]] = Depends(optional_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
    service: RoomService = Depends(get_room_service),
):
    if not await _may_read_protected_room(service, room_id, claims, session):
        return _error_response("meeting_summary_not_found", "Meeting summary not found", 404)
    try:
        requested_language = language or summary_language
        return await service.generate_meeting_summary(
            room_id,
            type,
            requested_language=requested_language,
            requester_claims=claims,
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except MeetingSummaryUnavailableError:
        return _error_response("meeting_summary_unavailable", "Meeting summary persistence is unavailable", 503)
    except MeetingSummaryNotReadyError:
        return _error_response("meeting_summary_not_ready", "Final summary can only be generated after room end", 409)
    except MeetingSummaryNotFoundError:
        return _error_response("meeting_summary_not_found", "Meeting summary not found", 404)
    except InvalidMeetingSummaryTypeError:
        return _error_response("invalid_summary_type", "summary type must be interim or final", 422)
    except InvalidMeetingSummaryLanguageError as exc:
        return _error_response(
            "invalid_summary_language",
            str(exc) or "summary language is not supported",
            422,
            exc.details,
        )

@router.post("/api/rooms/{room_id}/join", response_model=JoinRoomResponse)
async def join_room(
    room_id: str,
    req: JoinRoomRequest,
    request: Request,
    service: RoomService = Depends(get_room_service),
    session: Optional[Dict[str, Any]] = Depends(require_user),
):
    user_id = _session_user_id(session)
    try:
        return await service.join_room(
            room_id,
            req.display_name,
            req.language,
            req.client,
            user_id=user_id,
            password=req.password,
            client_ip=_client_ip(request),
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except RoomPasswordRequiredError:
        return _error_response("room_password_required", "This meeting requires a password.", 403)
    except InvalidRoomPasswordError:
        return _error_response("invalid_room_password", "Incorrect meeting password.", 403)
    except RoomPasswordRateLimitedError as exc:
        response = _error_response(
            "room_password_rate_limited",
            "Too many incorrect password attempts. Please wait a few minutes and try again.",
            429,
        )
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response
    except RoomExpiredError:
        return _error_response(
            "room_expired",
            "Room meeting duration has expired. Please create a new room.",
            410,
        )
    except RoomFullError:
        return _error_response("room_full", "Room is full", 409)
    except InvalidLanguageError as exc:
        return _error_response(
            "invalid_language",
            str(exc) or "Invalid language",
            422,
            exc.details or {"field": "language"},
        )


@router.post("/api/rooms/{room_id}/brse/enable", response_model=CreateRoomResponseRoom)
async def enable_brse(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    try:
        return await service.set_brse_enabled(
            room_id,
            True,
            actor_participant_id=claims.get("participant_id"),
            session_id=claims.get("session_id"),
            reason="rest_enable",
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except BrseToggleForbiddenError as exc:
        status_code = 409 if exc.code == "session_mismatch" else 403
        return _error_response(exc.code, str(exc), status_code)


@router.post("/api/rooms/{room_id}/brse/disable", response_model=CreateRoomResponseRoom)
async def disable_brse(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    try:
        return await service.set_brse_enabled(
            room_id,
            False,
            actor_participant_id=claims.get("participant_id"),
            session_id=claims.get("session_id"),
            reason="rest_disable",
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except BrseToggleForbiddenError as exc:
        status_code = 409 if exc.code == "session_mismatch" else 403
        return _error_response(exc.code, str(exc), status_code)

@router.patch("/api/rooms/{room_id}/relay-mode", response_model=CreateRoomResponseRoom)
async def update_relay_mode(
    room_id: str,
    body: UpdateRelayModeRequest,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    try:
        return await service.set_relay_mode(
            room_id,
            body.mode,
            actor_participant_id=claims.get("participant_id"),
            session_id=claims.get("session_id"),
            reason="rest_relay_mode",
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except RoomExpiredError:
        return _error_response("room_expired", "This meeting has ended.", 409)
    except RelayModeNotSupportedError as exc:
        return _error_response(exc.code, str(exc), 422)
    except BrseToggleForbiddenError as exc:
        status_code = 409 if exc.code == "session_mismatch" else 403
        return _error_response(exc.code, str(exc), status_code)


@router.delete("/api/rooms/{room_id}/leave", status_code=204)
async def leave_room(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service)
):
    participant_id = claims.get("participant_id")
    session_id = claims.get("session_id")
    await service.leave_room(room_id, participant_id, session_id=session_id)
    return Response(status_code=204)


@router.post("/api/rooms/{room_id}/screen-share/start", response_model=ScreenShareStateResponse)
async def start_screen_share(
    room_id: str,
    req: ScreenShareStartRequest,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    participant_id = claims.get("participant_id")
    session_id = claims.get("session_id")
    try:
        ok = await service.start_screen_share(
            room_id=room_id,
            participant_id=participant_id,
            session_id=session_id,
            track_sid=req.track_sid,
            track_name=req.track_name,
            source=req.source,
        )
        if not ok:
            return _error_response("session_mismatch", "Session no longer valid for participant", 409)

        return ScreenShareStateResponse(
            participant_id=participant_id,
            display_name=claims.get("display_name", participant_id),
            active=True,
            timestamp=service._now_str(),
            track_sid=req.track_sid,
            track_name=req.track_name,
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except ParticipantNotFoundError:
        return _error_response("participant_not_found", "Participant not found in room", 404)


@router.post("/api/rooms/{room_id}/screen-share/stop", response_model=ScreenShareStateResponse)
async def stop_screen_share(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    service: RoomService = Depends(get_room_service),
):
    participant_id = claims.get("participant_id")
    session_id = claims.get("session_id")
    try:
        ok = await service.stop_screen_share(
            room_id=room_id,
            participant_id=participant_id,
            session_id=session_id,
            reason="rest_stop",
        )
        if not ok:
            return _error_response("session_mismatch", "Session no longer valid for participant", 409)

        return ScreenShareStateResponse(
            participant_id=participant_id,
            display_name=claims.get("display_name", participant_id),
            active=False,
            timestamp=service._now_str(),
        )
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except ParticipantNotFoundError:
        return _error_response("participant_not_found", "Participant not found in room", 404)
