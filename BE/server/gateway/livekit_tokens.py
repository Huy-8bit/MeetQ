import json
from datetime import timedelta
from livekit.api import AccessToken, VideoGrants

def generate_livekit_token(
    room_name: str,
    participant_id: str,
    participant_name: str,
    language: str,
    api_key: str,
    api_secret: str,
    ttl_seconds: int = 86400,
    kind: str = "human",
) -> str:
    grant = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=False
    )
    
    metadata = {
        "participant_id": participant_id,
        "language": language,
        "kind": kind,
        "room_id": room_name,
    }

    access_token = (
        AccessToken(api_key, api_secret)
        .with_identity(participant_id)
        .with_name(participant_name)
        .with_grants(grant)
        .with_metadata(json.dumps(metadata))
        .with_ttl(timedelta(seconds=ttl_seconds))
    )
    
    return access_token.to_jwt()
