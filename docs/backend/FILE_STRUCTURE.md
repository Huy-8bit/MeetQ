# BE File Structure

Phạm vi của tài liệu này là **toàn bộ source-controlled file** cần tồn tại trong `BE/` sau khi backend meeting platform hoàn tất.

Quy ước trạng thái:

- `[KEEP]` giữ nguyên file hiện có, không sửa nội dung.
- `[MODIFY]` giữ file hiện có nhưng cập nhật nội dung.
- `[NEW]` file mới cần tạo.
- `[REMOVE]` file/local artifact không được tồn tại trong target tree.

Ngoài scope của cây bên dưới:

- Runtime-local: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `logs/*.log`, `recordings/*.wav`
- Root-level infra ngoài `BE/`: `docker-compose.yml`, `livekit.yaml`, nginx config

## Target Tree

```text
BE/
├── .dockerignore                                   [MODIFY]
├── .env.example                                    [MODIFY]
├── .gitignore                                      [MODIFY]
├── Dockerfile                                      [MODIFY]
├── README.md                                       [MODIFY]
├── main.py                                         [KEEP]
├── requirements.txt                                [MODIFY]
├── logs/
│   └── .gitkeep                                    [KEEP]
├── recordings/
│   └── .gitkeep                                    [KEEP]
├── src/
│   ├── __init__.py                                 [KEEP]
│   ├── common/
│   │   ├── .gitkeep                                [KEEP]
│   │   ├── __init__.py                             [KEEP]
│   │   ├── audio.py                                [KEEP]
│   │   ├── lang.py                                 [KEEP]
│   │   └── logging_utils.py                        [KEEP]
│   ├── fallback/
│   │   ├── .gitkeep                                [KEEP]
│   │   ├── __init__.py                             [KEEP]
│   │   ├── main.py                                 [KEEP]
│   │   └── pipeline.py                             [KEEP]
│   └── realtime/
│       ├── .gitkeep                                [KEEP]
│       ├── __init__.py                             [KEEP]
│       ├── client.py                               [KEEP]
│       └── main.py                                 [KEEP]
├── server/
│   ├── __init__.py                                 [NEW]
│   ├── config.py                                   [NEW]
│   ├── events.py                                   [NEW]
│   ├── models.py                                   [NEW]
│   ├── redis.py                                    [NEW]
│   ├── gateway/
│   │   ├── __init__.py                             [NEW]
│   │   ├── api_health.py                           [NEW]
│   │   ├── api_rooms.py                            [NEW]
│   │   ├── app_state.py                            [NEW]
│   │   ├── auth.py                                 [NEW]
│   │   ├── dependencies.py                         [NEW]
│   │   ├── event_consumer.py                       [NEW]
│   │   ├── livekit_tokens.py                       [NEW]
│   │   ├── main.py                                 [NEW]
│   │   ├── room_service.py                         [NEW]
│   │   ├── room_store.py                           [NEW]
│   │   ├── ws_endpoint.py                          [NEW]
│   │   └── ws_hub.py                               [NEW]
│   └── interpreter/
│       ├── __init__.py                             [NEW]
│       ├── audio_adapter.py                        [NEW]
│       ├── client_pool.py                          [NEW]
│       ├── event_sink.py                           [NEW]
│       ├── fallback_translator.py                  [NEW]
│       ├── livekit_runtime.py                      [NEW]
│       ├── main.py                                 [NEW]
│       ├── output_router.py                        [NEW]
│       ├── realtime_bridge.py                      [NEW]
│       ├── service.py                              [NEW]
│       └── session.py                              [NEW]
└── tests/
    ├── conftest.py                                 [NEW]
    ├── test_gateway_api.py                         [NEW]
    ├── test_gateway_auth.py                        [NEW]
    ├── test_gateway_room_store.py                  [NEW]
    ├── test_gateway_ws.py                          [NEW]
    ├── test_integration_room_lifecycle.py          [NEW]
    ├── test_interpreter_audio_adapter.py           [NEW]
    ├── test_interpreter_client_pool.py             [NEW]
    ├── test_interpreter_fallback_translator.py     [NEW]
    ├── test_interpreter_output_router.py           [NEW]
    ├── test_interpreter_realtime_bridge.py         [NEW]
    └── test_realtime_observability.py              [KEEP]
```

## File Responsibilities

### Top-level files

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/.dockerignore` | `[MODIFY]` | Loại runtime-local files khỏi Docker build context, đặc biệt `.env`, `.venv`, `recordings/*.wav`, `logs/*`, cache directories. |
| `BE/.env.example` | `[MODIFY]` | Template đầy đủ cho CLI và platform: OpenAI, Redis, JWT, LiveKit public/internal URLs, API secrets. |
| `BE/.gitignore` | `[MODIFY]` | Ignore `.env`, recordings generated at runtime, logs, caches, and local editor artifacts. |
| `BE/Dockerfile` | `[MODIFY]` | Base image chung cho CLI, Gateway, và Interpreter; cài deps web/redis/livekit ngoài deps CLI hiện có. |
| `BE/README.md` | `[MODIFY]` | Mô tả cách chạy CLI cũ và các process mới: Gateway, Interpreter, test, Docker usage. |
| `BE/main.py` | `[KEEP]` | Entry point CLI hiện có; không tham gia luồng meeting platform. |
| `BE/requirements.txt` | `[MODIFY]` | Bổ sung FastAPI, Uvicorn, Redis client, JWT libs, LiveKit Python SDK hiện hành, test deps còn thiếu nếu project pin trong một file. |

### Runtime placeholder directories

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/logs/.gitkeep` | `[KEEP]` | Giữ thư mục log tồn tại; production không commit file log thực tế. |
| `BE/recordings/.gitkeep` | `[KEEP]` | Giữ thư mục recordings cho CLI fallback; platform path không được persist audio vào đây. |

### Existing reusable engine in `src/`

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/src/__init__.py` | `[KEEP]` | Marker package cho source tree hiện hữu. |
| `BE/src/common/.gitkeep` | `[KEEP]` | Placeholder thư mục. |
| `BE/src/common/__init__.py` | `[KEEP]` | Marker package cho common module. |
| `BE/src/common/audio.py` | `[KEEP]` | Contract `AudioInput`, `SpeakerPlayer`, mic/loopback capture; interpreter chỉ implement adapter mới ở `server/`. |
| `BE/src/common/lang.py` | `[KEEP]` | Instruction builder và routing helper được tái sử dụng bởi interpreter và fallback translator. |
| `BE/src/common/logging_utils.py` | `[KEEP]` | Logger utility hiện có. |
| `BE/src/fallback/.gitkeep` | `[KEEP]` | Placeholder thư mục. |
| `BE/src/fallback/__init__.py` | `[KEEP]` | Marker package cho fallback module. |
| `BE/src/fallback/main.py` | `[KEEP]` | CLI fallback runner hiện có. |
| `BE/src/fallback/pipeline.py` | `[KEEP]` | CLI-oriented fallback pipeline; platform không sửa file này, chỉ tái sử dụng ý tưởng/model choice. |
| `BE/src/realtime/.gitkeep` | `[KEEP]` | Placeholder thư mục. |
| `BE/src/realtime/__init__.py` | `[KEEP]` | Marker package cho realtime module. |
| `BE/src/realtime/client.py` | `[KEEP]` | `RealtimeClient` lõi; interpreter dùng subclass/wrapper ở `server/interpreter/realtime_bridge.py` thay vì sửa trực tiếp. |
| `BE/src/realtime/main.py` | `[KEEP]` | CLI realtime runner hiện có. |

### Shared server package

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/server/__init__.py` | `[NEW]` | Marker package cho toàn bộ backend meeting-platform code. |
| `BE/server/config.py` | `[NEW]` | `BaseSettings` cho Gateway và Interpreter: Redis URL, JWT secret, LiveKit public/internal URL, OpenAI key, TTLs, limits. |
| `BE/server/events.py` | `[NEW]` | Khai báo channel names Redis pub/sub, event type constants, helper build/parse envelope. |
| `BE/server/models.py` | `[NEW]` | Shared Pydantic models / TypedDicts cho room state, participant state, transcript event, interpreter status, API DTOs. |
| `BE/server/redis.py` | `[NEW]` | Factory tạo `redis.asyncio.Redis`, helper ping/close, TTL refresh helpers. |

### Gateway package

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/server/gateway/__init__.py` | `[NEW]` | Marker package cho Gateway service. |
| `BE/server/gateway/api_health.py` | `[NEW]` | `GET /api/health` route và response mapping. |
| `BE/server/gateway/api_rooms.py` | `[NEW]` | `POST /api/rooms`, `GET /api/rooms/{id}`, `POST /join`, `DELETE /leave` routes. |
| `BE/server/gateway/app_state.py` | `[NEW]` | Runtime singletons: settings, Redis clients, room store, ws hub, background tasks. |
| `BE/server/gateway/auth.py` | `[NEW]` | Sinh/verify room JWT bằng `python-jose`, token claims, close-code mapping cho WS auth failures. |
| `BE/server/gateway/dependencies.py` | `[NEW]` | FastAPI dependency providers cho settings, store, room service, authenticated participant context. |
| `BE/server/gateway/event_consumer.py` | `[NEW]` | Background subscriber nhận events từ Interpreter qua Redis và fan-out vào room store + ws hub. |
| `BE/server/gateway/livekit_tokens.py` | `[NEW]` | Sinh LiveKit access token cho browser participants bằng `livekit-api`; gắn metadata chuẩn. |
| `BE/server/gateway/main.py` | `[NEW]` | FastAPI app factory, lifespan startup/shutdown, route registration, middleware. |
| `BE/server/gateway/room_service.py` | `[NEW]` | Use-case layer cho create/join/leave/update-language; publish control events sang Interpreter. |
| `BE/server/gateway/room_store.py` | `[NEW]` | Redis persistence cho room meta, participants, transcripts, TTL refresh, snapshot retrieval. |
| `BE/server/gateway/ws_endpoint.py` | `[NEW]` | WebSocket `/ws/rooms/{room_id}` endpoint, heartbeat, auth, message parsing, disconnect cleanup. |
| `BE/server/gateway/ws_hub.py` | `[NEW]` | In-memory connection registry theo `room_id` và `participant_id`; send snapshot/broadcast per-room/per-participant. |

### Interpreter package

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/server/interpreter/__init__.py` | `[NEW]` | Marker package cho Interpreter service. |
| `BE/server/interpreter/audio_adapter.py` | `[NEW]` | `LiveKitAudioInput` implements `AudioInput` bằng cách bridge `rtc.AudioStream` sang PCM16 16kHz chunk iterator. |
| `BE/server/interpreter/client_pool.py` | `[NEW]` | `RealtimeClientPool` quản lý create/reuse/evict sessions theo `(room_id, speaker_id, src_lang, tgt_lang)`. |
| `BE/server/interpreter/event_sink.py` | `[NEW]` | Publish transcript/status/media events từ Interpreter sang Redis channel của Gateway. |
| `BE/server/interpreter/fallback_translator.py` | `[NEW]` | In-memory Whisper + GPT fallback cho utterance buffer, không ghi WAV ra disk. |
| `BE/server/interpreter/livekit_runtime.py` | `[NEW]` | Kết nối programmatic participant tới LiveKit room, subscribe remote mic tracks, publish translated output tracks. |
| `BE/server/interpreter/main.py` | `[NEW]` | Process entrypoint cho Interpreter service. |
| `BE/server/interpreter/output_router.py` | `[NEW]` | Convert PCM16 24kHz deltas thành `rtc.AudioFrame`, publish/fan-out tới track riêng cho từng listener, clear queues khi barge-in. |
| `BE/server/interpreter/realtime_bridge.py` | `[NEW]` | Subclass/wrapper của `RealtimeClient` để chuyển OpenAI events thành callbacks thay vì stdout/speaker playback. |
| `BE/server/interpreter/service.py` | `[NEW]` | Orchestrator chính: consume Redis control events, manage room runtimes, trigger pool/session lifecycle. |
| `BE/server/interpreter/session.py` | `[NEW]` | State machine và runtime object cho một interpretation session per `(room, speaker, src, tgt)`. |

### Test suite

| File | Status | Responsibility |
| --- | --- | --- |
| `BE/tests/conftest.py` | `[NEW]` | Shared fixtures cho Redis fake, LiveKit stubs, JWT helpers, FastAPI app factory. |
| `BE/tests/test_gateway_api.py` | `[NEW]` | REST contract tests cho create/get/join/leave. |
| `BE/tests/test_gateway_auth.py` | `[NEW]` | JWT issue/verify tests, room mismatch, expiry, invalid signature. |
| `BE/tests/test_gateway_room_store.py` | `[NEW]` | Redis state persistence tests, transcript trimming, TTL refresh, room lifecycle transitions. |
| `BE/tests/test_gateway_ws.py` | `[NEW]` | WebSocket handshake, `room.snapshot`, `set_language`, heartbeat, reconnect replacement. |
| `BE/tests/test_integration_room_lifecycle.py` | `[NEW]` | Gateway + Interpreter + Redis fake integration around join/speak/leave event flow. |
| `BE/tests/test_interpreter_audio_adapter.py` | `[NEW]` | `LiveKitAudioInput` frame conversion, chunk sizing, stop semantics. |
| `BE/tests/test_interpreter_client_pool.py` | `[NEW]` | Pool key reuse, reference counting, teardown on language change/participant leave. |
| `BE/tests/test_interpreter_fallback_translator.py` | `[NEW]` | Fallback trigger behavior, in-memory WAV conversion, text-only degraded output contract. |
| `BE/tests/test_interpreter_output_router.py` | `[NEW]` | Audio rechunking 24kHz, per-listener track publish, `clear_queue()` on cancel. |
| `BE/tests/test_interpreter_realtime_bridge.py` | `[NEW]` | Mapping OpenAI events thành transcript/audio callbacks và session state transitions. |
| `BE/tests/test_realtime_observability.py` | `[KEEP]` | Existing regression tests cho `src/realtime/client.py`; vẫn phải pass sau khi thêm platform code. |

## Local Artifacts To Remove

| Path | Status | Reason |
| --- | --- | --- |
| `BE/recordings/.DS_Store` | `[REMOVE]` | macOS artifact, không thuộc target tree. |
| `BE/tasks/` | `[REMOVE]` | Empty scratch directory hiện tại, không có vai trò trong target backend. |

## Design Notes

1. `BE/src/` là frozen engine layer. Mọi integration code mới phải đi vào `BE/server/`.
2. Gateway và Interpreter cùng dùng chung `server/config.py`, `server/events.py`, `server/models.py`, `server/redis.py` để không duplicate contract.
3. `server/interpreter/realtime_bridge.py` là điểm then chốt để tái sử dụng `RealtimeClient` mà không sửa file gốc.
4. Không thêm database migration, ORM, SQL model, hay Alembic vì MVP chỉ dùng Redis TTL 24h.
