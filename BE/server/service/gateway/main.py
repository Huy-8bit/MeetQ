import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from server.config import get_settings
from server.integrations.mongodb import close_mongo_client, create_mongo_client, get_mongo_database
from server.redis import create_redis_client, close_redis
from server.service.gateway.app_state import app_state
from server.service.gateway.room_store import RoomStore
from server.service.gateway.room_service import RoomService
from server.service.gateway.ws_hub import WSHub
from server.service.gateway.test_session_store import TestSessionStore
from server.service.gateway.api_health import router as health_router
from server.service.gateway.api_config import router as config_router
from server.service.admin.api import router as admin_router
from server.service.auth.api import admin_auth_router, user_router as auth_router
from server.service.archive.setup import build_archive_services, install as install_archive_services
from server.service.archive.api import meetings_router, recordings_router
from server.service.admin.archives_api import router as admin_archives_router
from server.service.gateway.origins import UNSAFE_METHODS, cors_allowed_origins, origin_is_trusted
from server.service.admin.dependencies import build_admin_context
from server.service.admin.errors import AdminApiError
from server.service.admin.livekit_inspector import LiveKitInspector
from server.service.ops.recorder import OpsRecorder
from server.service.gateway.api_rooms import router as rooms_router
from server.service.gateway.api_test_sessions import router as test_sessions_router
from server.service.gateway.ws_endpoint import router as ws_router
from server.service.gateway.ws_test_mic import router as ws_mic_router
from server.service.gateway.ws_test_translation import router as ws_translation_router
from server.service.gateway.event_consumer import start_event_consumer
from server.service.persistence.room_history import MongoRoomHistoryRepository
import logging
import os
import time
import uuid


def _configure_logging() -> None:
    # Uvicorn only configures its own loggers; without this, application INFO logs
    # (room lifecycle, relay mode changes, admin access) were never emitted.
    root = logging.getLogger()
    if root.handlers:
        return
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()
admin_logger = logging.getLogger("server.service.admin.access")
logger = logging.getLogger("server.service.gateway.main")


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
    app_state.mongo_client = create_mongo_client(app_state.settings)
    mongo_db = get_mongo_database(app_state.mongo_client, app_state.settings)
    app_state.room_history = MongoRoomHistoryRepository(mongo_db)
    app_state.room_history.schedule(
        app_state.room_history.ensure_indexes,
        action="ensure_indexes",
        room_id="__startup__",
    )
    room_ttl_seconds = app_state.settings.room_meeting_duration_seconds + 300
    app_state.room_store = RoomStore(app_state.redis, ttl_seconds=room_ttl_seconds)
    app_state.ops_recorder = OpsRecorder(
        app_state.redis,
        mongo_db,
        room_ttl_seconds=room_ttl_seconds,
        retention_days=app_state.settings.ops_event_retention_days,
    )
    app_state.room_history.schedule(
        app_state.ops_recorder.ensure_indexes,
        action="ensure_ops_indexes",
        room_id="__startup__",
    )
    app_state.room_service = RoomService(
        app_state.room_store,
        app_state.settings,
        app_state.redis,
        room_history=app_state.room_history,
        ops_recorder=app_state.ops_recorder,
    )
    app_state.admin_context = build_admin_context(inspector=LiveKitInspector(app_state.settings))
    app_state.room_history.schedule(
        app_state.admin_context.history.ensure_indexes,
        action="ensure_admin_indexes",
        room_id="__startup__",
    )
    app_state.ws_hub = WSHub(
        on_connection_lost=_on_ws_connection_lost,
        stale_timeout_seconds=app_state.settings.ws_stale_timeout_seconds,
    )
    app_state.test_session_store = TestSessionStore(app_state.redis)

    # Meeting recording, archive and retention (server/service/archive).
    archive_services = build_archive_services(
        app_state.settings,
        redis=app_state.redis,
        mongo_db=mongo_db,
        store=app_state.room_store,
        ops_recorder=app_state.ops_recorder,
    )
    install_archive_services(archive_services)
    if archive_services["repo"].enabled:
        app_state.room_history.schedule(
            archive_services["repo"].ensure_indexes,
            action="ensure_archive_indexes",
            room_id="__startup__",
        )
        app_state.room_service.room_end_listeners.append(
            lambda room_id, reason: archive_services["recordings"].stop_for_room_end(room_id, reason)
        )
        archive_services["worker"].start()
    if archive_services["storage"] is not None and app_state.settings.s3_create_bucket:
        try:
            await archive_services["storage"].ensure_private_bucket()
        except Exception:
            logger.exception("local archive bucket could not be created")

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

    if app_state.archive_worker:
        await app_state.archive_worker.stop()
    provider = getattr(app_state.recording_service, "provider", None)
    if provider is not None:
        await provider.aclose()
    if app_state.room_service:
        await app_state.room_service.shutdown_side_effects()
    if app_state.ops_recorder:
        await app_state.ops_recorder.shutdown()
    if app_state.room_history:
        await app_state.room_history.shutdown()

    if app_state.redis:
        await close_redis(app_state.redis)
    close_mongo_client(app_state.mongo_client)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(lifespan=lifespan)

@app.exception_handler(AdminApiError)
async def admin_api_error_handler(request: Request, exc: AdminApiError):
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


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
    
    # Never echo the submitted values back (`input`/`ctx` can carry e.g. a room password).
    safe_errors = [
        {
            "loc": list(error.get("loc", [])),
            "msg": str(error.get("msg", "")).removeprefix("Value error, "),
            "type": error.get("type"),
        }
        for error in errors
    ]
    password_error = next(
        (error for error in safe_errors if "password" in error["loc"] or "password" in error["msg"].lower()),
        None,
    )
    if password_error is not None:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_room_password_setting",
                    "message": password_error["msg"],
                    "details": {"field": "password"},
                }
            },
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Validation error",
                "details": {"errors": safe_errors}
            }
        }
    )

_TRUSTED_ORIGINS = cors_allowed_origins()


@app.middleware("http")
async def reject_untrusted_origin(request: Request, call_next):
    """CSRF guard for cookie sessions: unsafe methods only from trusted frontends."""
    if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
        if not origin_is_trusted(request.headers.get("origin"), _TRUSTED_ORIGINS):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "origin_not_allowed", "message": "Request origin is not allowed."}},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_TRUSTED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    if request.url.path.startswith("/api/admin"):
        # Structured access log for the admin API (no query values: they may hold search terms).
        admin_logger.info(
            "admin_api request_id=%s method=%s path=%s status=%s duration_ms=%d",
            req_id,
            request.method,
            request.url.path,
            response.status_code,
            int((time.monotonic() - started) * 1000),
        )
    return response

app.include_router(health_router)
app.include_router(config_router)
app.include_router(auth_router)
app.include_router(admin_auth_router)
app.include_router(admin_archives_router)
app.include_router(admin_router)
app.include_router(recordings_router)
app.include_router(meetings_router)
app.include_router(rooms_router)
app.include_router(test_sessions_router)
app.include_router(ws_router)
app.include_router(ws_mic_router)
app.include_router(ws_translation_router)
