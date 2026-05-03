from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError, ExpiredSignatureError
from typing import Dict, Any

class InvalidTokenError(Exception):
    pass

class ExpiredTokenError(Exception):
    pass

class TokenRoomMismatchError(Exception):
    pass

def issue_room_token(
    room_id: str,
    participant_id: str,
    session_id: str,
    display_name: str,
    language: str,
    secret: str,
    ttl_seconds: int
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "room_id": room_id,
        "participant_id": participant_id,
        "session_id": session_id,
        "display_name": display_name,
        "language": language,
        "exp": now + timedelta(seconds=ttl_seconds),
        "iat": now
    }
    return jwt.encode(claims, secret, algorithm="HS256")

def verify_room_token(token: str, secret: str, expected_room_id: str = None) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise ExpiredTokenError("Token has expired")
    except JWTError as e:
        raise InvalidTokenError(f"Invalid token: {e}")
        
    if expected_room_id and claims.get("room_id") != expected_room_id:
        raise TokenRoomMismatchError("Token does not match the requested room")
        
    return claims
