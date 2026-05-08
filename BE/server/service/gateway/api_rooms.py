from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse
from server.service.gateway.room_service import (
    BrseToggleForbiddenError,
    InvalidLanguageError,
    InvalidMeetingLanguagesError,
    InvalidMeetingSummaryTypeError,
    MeetingSummaryNotFoundError,
    MeetingSummaryNotReadyError,
    MeetingSummaryUnavailableError,
    ParticipantNotFoundError,
    RoomExpiredError,
    RoomFullError,
    RoomNotFoundError,
    RoomService,
)
from server.service.gateway.dependencies import get_room_service, verify_token_dependency
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

@router.post("/api/rooms", response_model=CreateRoomResponse)
async def create_room(
    req: Optional[CreateRoomRequest] = Body(default=None),
    service: RoomService = Depends(get_room_service),
):
    try:
        payload = req or CreateRoomRequest()
        return await service.create_room(
            payload.meeting_languages,
            payload.brse_enabled,
            payload.brse_mode,
            payload.brse_output_mode,
        )
    except InvalidMeetingLanguagesError as exc:
        return _error_response("invalid_meeting_languages", str(exc), 422, exc.details)

@router.get("/api/rooms/{room_id}", response_model=RoomSnapshotResponse)
async def get_room(room_id: str, service: RoomService = Depends(get_room_service)):
    try:
        return await service.get_room(room_id)
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)


@router.get("/api/rooms/{room_id}/summary", response_model=MeetingSummaryResponse)
async def get_room_summary(
    room_id: str,
    type: str = "final",
    service: RoomService = Depends(get_room_service),
):
    try:
        return await service.get_meeting_summary(room_id, type)
    except MeetingSummaryNotFoundError:
        return _error_response("meeting_summary_not_found", "Meeting summary not found", 404)
    except InvalidMeetingSummaryTypeError:
        return _error_response("invalid_summary_type", "summary type must be interim or final", 422)


@router.post("/api/rooms/{room_id}/summary", response_model=MeetingSummaryResponse)
async def generate_room_summary(
    room_id: str,
    type: Optional[str] = None,
    service: RoomService = Depends(get_room_service),
):
    try:
        return await service.generate_meeting_summary(room_id, type)
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

@router.post("/api/rooms/{room_id}/join", response_model=JoinRoomResponse)
async def join_room(room_id: str, req: JoinRoomRequest, service: RoomService = Depends(get_room_service)):
    try:
        return await service.join_room(room_id, req.display_name, req.language, req.client)
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
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
