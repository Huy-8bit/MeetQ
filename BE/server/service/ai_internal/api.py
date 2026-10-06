"""Internal AI API for Go Backend -> Python AI integration.

Endpoints:
- POST /internal/ai/rooms/{room_id}/summary
- POST /internal/ai/rooms/{room_id}/final-summary
- POST /internal/ai/chat/translate
- GET  /internal/ai/health

Protected by X-Internal-Service-Token header if configured.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from server.config import Settings
from server.service.gateway.app_state import app_state
from server.service.gateway.chat_translator import translate_chat_message
from server.service.gateway.dependencies import get_room_service, get_settings
from server.service.gateway.room_service import (
    InvalidMeetingSummaryLanguageError,
    InvalidMeetingSummaryTypeError,
    MeetingSummaryNotFoundError,
    MeetingSummaryNotReadyError,
    MeetingSummaryUnavailableError,
    RoomNotFoundError,
    RoomService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/ai", tags=["internal-ai"])


def verify_service_token(
    settings: Settings = Depends(get_settings),
    x_internal_service_token: Optional[str] = Header(None, alias="X-Internal-Service-Token"),
) -> None:
    expected = settings.python_ai_service_token
    if expected:
        if not x_internal_service_token or x_internal_service_token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Invalid or missing service token"}},
            )


class SummaryRequest(BaseModel):
    type: Optional[str] = None
    language: Optional[str] = None
    requester_participant_id: Optional[str] = None
    requester_language: Optional[str] = None


class FinalSummaryRequest(BaseModel):
    trigger_reason: str = Field(default="room_expired")
    ended_at: Optional[str] = None
    requester_language: Optional[str] = None


class TranslateChatRequest(BaseModel):
    room_id: str
    text: str
    src_lang: str
    room_languages: List[str] = Field(default_factory=list)


@router.get("/health", dependencies=[Depends(verify_service_token)])
async def ai_health():
    return {"status": "ok"}


@router.post("/rooms/{room_id}/summary", dependencies=[Depends(verify_service_token)])
async def generate_summary(
    room_id: str,
    req: SummaryRequest,
    service: RoomService = Depends(get_room_service),
):
    try:
        requester_claims = None
        if req.requester_participant_id or req.requester_language:
            requester_claims = {
                "participant_id": req.requester_participant_id,
                "language": req.requester_language,
            }
        summary_resp = await service.generate_meeting_summary(
            room_id,
            summary_type=req.type,
            requested_language=req.language,
            requester_claims=requester_claims,
        )
        return summary_resp.model_dump()
    except RoomNotFoundError:
        return JSONResponse(status_code=404, content={"error": {"code": "room_not_found", "message": "Room not found"}})
    except MeetingSummaryUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "meeting_summary_unavailable", "message": "Meeting summary persistence is unavailable"}},
        )
    except MeetingSummaryNotReadyError:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "meeting_summary_not_ready", "message": "Final summary can only be generated after room end"}},
        )
    except MeetingSummaryNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "meeting_summary_not_found", "message": "Meeting summary not found"}},
        )
    except InvalidMeetingSummaryTypeError:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_summary_type", "message": "summary type must be interim or final"}},
        )
    except InvalidMeetingSummaryLanguageError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_summary_language",
                    "message": str(exc) or "summary language is not supported",
                    "details": exc.details,
                }
            },
        )
    except Exception as exc:
        logger.exception("internal generate summary error room_id=%s: %s", room_id, exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": str(exc)}},
        )


@router.post("/rooms/{room_id}/final-summary", dependencies=[Depends(verify_service_token)])
async def request_final_summary(
    room_id: str,
    req: FinalSummaryRequest,
    service: RoomService = Depends(get_room_service),
):
    summary_service = service.summary_service
    if summary_service and summary_service.enabled:
        summary_service.schedule_for_room_end(
            room_id=room_id,
            trigger_reason=req.trigger_reason,
            ended_at=req.ended_at,
            summary_language=req.requester_language,
        )
    return {"status": "accepted", "room_id": room_id}


@router.post("/chat/translate", dependencies=[Depends(verify_service_token)])
async def translate_chat(
    req: TranslateChatRequest,
    settings: Settings = Depends(get_settings),
):
    target_langs = [l for l in req.room_languages if l != req.src_lang]
    translations = []
    api_key = settings.openai_api_key
    if not api_key:
        return {"translations": []}

    for tgt in target_langs:
        try:
            res = await translate_chat_message(
                text=req.text,
                src_lang=req.src_lang,
                tgt_lang=tgt,
                api_key=api_key,
            )
            if res:
                translations.append({"language": tgt, "text": res})
        except Exception as exc:
            logger.warning("translate_chat failed for target %s: %s", tgt, exc)

    return {"translations": translations}
