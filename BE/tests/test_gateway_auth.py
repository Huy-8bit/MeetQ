import pytest
import time
import json
from jose import jwt
from server.service.gateway.auth import (
    issue_room_token,
    verify_room_token,
    InvalidTokenError,
    ExpiredTokenError,
    TokenRoomMismatchError
)
from server.service.gateway.livekit_tokens import generate_livekit_token
from server.config import Settings

def test_room_token_valid(fake_settings: Settings):
    token = issue_room_token(
        "rm_123", "pt_abc", "ses_xyz", "Test User", "vi",
        fake_settings.room_jwt_secret, 3600
    )
    claims = verify_room_token(token, fake_settings.room_jwt_secret, "rm_123")
    assert claims["room_id"] == "rm_123"
    assert claims["participant_id"] == "pt_abc"
    assert claims["language"] == "vi"

def test_room_token_expired(fake_settings: Settings):
    token = issue_room_token(
        "rm_123", "pt_abc", "ses_xyz", "Test User", "vi",
        fake_settings.room_jwt_secret, -1 # immediately expired
    )
    with pytest.raises(ExpiredTokenError):
        verify_room_token(token, fake_settings.room_jwt_secret, "rm_123")

def test_room_token_wrong_signature(fake_settings: Settings):
    token = issue_room_token(
        "rm_123", "pt_abc", "ses_xyz", "Test User", "vi",
        "wrong-secret", 3600
    )
    with pytest.raises(InvalidTokenError):
        verify_room_token(token, fake_settings.room_jwt_secret, "rm_123")

def test_room_token_wrong_room(fake_settings: Settings):
    token = issue_room_token(
        "rm_123", "pt_abc", "ses_xyz", "Test User", "vi",
        fake_settings.room_jwt_secret, 3600
    )
    with pytest.raises(TokenRoomMismatchError):
        verify_room_token(token, fake_settings.room_jwt_secret, "rm_wrong")

def test_generate_livekit_token(fake_settings: Settings):
    token = generate_livekit_token(
        room_name="rm_123",
        participant_id="pt_abc",
        participant_name="Test User",
        language="vi",
        api_key=fake_settings.livekit_api_key,
        api_secret=fake_settings.livekit_api_secret,
        ttl_seconds=3600
    )
    
    # decode the jwt without verifying signature just to check claims
    claims = jwt.get_unverified_claims(token)
    assert claims["sub"] == "pt_abc"
    assert claims["name"] == "Test User"
    
    video_grants = claims.get("video", {})
    assert video_grants.get("roomJoin") is True
    assert video_grants.get("room") == "rm_123"
    assert video_grants.get("canPublish") is True
    
    metadata = json.loads(claims.get("metadata", "{}"))
    assert metadata["participant_id"] == "pt_abc"
    assert metadata["language"] == "vi"
    assert metadata["kind"] == "human"
