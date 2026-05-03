"""
WebSocket endpoint for translation-test sessions.

Connect: ws://host/ws/test/translation/{session_id}

Protocol:
  Client -> Server:
    binary frames  — raw PCM16, 16 kHz, mono, little-endian
    {"type": "ping", ...}          — heartbeat
    {"type": "translation_test.stop"} — graceful stop

  Server -> Client (all JSON):
    translation_test.started   — session confirmed active
    translation_test.partial   — incremental source + translated text while speaking
    translation_test.final     — final source + translated text for the utterance
    translation_test.error     — pipeline error
    pong                       — reply to client ping

Event schema for translation_test.partial and translation_test.final:
  {
    "type": "translation_test.partial" | "translation_test.final",
    "event_id": "evt_...",
    "session_id": "ts_...",
    "sent_at": "...",
    "payload": {
      "session_id": "ts_...",
      "src_lang": "vi",
      "tgt_lang": "ja",
      "source_text": "xin chào...",
      "translated_text": "こんにちは...",
      "is_final": false,
      "timestamp": "..."
    }
  }

Audio output: text-only in this implementation.
Contract leaves room for audio via `audio_track_name` / `audio_url` in a future turn.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.events import EventType, build_test_event
from server.service.gateway.app_state import app_state
from server.brain.realtime.translation_test_client import TranslationTestClient

logger = logging.getLogger(__name__)

router = APIRouter()


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.websocket("/ws/test/translation/{session_id}")
async def ws_translation_test(websocket: WebSocket, session_id: str) -> None:
    store = app_state.test_session_store
    if store is None:
        await websocket.close(code=1011, reason="Test session store unavailable")
        return

    session = await store.get_translation_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="Translation test session not found or expired")
        return

    settings = app_state.settings
    if settings is None:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    await websocket.accept()
    await store.update_translation_session_status(session_id, "listening")

    client = TranslationTestClient(
        api_key=settings.openai_api_key,
        model=settings.openai_realtime_model,
        src_lang=session.src_lang,
        tgt_lang=session.tgt_lang,
    )

    # Shared state for building utterance payloads
    _current_source: list[str] = [""]
    _current_translated: list[str] = [""]

    async def send_json_safe(data: dict) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    # Translate-test callbacks → push events to WS
    def on_source_partial(text: str) -> None:
        _current_source[0] = text
        asyncio.create_task(
            send_json_safe(
                build_test_event(
                    EventType.TRANSLATION_TEST_PARTIAL,
                    session_id,
                    {
                        "session_id": session_id,
                        "src_lang": session.src_lang,
                        "tgt_lang": session.tgt_lang,
                        "source_text": text,
                        "translated_text": _current_translated[0],
                        "is_final": False,
                        "timestamp": _now_str(),
                    },
                )
            )
        )

    def on_source_final(text: str) -> None:
        _current_source[0] = text

    def on_translated_partial(text: str) -> None:
        _current_translated[0] = text
        asyncio.create_task(
            send_json_safe(
                build_test_event(
                    EventType.TRANSLATION_TEST_PARTIAL,
                    session_id,
                    {
                        "session_id": session_id,
                        "src_lang": session.src_lang,
                        "tgt_lang": session.tgt_lang,
                        "source_text": _current_source[0],
                        "translated_text": text,
                        "is_final": False,
                        "timestamp": _now_str(),
                    },
                )
            )
        )

    def on_translated_final(text: str) -> None:
        _current_translated[0] = text
        asyncio.create_task(
            send_json_safe(
                build_test_event(
                    EventType.TRANSLATION_TEST_FINAL,
                    session_id,
                    {
                        "session_id": session_id,
                        "src_lang": session.src_lang,
                        "tgt_lang": session.tgt_lang,
                        "source_text": _current_source[0],
                        "translated_text": text,
                        "is_final": True,
                        "timestamp": _now_str(),
                        # audio output path reserved for future turn:
                        # "audio_track_name": None,
                        # "audio_url": None,
                    },
                )
            )
        )
        _current_source[0] = ""
        _current_translated[0] = ""

    def on_error(code: str, message: str) -> None:
        asyncio.create_task(
            send_json_safe(
                build_test_event(
                    EventType.TRANSLATION_TEST_ERROR,
                    session_id,
                    {
                        "session_id": session_id,
                        "code": code,
                        "message": message,
                        "timestamp": _now_str(),
                    },
                )
            )
        )

    client.on_source_partial = on_source_partial
    client.on_source_final = on_source_final
    client.on_translated_partial = on_translated_partial
    client.on_translated_final = on_translated_final
    client.on_error = on_error

    await client.start()

    # Notify FE that session is live
    await send_json_safe(
        build_test_event(
            "translation_test.started",
            session_id,
            {
                "session_id": session_id,
                "src_lang": session.src_lang,
                "tgt_lang": session.tgt_lang,
                "status": "listening",
                "timestamp": _now_str(),
            },
        )
    )
    await store.update_translation_session_status(session_id, "listening")

    try:
        while True:
            message = await websocket.receive()

            # Binary audio frame → push into pipeline
            if message["type"] == "websocket.receive" and message.get("bytes"):
                pcm_bytes: bytes = message["bytes"]
                client.push_audio(pcm_bytes)
                await store.update_translation_session_status(session_id, "translating")

            # Text JSON control message
            elif message["type"] == "websocket.receive" and message.get("text"):
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "translation_test.stop":
                    await store.update_translation_session_status(session_id, "completed")
                    await send_json_safe(
                        build_test_event(
                            "translation_test.stopped",
                            session_id,
                            {
                                "session_id": session_id,
                                "status": "completed",
                                "timestamp": _now_str(),
                            },
                        )
                    )
                    await websocket.close(code=1000)
                    return

                elif msg_type == "ping":
                    await send_json_safe(
                        {
                            "type": "pong",
                            "event_id": msg.get("event_id"),
                            "session_id": session_id,
                            "sent_at": _now_str(),
                            "payload": {
                                "client_time": msg.get("sent_at"),
                                "server_time": _now_str(),
                            },
                        }
                    )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("Translation test WS error for session %s", session_id)
        await send_json_safe(
            build_test_event(
                EventType.TRANSLATION_TEST_ERROR,
                session_id,
                {
                    "session_id": session_id,
                    "code": "internal_error",
                    "message": str(exc),
                    "timestamp": _now_str(),
                },
            )
        )
    finally:
        await client.stop()
        await store.update_translation_session_status(session_id, "completed")
