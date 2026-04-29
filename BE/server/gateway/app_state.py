from typing import Optional
from redis.asyncio import Redis
from server.config import Settings
from server.gateway.room_store import RoomStore
from server.gateway.room_service import RoomService
from server.gateway.ws_hub import WSHub

class AppState:
    settings: Optional[Settings] = None
    redis: Optional[Redis] = None
    room_store: Optional[RoomStore] = None
    room_service: Optional[RoomService] = None
    ws_hub: Optional[WSHub] = None

app_state = AppState()
