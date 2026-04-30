import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from server.config import get_settings
from server.redis import create_redis_client, close_redis
from server.gateway.app_state import app_state
from server.gateway.room_store import RoomStore
from server.gateway.room_service import RoomService
from server.gateway.ws_hub import WSHub
from server.gateway.test_session_store import TestSessionStore
from server.gateway.api_health import router as health_router
from server.gateway.api_rooms import router as rooms_router
from server.gateway.api_test_sessions import router as test_sessions_router
from server.gateway.ws_endpoint import router as ws_router
from server.gateway.ws_test_mic import router as ws_mic_router
from server.gateway.ws_test_translation import router as ws_translation_router
from server.gateway.event_consumer import start_event_consumer
import uuid


async def _on_ws_connection_lost(room_id: str, participant_id: str, session_id: str, reason: str):
    if not app_state.room_service:
        return
    await app_state.room_service.cleanup_participant(
        room_id=room_id,
        participant_id=participant_id,
        session_id=session_id,
        reason=f"ws_{reason}",
    )


async def _ws_stale_sweeper():
    while True:
        await asyncio.sleep(max(app_state.settings.ws_stale_sweep_interval_seconds, 5))
        if app_state.ws_hub:
            await app_state.ws_hub.close_stale_connections()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app_state.settings = get_settings()
    app_state.redis = await create_redis_client(app_state.settings.redis_url)
    app_state.room_store = RoomStore(app_state.redis, ttl_seconds=app_state.settings.room_token_ttl_seconds)
    app_state.room_service = RoomService(app_state.room_store, app_state.settings, app_state.redis)
    app_state.ws_hub = WSHub(
        on_connection_lost=_on_ws_connection_lost,
        stale_timeout_seconds=app_state.settings.ws_stale_timeout_seconds,
    )
    app_state.test_session_store = TestSessionStore(app_state.redis)

    # Start consumer
    consumer_task = asyncio.create_task(start_event_consumer(app_state.redis))
    stale_sweeper_task = asyncio.create_task(_ws_stale_sweeper())

    yield
    # Shutdown
    consumer_task.cancel()
    stale_sweeper_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    try:
        await stale_sweeper_task
    except asyncio.CancelledError:
        pass

    if app_state.redis:
        await close_redis(app_state.redis)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    # Check if it's a language error
    for error in errors:
        if "language" in error.get("loc", []):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "invalid_language",
                        "message": error.get("msg"),
                        "details": {"field": "language"}
                    }
                }
            )
    
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Validation error",
                "details": {"errors": errors}
            }
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

app.include_router(health_router)
app.include_router(rooms_router)
app.include_router(test_sessions_router)
app.include_router(ws_router)
app.include_router(ws_mic_router)
app.include_router(ws_translation_router)

