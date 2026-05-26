import pytest
import os
from typing import Dict, Any, AsyncGenerator, List
from unittest.mock import AsyncMock, MagicMock
from jose import jwt
from datetime import datetime, timedelta, timezone

from server.config import Settings
from server.models import RoomState, ParticipantState

@pytest.fixture
def fake_settings() -> Settings:
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ROOM_JWT_SECRET"] = "test-jwt-secret"
    os.environ["ROOM_TOKEN_TTL_SECONDS"] = "3600"
    os.environ["REDIS_URL"] = "redis://localhost:6379"
    os.environ["LIVEKIT_API_KEY"] = "test-lk-key"
    os.environ["LIVEKIT_API_SECRET"] = "test-lk-secret"
    os.environ["LIVEKIT_WS_URL_PUBLIC"] = "ws://localhost:7880"
    os.environ["LIVEKIT_WS_URL_INTERNAL"] = "ws://localhost:7880"
    return Settings()

class FakePipeline:
    def __init__(self, parent):
        self.parent = parent
        self.commands = []
        
    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        
    def rpush(self, key, value):
        self.commands.append(("rpush", key, value))
        
    def ltrim(self, key, start, end):
        self.commands.append(("ltrim", key, start, end))
        
    async def execute(self):
        for cmd in self.commands:
            if cmd[0] == "expire":
                pass
            elif cmd[0] == "rpush":
                if cmd[1] not in self.parent.data:
                    self.parent.data[cmd[1]] = []
                self.parent.data[cmd[1]].append(cmd[2])
            elif cmd[0] == "ltrim":
                if cmd[1] in self.parent.data:
                    lst = self.parent.data[cmd[1]]
                    start, end = cmd[2], cmd[3]
                    if end == -1:
                        self.parent.data[cmd[1]] = lst[start:]
                    else:
                        self.parent.data[cmd[1]] = lst[start:end+1]

class FakeRedis:
    def __init__(self):
        self.data: Dict[str, Any] = {}
    
    async def get(self, key: str) -> Any:
        return self.data.get(key)
        
    async def set(self, key: str, value: str, ex: int = None) -> None:
        self.data[key] = value
        
    async def hset(self, name: str, key: str, value: str) -> None:
        if name not in self.data:
            self.data[name] = {}
        self.data[name][key] = value

    async def hget(self, name: str, key: str) -> Any:
        return self.data.get(name, {}).get(key)

    async def hdel(self, name: str, key: str) -> None:
        if name in self.data:
            self.data[name].pop(key, None)
        
    async def hgetall(self, name: str) -> Dict[str, str]:
        return self.data.get(name, {})

    async def delete(self, *names: str) -> None:
        for name in names:
            self.data.pop(name, None)
            
    async def lrange(self, name: str, start: int, end: int) -> List[str]:
        lst = self.data.get(name, [])
        if end == -1:
            return lst[start:]
        return lst[start:end+1]

    def pipeline(self):
        return FakePipeline(self)
        
    async def publish(self, channel: str, message: str) -> int:
        return 1

    def pubsub(self):
        class FakePubSub:
            async def subscribe(self, *args):
                pass
            async def unsubscribe(self, *args):
                pass
            async def listen(self):
                # Never yield to block the consumer task instead of dying
                import asyncio
                await asyncio.sleep(86400)
                yield {"type": "not_message"}
        return FakePubSub()

    async def ping(self) -> bool:
        return True
        
    async def aclose(self) -> None:
        pass

@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()

@pytest.fixture
def gateway_app(fake_settings, fake_redis):
    # Lazy import to avoid error before GTW-004 is implemented
    try:
        from server.service.gateway.main import app
        from fastapi.testclient import TestClient
        from server.service.gateway.app_state import app_state
        from server.service.gateway.room_store import RoomStore
        from server.service.gateway.room_service import RoomService
        from server.service.gateway.ws_hub import WSHub
        
        # Override app_state for tests
        app_state.settings = fake_settings
        app_state.redis = fake_redis
        app_state.room_store = RoomStore(fake_redis, ttl_seconds=fake_settings.room_token_ttl_seconds)
        app_state.room_service = RoomService(app_state.room_store, fake_settings, fake_redis)
        app_state.ws_hub = WSHub()
        
        # We don't use the TestClient as a context manager because it would trigger lifespan and overwrite app_state
        # Or we can just return it. 
        return TestClient(app)
    except ImportError:
        return None

# LiveKit Stubs
class StubRoom:
    def __init__(self):
        self.participants = {}
        self.local_participant = AsyncMock()
        
    async def connect(self, url, token):
        pass

    async def disconnect(self):
        pass
        
    def on(self, event, callback):
        pass

class StubAudioStream:
    def __init__(self):
        pass
        
    async def __aiter__(self):
        yield MagicMock()

class StubAudioSource:
    def __init__(self):
        pass

@pytest.fixture
def livekit_stubs():
    return {
        "room": StubRoom,
        "audio_stream": StubAudioStream,
        "audio_source": StubAudioSource
    }

@pytest.fixture
def create_room_jwt(fake_settings: Settings):
    def _create(room_id: str, participant_id: str, session_id: str) -> str:
        claims = {
            "room_id": room_id,
            "participant_id": participant_id,
            "session_id": session_id,
            "exp": datetime.now(timezone.utc) + timedelta(seconds=fake_settings.room_token_ttl_seconds)
        }
        return jwt.encode(claims, fake_settings.room_jwt_secret, algorithm="HS256")
    return _create
