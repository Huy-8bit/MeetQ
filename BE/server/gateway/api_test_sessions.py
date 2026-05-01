"""
REST endpoints for mic-test and translation-test sessions.

POST /api/test/mic                   -> create mic test session
DELETE /api/test/mic/{session_id}    -> stop / delete mic test session
POST /api/test/translation           -> create translation test session
DELETE /api/test/translation/{session_id} -> stop / delete translation test session

These sessions are independent of the meeting room flow.
No room join, no LiveKit subscription required.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.gateway.app_state import app_state
from server.meeting_modes import SUPPORTED_MEETING_LANGUAGES
from server.models import (
    CreateMicTestSessionResponse,
    CreateTranslationTestRequest,
    CreateTranslationTestSessionResponse,
)

router = APIRouter(prefix="/api/test", tags=["test-sessions"])

_SUPPORTED_LANGS = tuple(SUPPORTED_MEETING_LANGUAGES)
_SUPPORTED_LANG_SET = set(_SUPPORTED_LANGS)


# ------------------------------------------------------------------
# Mic test
# ------------------------------------------------------------------

@router.post("/mic", response_model=CreateMicTestSessionResponse, status_code=201)
async def create_mic_test_session() -> CreateMicTestSessionResponse:
    """
    Create a mic-test session.

    FE uses the returned `websocket.url` to connect and begin streaming
    raw PCM16 audio. The server will reply with `mic_test.level` events
    so FE can display a real input meter confirming server-side audio ingress.

    Session lifecycle: created -> active -> stopped -> (auto-expired after 15 min)
    """
    store = _require_store()
    session = await store.create_mic_session()
    return CreateMicTestSessionResponse(
        session_id=session.session_id,
        status=session.status,
        created_at=session.created_at,
        expires_at=session.expires_at,
        websocket={"url": f"/ws/test/mic/{session.session_id}"},
    )


@router.delete("/mic/{session_id}", status_code=204)
async def delete_mic_test_session(session_id: str) -> None:
    """Stop and delete a mic-test session. Idempotent."""
    store = _require_store()
    await store.delete_mic_session(session_id)


# ------------------------------------------------------------------
# Translation test
# ------------------------------------------------------------------

@router.post(
    "/translation",
    response_model=CreateTranslationTestSessionResponse,
    status_code=201,
)
async def create_translation_test_session(
    body: CreateTranslationTestRequest,
) -> CreateTranslationTestSessionResponse:
    """
    Create a translation-test session.

    FE must provide explicit platform-supported `src_lang` and `tgt_lang`.
    FE uses the returned `websocket.url` to connect and stream PCM16 audio.
    The server processes audio through the realtime translation pipeline and
    replies with `translation_test.partial` and `translation_test.final` events.

    Translation-only mode: the AI is strictly instructed to translate,
    never to reply as an assistant.

    Session lifecycle: created -> listening -> translating -> completed -> (auto-expired after 15 min)
    """
    if body.src_lang not in _SUPPORTED_LANG_SET:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "invalid_language",
                    "message": f"src_lang must be one of {', '.join(_SUPPORTED_LANGS)}",
                    "details": {"field": "src_lang", "supported": list(_SUPPORTED_LANGS)},
                }
            },
        )
    if body.tgt_lang not in _SUPPORTED_LANG_SET:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "invalid_language",
                    "message": f"tgt_lang must be one of {', '.join(_SUPPORTED_LANGS)}",
                    "details": {"field": "tgt_lang", "supported": list(_SUPPORTED_LANGS)},
                }
            },
        )
    if body.src_lang == body.tgt_lang:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "invalid_language",
                    "message": "src_lang and tgt_lang must be different",
                    "details": {"field": "tgt_lang"},
                }
            },
        )

    store = _require_store()
    session = await store.create_translation_session(
        src_lang=body.src_lang, tgt_lang=body.tgt_lang
    )
    return CreateTranslationTestSessionResponse(
        session_id=session.session_id,
        src_lang=session.src_lang,
        tgt_lang=session.tgt_lang,
        status=session.status,
        created_at=session.created_at,
        expires_at=session.expires_at,
        websocket={"url": f"/ws/test/translation/{session.session_id}"},
    )


@router.delete("/translation/{session_id}", status_code=204)
async def delete_translation_test_session(session_id: str) -> None:
    """Stop and delete a translation-test session. Idempotent."""
    store = _require_store()
    await store.delete_translation_session(session_id)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _require_store():
    if app_state.test_session_store is None:
        raise HTTPException(status_code=503, detail={"error": {"code": "redis_unavailable", "message": "Test session store not initialized"}})
    return app_state.test_session_store
