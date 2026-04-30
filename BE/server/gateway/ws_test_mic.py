"""
WebSocket endpoint for mic-test sessions.

Connect: ws://host/ws/test/mic/{session_id}

Protocol:
  Client -> Server: binary frames (raw PCM16, 16 kHz, mono, little-endian)
                    OR text JSON ping: {"type": "ping", "event_id": "...", "sent_at": "..."}
                    OR text JSON stop: {"type": "mic_test.stop"}

  Server -> Client (all JSON):
    mic_test.started  — emitted once after accept, confirms session is active
    mic_test.level    — emitted per audio chunk with RMS + peak, server confirms audio ingress
    mic_test.silence  — emitted when RMS drops below threshold for >500 ms
    mic_test.stopped  — emitted when client sends stop or disconnects cleanly
    mic_test.error    — emitted on fatal error before close

Event schema (server -> client):
  {
    "type": "mic_test.level",
    "event_id": "evt_...",
    "session_id": "ts_...",
    "sent_at": "...",
    "payload": {
      "session_id": "ts_...",
      "status": "active",
      "rms": 0.032,          // 0.0 – 1.0 normalized from int16 range
      "peak": 0.045,         // 0.0 – 1.0
      "db": -29.8,           // dBFS, -inf to 0.0
      "chunk_ms": 20,
      "timestamp": "..."
    }
  }
"""
from __future__ import annotations

import json
import math
import struct
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.events import EventType, build_test_event
from server.gateway.app_state import app_state

router = APIRouter()

_SILENCE_THRESHOLD_RMS = 0.004   # ~-48 dBFS — below this counts as silence
_SILENCE_WINDOW_MS = 500          # emit silence event after this many ms of quiet
_INT16_MAX = 32768.0
_BYTES_PER_SAMPLE = 2


def _compute_rms_peak(pcm16_bytes: bytes) -> tuple[float, float]:
    """Return (rms, peak) normalized to [0.0, 1.0] from raw PCM16 LE bytes."""
    if len(pcm16_bytes) < _BYTES_PER_SAMPLE:
        return 0.0, 0.0
    n = len(pcm16_bytes) // _BYTES_PER_SAMPLE
    samples = struct.unpack_from(f"<{n}h", pcm16_bytes[:n * _BYTES_PER_SAMPLE])
    sq_sum = sum(s * s for s in samples)
    rms = math.sqrt(sq_sum / n) / _INT16_MAX
    peak = max(abs(s) for s in samples) / _INT16_MAX
    return rms, peak


def _rms_to_db(rms: float) -> float:
    if rms <= 0.0:
        return -96.0
    return max(-96.0, 20.0 * math.log10(rms))


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.websocket("/ws/test/mic/{session_id}")
async def ws_mic_test(websocket: WebSocket, session_id: str) -> None:
    store = app_state.test_session_store
    if store is None:
        await websocket.close(code=1011, reason="Test session store unavailable")
        return

    session = await store.get_mic_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="Mic test session not found or expired")
        return

    await websocket.accept()
    await store.update_mic_session_status(session_id, "active")

    # Emit started
    await websocket.send_json(
        build_test_event(
            EventType.MIC_TEST_STARTED,
            session_id,
            {
                "session_id": session_id,
                "status": "active",
                "timestamp": _now_str(),
            },
        )
    )

    silence_ms_accumulated: float = 0.0
    silence_event_sent: bool = False

    try:
        while True:
            message = await websocket.receive()

            # Binary audio frame
            if message["type"] == "websocket.receive" and message.get("bytes"):
                pcm_bytes: bytes = message["bytes"]
                rms, peak = _compute_rms_peak(pcm_bytes)
                db = _rms_to_db(rms)

                # Approximate chunk duration from byte length (16 kHz, mono, 16-bit)
                chunk_ms = len(pcm_bytes) / (_INT16_MAX * 2 * _BYTES_PER_SAMPLE) * 1000
                chunk_ms = (len(pcm_bytes) / _BYTES_PER_SAMPLE) / 16000 * 1000

                if rms < _SILENCE_THRESHOLD_RMS:
                    silence_ms_accumulated += chunk_ms
                    if silence_ms_accumulated >= _SILENCE_WINDOW_MS and not silence_event_sent:
                        silence_event_sent = True
                        await websocket.send_json(
                            build_test_event(
                                EventType.MIC_TEST_SILENCE,
                                session_id,
                                {
                                    "session_id": session_id,
                                    "status": "active",
                                    "silence_ms": round(silence_ms_accumulated),
                                    "timestamp": _now_str(),
                                },
                            )
                        )
                else:
                    silence_ms_accumulated = 0.0
                    silence_event_sent = False

                await websocket.send_json(
                    build_test_event(
                        EventType.MIC_TEST_LEVEL,
                        session_id,
                        {
                            "session_id": session_id,
                            "status": "active",
                            "rms": round(rms, 5),
                            "peak": round(peak, 5),
                            "db": round(db, 2),
                            "chunk_ms": round(chunk_ms, 1),
                            "timestamp": _now_str(),
                        },
                    )
                )

            # Text JSON control message
            elif message["type"] == "websocket.receive" and message.get("text"):
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = message_type = msg.get("type")

                if msg_type == "mic_test.stop":
                    await _send_stopped(websocket, session_id)
                    await store.update_mic_session_status(session_id, "stopped")
                    await websocket.close(code=1000)
                    return

                elif msg_type == "ping":
                    await websocket.send_json(
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
        try:
            await websocket.send_json(
                build_test_event(
                    EventType.MIC_TEST_ERROR,
                    session_id,
                    {
                        "session_id": session_id,
                        "code": "internal_error",
                        "message": str(exc),
                        "timestamp": _now_str(),
                    },
                )
            )
        except Exception:
            pass
    finally:
        await store.update_mic_session_status(session_id, "stopped")


async def _send_stopped(websocket: WebSocket, session_id: str) -> None:
    try:
        await websocket.send_json(
            build_test_event(
                EventType.MIC_TEST_STOPPED,
                session_id,
                {
                    "session_id": session_id,
                    "status": "stopped",
                    "timestamp": _now_str(),
                },
            )
        )
    except Exception:
        pass
