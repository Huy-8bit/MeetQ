from fastapi import Depends, Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from server.service.gateway.app_state import app_state
from server.config import Settings
from server.service.gateway.room_store import RoomStore
from server.service.gateway.room_service import RoomService
from server.service.gateway.auth import verify_room_token, InvalidTokenError, ExpiredTokenError, TokenRoomMismatchError
from typing import Dict, Any

security = HTTPBearer()

def get_settings() -> Settings:
    if not app_state.settings:
        raise RuntimeError("Settings not initialized")
    return app_state.settings

def get_room_store() -> RoomStore:
    if not app_state.room_store:
        raise RuntimeError("RoomStore not initialized")
    return app_state.room_store

def get_room_service() -> RoomService:
    if not app_state.room_service:
        raise RuntimeError("RoomService not initialized")
    return app_state.room_service

def verify_token_dependency(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security),
    settings: Settings = Depends(get_settings)
) -> Dict[str, Any]:
    room_id = request.path_params.get("room_id")
    try:
        claims = verify_room_token(credentials.credentials, settings.room_jwt_secret, room_id)
        return claims
    except ExpiredTokenError:
        raise HTTPException(status_code=401, detail={"error": {"code": "invalid_token", "message": "token expired"}})
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail={"error": {"code": "invalid_token", "message": "invalid token"}})
    except TokenRoomMismatchError:
        raise HTTPException(status_code=403, detail={"error": {"code": "token_room_mismatch", "message": "room mismatch"}})
