from typing import Optional, TYPE_CHECKING
from redis.asyncio import Redis
from server.config import Settings
from server.service.gateway.room_store import RoomStore
from server.service.gateway.room_service import RoomService
from server.service.gateway.ws_hub import WSHub

if TYPE_CHECKING:
    from server.service.gateway.test_session_store import TestSessionStore
    from server.service.persistence.room_history import MongoRoomHistoryRepository
    from server.service.ops.recorder import OpsRecorder


class AppState:
    settings: Optional[Settings] = None
    redis: Optional[Redis] = None
    room_store: Optional[RoomStore] = None
    room_service: Optional[RoomService] = None
    mongo_client: Optional[object] = None
    room_history: Optional["MongoRoomHistoryRepository"] = None
    ws_hub: Optional[WSHub] = None
    test_session_store: Optional["TestSessionStore"] = None
    ops_recorder: Optional["OpsRecorder"] = None
    # server.service.admin.dependencies.AdminContext, built at startup.
    admin_context: Optional[object] = None
    # Meeting recording / archive / retention (server/service/archive), built at startup.
    archive_repo: Optional[object] = None
    archive_storage: Optional[object] = None
    recording_service: Optional[object] = None
    archive_service: Optional[object] = None
    archive_worker: Optional[object] = None


app_state = AppState()
