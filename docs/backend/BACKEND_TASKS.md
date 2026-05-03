# Backend Tasks For Coding Agent

Tài liệu này chia backend work thành task đủ nhỏ để agent code từng task độc lập, không cần hỏi lại design intent.

Quy ước:

- `Depends on`: task phải xong trước
- `Files`: file tạo mới hoặc sửa trong task
- `Input / Output`: interface contract agent phải tạo
- `Acceptance test`: cách verify task hoàn thành

## Foundation

## FND-001 — Platform Dependency And Env Scaffolding

**Goal**

Chuẩn hóa top-level backend files để chạy được Gateway và Interpreter từ cùng codebase.

**Files**

- `BE/requirements.txt` `[MODIFY]`
- `BE/.env.example` `[MODIFY]`
- `BE/.dockerignore` `[MODIFY]`
- `BE/.gitignore` `[MODIFY]`
- `BE/Dockerfile` `[MODIFY]`
- `BE/README.md` `[MODIFY]`

**Input / Output**

Input:

- existing CLI dependency file
- env var list từ `GATEWAY_DESIGN.md` và `LIVEKIT_SETUP.md`

Output:

- `requirements.txt` có đủ deps cho CLI + FastAPI + Redis + LiveKit + JWT
- `.env.example` có đầy đủ biến cho CLI, Gateway, Interpreter
- `Dockerfile` build được image dùng cho cả Gateway và Interpreter

**Depends on**

- none

**Acceptance test**

1. `cd BE && pip install -r requirements.txt` chạy không conflict version
2. `cd BE && python -c "import fastapi, redis, jose, livekit, livekit.api"` không lỗi
3. `cd BE && grep -q LIVEKIT_WS_URL_PUBLIC .env.example`

## FND-002 — Shared Server Package

**Goal**

Tạo shared package cho config, Redis access, event names, và common models.

**Files**

- `BE/server/__init__.py` `[NEW]`
- `BE/server/config.py` `[NEW]`
- `BE/server/events.py` `[NEW]`
- `BE/server/models.py` `[NEW]`
- `BE/server/redis.py` `[NEW]`

**Input / Output**

Input:

- env vars đã khai báo ở FND-001
- state/event shapes từ design docs

Output:

- `Settings` object đọc env vars và expose typed fields
- constants cho Redis channels và key prefixes
- Pydantic models hoặc TypedDict rõ ràng cho:
  - `RoomState`
  - `ParticipantState`
  - `TranscriptEvent`
  - `InterpreterStatusEvent`
  - REST DTOs
- async Redis factory trả `redis.asyncio.Redis`

**Depends on**

- `FND-001`

**Acceptance test**

1. `cd BE && python -c "from server.config import Settings; Settings()"` load được defaults
2. `cd BE && python -c "from server.events import GATEWAY_CONTROL_CHANNEL, INTERPRETER_EVENTS_CHANNEL; print(GATEWAY_CONTROL_CHANNEL, INTERPRETER_EVENTS_CHANNEL)"`
3. `cd BE && pytest -q tests/conftest.py` sau khi `conftest.py` tồn tại không import-error

## FND-003 — Test Bootstrap And Fixtures

**Goal**

Tạo test harness dùng chung cho Gateway và Interpreter.

**Files**

- `BE/tests/conftest.py` `[NEW]`

**Input / Output**

Input:

- shared models/config từ `server/`

Output:

- fixtures cho fake settings
- Redis fake hoặc isolated test Redis fixture
- FastAPI app fixture cho Gateway
- LiveKit stub objects hoặc protocol doubles cho `rtc.Room`, `rtc.AudioStream`, `rtc.AudioSource`
- helper create room JWT

**Depends on**

- `FND-002`

**Acceptance test**

1. `cd BE && pytest -q tests/conftest.py`
2. test import của `server.config`, `server.models`, `server.events` đều pass

## Gateway

## GTW-001 — Room JWT Auth And LiveKit Token Builder

**Goal**

Tạo layer auth cho Gateway WS/leave API và token issuer cho browser LiveKit connect.

**Files**

- `BE/server/service/gateway/__init__.py` `[NEW]`
- `BE/server/service/gateway/auth.py` `[NEW]`
- `BE/server/service/gateway/livekit_tokens.py` `[NEW]`
- `BE/tests/test_gateway_auth.py` `[NEW]`

**Input / Output**

Input:

- `ROOM_JWT_SECRET`, `ROOM_TOKEN_TTL_SECONDS`
- participant join data: `room_id`, `participant_id`, `session_id`, `display_name`, `language`

Output:

- function issue room token
- function verify room token
- function generate browser LiveKit token
- explicit exceptions or error objects:
  - `InvalidTokenError`
  - `ExpiredTokenError`
  - `TokenRoomMismatchError`

**Depends on**

- `FND-002`

**Acceptance test**

1. `cd BE && pytest -q tests/test_gateway_auth.py`
2. test must cover valid token, expired token, wrong signature, wrong room
3. generated LiveKit token must embed correct `identity` and `room`

## GTW-002 — Redis Room Store

**Goal**

Implement Redis persistence layer cho room meta, participant state, transcript history, TTL refresh.

**Files**

- `BE/server/service/gateway/room_store.py` `[NEW]`
- `BE/tests/test_gateway_room_store.py` `[NEW]`

**Input / Output**

Input methods cần có:

- `create_room()`
- `get_room_snapshot(room_id)`
- `add_participant(room_id, participant_state)`
- `update_participant(room_id, participant_id, patch)`
- `mark_participant_left(room_id, participant_id, left_at)`
- `append_transcript(room_id, transcript_event)`
- `mark_room_empty(room_id)`
- `delete_room(room_id)`

Output:

- serialized Redis state đúng key layout
- TTL refreshed on every mutation
- transcript list trimmed về `RECENT_TRANSCRIPT_LIMIT`

**Depends on**

- `FND-002`

**Acceptance test**

1. `cd BE && pytest -q tests/test_gateway_room_store.py`
2. test must verify room lifecycle `created -> active -> empty`
3. test must verify transcript list trim and TTL refresh

## GTW-003 — Room Service Domain Logic

**Goal**

Tách use-case layer khỏi route layer.

**Files**

- `BE/server/service/gateway/room_service.py` `[NEW]`

**Input / Output**

Required methods:

- `create_room() -> CreateRoomResponse`
- `get_room(room_id) -> RoomSnapshotResponse`
- `join_room(room_id, display_name, language, client_meta) -> JoinRoomResponse`
- `leave_room(room_id, participant_ctx) -> None`
- `set_language(room_id, participant_ctx, language) -> ParticipantState`

Required side effects:

- publish Redis control events:
  - `room.created`
  - `participant.joined`
  - `participant.updated`
  - `participant.left`

**Depends on**

- `GTW-001`
- `GTW-002`

**Acceptance test**

1. covered indirectly by API and WS tests
2. service unit tests may be added inline if needed
3. join must reject room full and invalid language deterministically

## GTW-004 — REST Routes

**Goal**

Expose public REST contract exactly như `API_CONTRACT.md`.

**Files**

- `BE/server/service/gateway/api_health.py` `[NEW]`
- `BE/server/service/gateway/api_rooms.py` `[NEW]`
- `BE/server/service/gateway/dependencies.py` `[NEW]`
- `BE/server/service/gateway/main.py` `[NEW]`
- `BE/tests/test_gateway_api.py` `[NEW]`

**Input / Output**

Routes bắt buộc:

- `POST /api/rooms`
- `GET /api/rooms/{room_id}`
- `POST /api/rooms/{room_id}/join`
- `DELETE /api/rooms/{room_id}/leave`
- `GET /api/health`

Output:

- status codes đúng
- error envelope đúng
- `X-Request-ID` header có mặt

**Depends on**

- `GTW-003`

**Acceptance test**

1. `cd BE && pytest -q tests/test_gateway_api.py`
2. test create room -> join -> get room -> leave flow
3. join response must include `websocket.url` và `livekit.token`

## GTW-005 — WebSocket Hub And Endpoint

**Goal**

Implement room-scoped socket registry, auth handshake, heartbeat, and client message handling.

**Files**

- `BE/server/service/gateway/ws_hub.py` `[NEW]`
- `BE/server/service/gateway/ws_endpoint.py` `[NEW]`
- `BE/tests/test_gateway_ws.py` `[NEW]`

**Input / Output**

Input:

- room token từ query string
- client messages `ping`, `set_language`

Output:

- initial `room.snapshot`
- `pong`
- `participant.updated`
- correct close codes on auth failure
- one active socket per participant

**Depends on**

- `GTW-001`
- `GTW-003`
- `GTW-004`

**Acceptance test**

1. `cd BE && pytest -q tests/test_gateway_ws.py`
2. test WS connect with valid token returns `room.snapshot`
3. test second connect same participant replaces first socket
4. test `set_language` broadcasts `participant.updated`

## GTW-006 — Interpreter Event Consumer

**Goal**

Consume Redis pub/sub events từ Interpreter và map thành:

- room store updates
- personalized WS fan-out

**Files**

- `BE/server/service/gateway/app_state.py` `[NEW]`
- `BE/server/service/gateway/event_consumer.py` `[NEW]`

**Input / Output**

Input events:

- `participant.media_connected`
- `participant.media_disconnected`
- `transcript.partial`
- `transcript.final`
- `interpreter.status`
- `interpreter.error`

Output:

- update participant `media_connected`
- persist only `transcript.final`
- fan-out WS events đúng envelope

**Depends on**

- `GTW-002`
- `GTW-005`

**Acceptance test**

1. test suite `tests/test_gateway_ws.py` or integration tests should prove transcript fan-out
2. injecting a `transcript.final` pub/sub message must appear on target socket and in room snapshot persistence

## Interpreter

## INT-001 — LiveKit Room Runtime

**Goal**

Join LiveKit room như interpreter participant, subscribe microphone tracks của human participants.

**Files**

- `BE/server/interpreter/__init__.py` `[NEW]`
- `BE/server/interpreter/livekit_runtime.py` `[NEW]`

**Input / Output**

Input:

- `room_id`
- current room participant map từ Gateway events
- LiveKit internal URL + API credentials

Output:

- connected `rtc.Room`
- callbacks khi human participant mic track publish/unpublish/disconnect
- participant media events published qua `EventSink`

**Depends on**

- `FND-002`

**Acceptance test**

1. use stubs in `tests/conftest.py`
2. runtime must ignore participant identities bắt đầu bằng `interp::`
3. runtime must subscribe only audio microphone tracks

## INT-002 — `LiveKitAudioInput` Adapter

**Goal**

Implement bridge từ `rtc.AudioStream` sang `AudioInput`.

**Files**

- `BE/server/interpreter/audio_adapter.py` `[NEW]`
- `BE/tests/test_interpreter_audio_adapter.py` `[NEW]`

**Input / Output**

Input:

- `rtc.AudioStream` sample rate 16k mono

Output:

- class `LiveKitAudioInput(AudioInput)`
- `metadata.sample_rate == 16000`
- `stream_frames()` yield `640` bytes per 20ms chunk

**Depends on**

- `INT-001`

**Acceptance test**

1. `cd BE && pytest -q tests/test_interpreter_audio_adapter.py`
2. test must cover normal frames, rechunking, stop sentinel, queue overflow behavior

## INT-003 — Realtime Bridge Wrapper

**Goal**

Wrap/subclass `RealtimeClient` để emit callbacks thay vì stdout/speaker.

**Files**

- `BE/server/interpreter/realtime_bridge.py` `[NEW]`
- `BE/tests/test_interpreter_realtime_bridge.py` `[NEW]`

**Input / Output**

Input:

- `LiveKitAudioInput`
- callbacks object
- explicit `src_lang`, `tgt_lang`

Output:

- class `InterpreterRealtimeClient(RealtimeClient)`
- coroutine start method dùng `_run_with_retry()`
- callback emission cho source transcript, translation partial/final, audio delta, errors
- force `enable_speaker=False`

**Depends on**

- `INT-002`

**Acceptance test**

1. `cd BE && pytest -q tests/test_interpreter_realtime_bridge.py`
2. `response.audio.delta` phải route sang callback bytes
3. `response.text.done` phải tạo final translation callback
4. no stdout dependency in assertions

## INT-004 — Output Router

**Goal**

Publish OpenAI audio delta thành LiveKit listener-specific tracks.

**Files**

- `BE/server/interpreter/output_router.py` `[NEW]`
- `BE/tests/test_interpreter_output_router.py` `[NEW]`

**Input / Output**

Input:

- PCM16 24kHz bytes chunks không cố định
- listener set
- room local participant publish handle

Output:

- rechunk thành 20ms `AudioFrame`
- publish track names theo format `interp::{speaker_id}::{listener_id}::{src}::{tgt}`
- `clear_queue()` support
- update subscription permissions sau mỗi publish/unpublish

**Depends on**

- `INT-001`

**Acceptance test**

1. `cd BE && pytest -q tests/test_interpreter_output_router.py`
2. test must verify `960`-byte rechunking
3. test must verify one track per listener
4. test must verify `clear_queue()` is called on cancel

## INT-005 — RealtimeClientPool And InterpretationSession

**Goal**

Manage session create/reuse/teardown theo key `(room_id, speaker_id, src_lang, tgt_lang)`.

**Files**

- `BE/server/interpreter/session.py` `[NEW]`
- `BE/server/interpreter/client_pool.py` `[NEW]`
- `BE/tests/test_interpreter_client_pool.py` `[NEW]`

**Input / Output**

Input:

- speaker id
- source language
- listener ids grouped theo target language
- current speaker remote track

Output:

- `PoolKey`
- `RealtimeClientPool.acquire(...)`
- `release_listener(...)`
- `evict_speaker(...)`
- `evict_room(...)`
- session state transitions `idle/capturing/translating/playing/fallback_text_only`

**Depends on**

- `INT-002`
- `INT-003`
- `INT-004`

**Acceptance test**

1. `cd BE && pytest -q tests/test_interpreter_client_pool.py`
2. same `(room,speaker,src,tgt)` must reuse one entry for multiple listeners
3. different target languages must create different entries
4. speaker leave must evict all speaker sessions

## INT-006 — In-Memory Fallback Translator

**Goal**

Implement Whisper + GPT fallback không ghi file.

**Files**

- `BE/server/interpreter/fallback_translator.py` `[NEW]`
- `BE/tests/test_interpreter_fallback_translator.py` `[NEW]`

**Input / Output**

Input:

- PCM16 mono 16kHz bytes buffer
- `src_lang`
- `tgt_lang`

Output:

- `translate_bytes(...) -> FallbackResult`
- result fields:
  - `source_text`
  - `translated_text`
  - `fallback_used=True`
  - `audio_track_name=None`

**Depends on**

- `FND-002`

**Acceptance test**

1. `cd BE && pytest -q tests/test_interpreter_fallback_translator.py`
2. implementation must use `BytesIO` or equivalent, not filesystem writes
3. test must verify correct prompt build from `src.common.lang.build_instructions`

## INT-007 — Event Sink And Service Orchestrator

**Goal**

Wire Redis control consumer, room runtimes, pool sessions, output router, fallback, and Gateway event publishing.

**Files**

- `BE/server/interpreter/event_sink.py` `[NEW]`
- `BE/server/interpreter/service.py` `[NEW]`
- `BE/server/interpreter/main.py` `[NEW]`

**Input / Output**

Input:

- Redis control events from Gateway

Output:

- service process that:
  - creates `RoomRuntime` on demand
  - updates participant language map
  - registers/unregisters listeners in sessions
  - publishes `transcript.partial`, `transcript.final`, `interpreter.status`, `participant.media_*`

**Depends on**

- `INT-001`
- `INT-005`
- `INT-006`

**Acceptance test**

1. service should start with `python -m server.interpreter.main`
2. injected `participant.joined` event should create room runtime lazily
3. injected `participant.left` should tear down listener mapping

## Integration

## ITG-001 — Gateway/Interpreter Redis Event Flow

**Goal**

Prove pub/sub contract hoạt động end-to-end không cần real browser.

**Files**

- `BE/tests/test_integration_room_lifecycle.py` `[NEW]`

**Input / Output**

Scenario bắt buộc:

1. create room
2. join 2 participants with different languages
3. simulate Interpreter publish `participant.media_connected`
4. simulate `transcript.partial`
5. simulate `transcript.final`
6. leave participant

Output assertions:

- Gateway WS client nhận đúng event order
- `transcript.final` persisted vào room snapshot
- participant leave transitions room to `empty` khi user cuối cùng rời

**Depends on**

- `GTW-006`
- `INT-007`

**Acceptance test**

1. `cd BE && pytest -q tests/test_integration_room_lifecycle.py`

## ITG-002 — Local Compose Smoke Path

**Goal**

Xác nhận commands và ports đúng cho local dev sau khi code xong.

**Files**

- `BE/README.md` `[MODIFY]`

**Input / Output**

Input:

- actual service entrypoints đã implement

Output:

- documented commands cho:
  - `uvicorn server.service.gateway.main:app --host 0.0.0.0 --port 8000`
  - `python -m server.interpreter.main`
- documented expectation về `LIVEKIT_WS_URL_PUBLIC` vs `LIVEKIT_WS_URL_INTERNAL`

**Depends on**

- `FND-001`
- `GTW-004`
- `INT-007`

**Acceptance test**

1. operator có thể follow README để khởi động local stack
2. `GET /api/health` trả `200`

## Recommended Execution Order

```text
Foundation
  FND-001 -> FND-002 -> FND-003

Gateway
  GTW-001 -> GTW-002 -> GTW-003 -> GTW-004 -> GTW-005 -> GTW-006

Interpreter
  INT-001 -> INT-002 -> INT-003 -> INT-004 -> INT-005 -> INT-006 -> INT-007

Integration
  ITG-001 -> ITG-002
```

## Definition Of Done

Backend MVP được coi là done khi toàn bộ điều kiện sau cùng đúng:

1. Tất cả test files trong target tree tồn tại
2. `tests/test_realtime_observability.py` vẫn pass
3. Gateway REST contract khớp `API_CONTRACT.md`
4. Gateway WS contract khớp `API_CONTRACT.md`
5. Interpreter publish được track name đúng format `interp::{speaker}::{listener}::{src}::{tgt}`
6. fallback path không ghi file WAV xuống disk
