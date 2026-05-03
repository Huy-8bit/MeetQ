# BE File Structure

Phạm vi tài liệu này là cấu trúc backend hiện tại sau refactor boundary `brain` vs `service`.

Refactor này là **behavior-preserving**:

- Không đổi REST API routes, WebSocket event names, room snapshot shape, BRSE toggle semantics, LiveKit connect flow, Redis channel contract, hay Telegram notification flow.
- `brain` chỉ chứa code AI/model-facing.
- `service` chứa backend orchestration/application logic điều phối room, LiveKit media, Redis control, và brain clients.

## Boundary Rule

- `brain`: module trực tiếp build prompt, cấu hình model session, gọi OpenAI/realtime model, xử lý model events, hoặc áp chính sách chống hallucination trong model-response path.
- `service`: module điều phối backend application/runtime lifecycle, bao gồm Gateway HTTP/WS transport, room-level coordination, participant/session flow, Redis event IO, LiveKit media bridge, và integration giữa Gateway state với Brain.
- `shared`: helper generic không thuộc AI domain.

## Target Tree

```text
BE/
├── Dockerfile
├── README.md
├── main.py
├── requirements.txt
├── logs/
│   └── .gitkeep
├── recordings/
│   └── .gitkeep
├── server/
│   ├── __init__.py
│   ├── config.py
│   ├── events.py
│   ├── meeting_modes.py
│   ├── models.py
│   ├── redis.py
│   ├── brain/
│   │   ├── __init__.py
│   │   ├── realtime/
│   │   │   ├── __init__.py
│   │   │   ├── client.py                   # reusable OpenAI Realtime client
│   │   │   ├── interpreter_client.py       # meeting realtime model wrapper/callback bridge
│   │   │   ├── main.py                     # local realtime CLI entrypoint
│   │   │   ├── session_config.py           # model session/VAD/instruction config
│   │   │   ├── source_policy.py            # source transcript validation/anti-hallucination policy
│   │   │   └── translation_test_client.py  # gateway translation-test model client
│   │   ├── prompts/
│   │   │   ├── __init__.py
│   │   │   └── language.py                 # language routing, detection, instruction builders
│   │   └── fallback/
│   │       ├── __init__.py
│   │       ├── main.py                     # local fallback CLI entrypoint
│   │       └── pipeline.py                 # fallback STT + chat model pipeline
│   ├── service/
│   │   ├── __init__.py
│   │   ├── brain_runtime/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                     # brain runtime service process entrypoint
│   │   │   ├── daemon.py                   # Redis control consumer, room manager lifecycle
│   │   │   ├── events.py                   # Redis event publisher/envelope adapter
│   │   │   └── room_manager.py             # room-level orchestration around brain clients
│   │   ├── media/
│   │   │   ├── __init__.py
│   │   │   ├── audio_input.py              # LiveKit AudioStream -> generic AudioInput adapter
│   │   │   ├── livekit_runtime.py          # LiveKit programmatic participant runtime
│   │   │   └── output_router.py            # brain audio output -> LiveKit relay track
│   │   └── gateway/
│   │       ├── __init__.py
│   │       ├── api_health.py
│   │       ├── api_rooms.py
│   │       ├── api_test_sessions.py
│   │       ├── app_state.py
│   │       ├── auth.py
│   │       ├── dependencies.py
│   │       ├── event_consumer.py
│   │       ├── livekit_tokens.py
│   │       ├── main.py
│   │       ├── room_service.py
│   │       ├── room_store.py
│   │       ├── test_session_store.py
│   │       ├── ws_endpoint.py
│   │       ├── ws_hub.py
│   │       ├── ws_test_mic.py
│   │       └── ws_test_translation.py
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── telegram.py
│   └── shared/
│       ├── __init__.py
│       ├── audio.py
│       └── logging_utils.py
└── tests/
    ├── conftest.py
    ├── test_gateway_api.py
    ├── test_gateway_auth.py
    ├── test_gateway_room_store.py
    ├── test_gateway_ws.py
    ├── test_interpreter_audio_adapter.py
    ├── test_realtime_observability.py
    └── test_telegram_notifier.py
```

## Module Boundaries

### `server.brain`

Brain owns AI/model-facing code:

- OpenAI Realtime websocket client and meeting-specific realtime wrapper.
- Model session payload config, VAD config, and realtime model instructions.
- Prompt/instruction builders and language routing helpers used by model prompts.
- Source transcript validation and anti-hallucination policy used before model relay output can publish.
- Translation-test model client.
- Fallback STT + chat model pipeline.

Brain does **not** own room lifecycle, Redis control consumption, LiveKit room connection lifecycle, or Gateway fan-out.

### `server.service`

Service owns backend orchestration:

- `service.gateway`: FastAPI REST routes, WebSocket room transport, auth, room store/service, browser LiveKit token issuance, Gateway app state, and event fan-out.
- `service.brain_runtime.main`: process entrypoint for the runtime that listens to Gateway control events and manages BRSE room runtimes.
- `service.brain_runtime.daemon`: Redis control channel consumer, room snapshot lookup, BRSE enabled/expired gates, manager spawn/stop lifecycle.
- `service.brain_runtime.room_manager`: room-level participant/media coordination, routing between room state and brain clients, speaker lifecycle/focus arbitration, transcript publish orchestration.
- `service.brain_runtime.events`: Redis event publisher/envelope adapter for service-to-gateway events.
- `service.media`: LiveKit media adapters used by the service runtime.

The production Gateway service starts with:

```bash
uvicorn server.service.gateway.main:app --host 0.0.0.0 --port 8000
```

The production brain runtime service starts with:

```bash
python -m server.service.brain_runtime.main
```

`docker-compose.yml` and `docker-compose.prod.yml` use this entrypoint for the interpreter/brain runtime container.

### `server.service.gateway`

Gateway owns transport and room ingress/egress:

- FastAPI REST routes and WebSocket room transport.
- JWT and LiveKit browser token issuance.
- Redis-backed room store/service.
- Fan-out of backend events into room snapshots and WebSocket messages.
- Test-only mic/translation WebSocket endpoints.

Gateway may call `server.brain.realtime.translation_test_client` for the translation-test tool because that code directly controls a realtime model session.

### `server.shared`

Shared contains generic backend helpers that are not AI-specific:

- `audio.py`: generic audio abstractions, mic/device capture, speaker playback helpers.
- `logging_utils.py`: generic logger and output helpers.

### `server.integrations`

Integrations contains external non-AI service adapters:

- `telegram.py`: Telegram notification integration used by Gateway room service.

## Notable Moves

| Old path | New path | Why |
| --- | --- | --- |
| `BE/server/brain/main.py` | `BE/server/service/brain_runtime/main.py` | Process startup is service orchestration. |
| `BE/server/brain/relay/daemon.py` | `BE/server/service/brain_runtime/daemon.py` | Redis control and manager lifecycle are service orchestration. |
| `BE/server/brain/relay/events.py` | `BE/server/service/brain_runtime/events.py` | Redis event publication is service IO, not model logic. |
| `BE/server/brain/relay/room_manager.py` | `BE/server/service/brain_runtime/room_manager.py` | Room coordination and lifecycle are service logic. |
| `BE/server/brain/livekit/audio_input.py` | `BE/server/service/media/audio_input.py` | LiveKit media adapter, not model logic. |
| `BE/server/brain/livekit/runtime.py` | `BE/server/service/media/livekit_runtime.py` | LiveKit participant runtime, not model logic. |
| `BE/server/brain/livekit/output_router.py` | `BE/server/service/media/output_router.py` | LiveKit output routing, not model logic. |
| `BE/server/gateway/*` | `BE/server/service/gateway/*` | Gateway is backend application/transport logic, so it belongs under `service`. |
| source transcript filter inside room manager | `BE/server/brain/realtime/source_policy.py` | AI response anti-hallucination/source policy belongs to model-response path. |

## Intentionally Kept

- `server.models`, `server.events`, `server.redis`, and `server.config` remain shared server-level contracts/config.
- `server.meeting_modes` remains server-level because Gateway and service both use the meeting/BRSE constants.
- `server.shared.audio` remains shared because it is generic audio abstraction, not AI-specific.
- No top-level `server.gateway` compatibility shim is kept; canonical Gateway imports are `server.service.gateway.*`.

## Behavior Preservation Strategy

1. Move modules mechanically and update imports.
2. Keep public API/WS contracts unchanged.
3. Keep Redis channel names, event types, room store semantics, and room lifecycle decisions unchanged.
4. Keep realtime model client behavior, VAD config, prompt text, source transcript policy, and relay gating semantics unchanged.
5. Keep LiveKit identity/token/track naming behavior unchanged.
6. Update Docker/compose/README entrypoint paths to the new `service.gateway` and `service.brain_runtime` modules.
7. Defer full test suite per CODE-ONLY instruction; use only lightweight compile/import checks for moved modules.
