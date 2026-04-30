from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from server.gateway.room_service import (
    RoomService, RoomFullError, InvalidLanguageError, RoomNotFoundError, ParticipantNotFoundError
)
from server.gateway.dependencies import get_room_service, verify_token_dependency
from server.models import (
    CreateRoomResponse,
    RoomSnapshotResponse,
    JoinRoomRequest,
    JoinRoomResponse,
    ScreenShareStartRequest,
    ScreenShareStateResponse,
)
from typing import Dict, Any

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
async def create_room(service: RoomService = Depends(get_room_service)):
    return await service.create_room()

@router.get("/api/rooms/{room_id}", response_model=RoomSnapshotResponse)
async def get_room(room_id: str, service: RoomService = Depends(get_room_service)):
    try:
        return await service.get_room(room_id)
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)

@router.post("/api/rooms/{room_id}/join", response_model=JoinRoomResponse)
async def join_room(room_id: str, req: JoinRoomRequest, service: RoomService = Depends(get_room_service)):
    try:
        return await service.join_room(room_id, req.display_name, req.language, req.client)
    except RoomNotFoundError:
        return _error_response("room_not_found", "Room not found", 404)
    except RoomFullError:
        return _error_response("room_full", "Room is full", 409)
    except InvalidLanguageError:
        return _error_response("invalid_language", "Invalid language", 422, {"field": "language"})

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
