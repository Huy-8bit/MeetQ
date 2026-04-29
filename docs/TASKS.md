# TASKS — brseAI Meeting Platform

Tracking toàn bộ công việc từ CLI engine → full meeting platform.

---

## DONE — CLI Engine

### TASK-01: Realtime interpreter core

**Status:** DONE

- [x] WebSocket session với OpenAI Realtime API
- [x] Stream audio PCM16 qua `input_audio_buffer.append`
- [x] Nhận và print translation text realtime
- [x] Ctrl+C shutdown

### TASK-02: Voice output + barge-in

**Status:** DONE

- [x] Decode `response.audio.delta` → play qua loa
- [x] `response.audio.done` flush player (50ms silence pad)
- [x] Barge-in: `speech_started` khi AI đang nói → `response.cancel` + restart player

### TASK-03: AudioInput abstraction + device loopback

**Status:** DONE

- [x] `AudioInput` abstract class
- [x] `MicInput` và `DeviceLoopbackInput`
- [x] `RealtimeClient` nhận injected `AudioInput`

### TASK-04: Language routing

**Status:** DONE

- [x] Heuristic detect vi / en / ja
- [x] `--src`, `--tgt`, `--meeting-mode` (locked / auto)
- [x] Dynamic `session.update` khi routing thay đổi
- [x] Pair filtering

### TASK-05: Fallback pipeline

**Status:** DONE

- [x] Record clip → WAV → Whisper transcribe → GPT translate
- [x] Loop liên tục trong fallback mode

### TASK-06: Cleanup — xóa Discord, đơn giản hóa entry point

**Status:** DONE

- [x] Xóa `src/discord/`
- [x] Viết lại `main.py` đơn giản
- [x] Dọn `requirements.txt`

---

## TODO — Meeting Platform

### TASK-07: Project scaffold

**Status:** TODO — Priority: P0

- [ ] Khởi tạo `web/client/` (React + TypeScript + Vite)
- [ ] Khởi tạo `server/gateway/` (FastAPI)
- [ ] Khởi tạo `server/interpreter/` (Python asyncio service)
- [ ] `docker-compose.yml`: web + gateway + interpreter + livekit + redis
- [ ] `.env.example` đầy đủ cho platform (`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, v.v.)
- [ ] Makefile: `make dev`, `make build`, `make test`

### TASK-08: SFU setup — LiveKit

**Status:** TODO — Priority: P0

- [ ] Chạy LiveKit server local qua Docker
- [ ] Config TURN/STUN
- [ ] Test publish/subscribe audio track cơ bản qua LiveKit Python SDK
- [ ] Verify PCM16 frames nhận được từ subscribed track

### TASK-09: Gateway server — FastAPI

**Status:** TODO — Priority: P0

- [ ] `POST /api/rooms` — tạo phòng, sinh room_id
- [ ] `POST /api/rooms/:id/join` — validate, sinh LiveKit token, trả config
- [ ] `GET /api/rooms/:id` — trạng thái phòng
- [ ] `DELETE /api/rooms/:id/leave`
- [ ] WebSocket `/ws/rooms/:id` — broadcast transcript và participant events
- [ ] Room state in-memory (dict)
- [ ] Event handling: participant join/leave, set language, transcript broadcast

### TASK-10: Interpreter Service — tích hợp brseAI engine

**Status:** TODO — Priority: P0

- [ ] `LiveKitAudioInput` adapter: LiveKit track frames → implements `AudioInput`
- [ ] Subscribe audio track của speaker từ LiveKit Python SDK
- [ ] Khởi tạo `RealtimeClient` per (speaker, language_pair)
- [ ] Publish audio output (dịch) → LiveKit track riêng cho người nghe
- [ ] Gửi transcript text → Gateway để broadcast
- [ ] Lifecycle management: tạo/hủy client khi participant join/leave/đổi ngôn ngữ

### TASK-11: Frontend — Room UI cơ bản

**Status:** TODO — Priority: P0

- [ ] Trang Home: tạo phòng mới / nhập room ID
- [ ] Trang Room: grid video, controls (mute, cam off)
- [ ] Modal chọn ngôn ngữ khi vào phòng (vi / en / ja)
- [ ] LiveKit JS SDK: publish mic + camera, subscribe tracks
- [ ] WebSocket đến Gateway: nhận transcript events
- [ ] Transcript panel: hiển thị bản dịch realtime, cuộn auto

### TASK-12: Frontend — UI/UX hoàn chỉnh

**Status:** TODO — Priority: P1

- [ ] Responsive desktop layout
- [ ] Indicator "AI đang dịch..." per speaker
- [ ] Participant list với badge ngôn ngữ
- [ ] Copy link mời phòng
- [ ] Thông báo join/leave
- [ ] Trạng thái kết nối (connected / reconnecting)
- [ ] Dark mode

### TASK-13: Interpreter Service — reliability

**Status:** TODO — Priority: P1

- [ ] Fallback tự động: Realtime API lỗi → Whisper + GPT
- [ ] Reconnect OpenAI WebSocket với exponential back-off
- [ ] Rate limit handling và queue
- [ ] Log latency: `speech_end → first_audio_delta`
- [ ] Giới hạn max concurrent `RealtimeClient` per room

### TASK-14: Testing

**Status:** TODO — Priority: P1

- [ ] Unit: language routing, instruction builder, room state
- [ ] Integration: Gateway API (create/join/leave)
- [ ] Integration: Interpreter Service với LiveKit mock
- [ ] E2E: 2 browser + 2 ngôn ngữ → transcript đúng ngôn ngữ đích

### TASK-15: Deployment

**Status:** TODO — Priority: P2

- [ ] Docker Compose production config
- [ ] Nginx reverse proxy + TLS (Let's Encrypt)
- [ ] LiveKit Cloud thay self-hosted
- [ ] Health check endpoints cho tất cả services
- [ ] Runbook: start, stop, restart, check logs

---

## Thứ tự build

```text
P0 — MVP hoạt động được:
  TASK-07 → TASK-08 → TASK-09 → TASK-10 → TASK-11

P1 — MVP tốt hơn:
  TASK-12 → TASK-13 → TASK-14

P2 — Production-ready:
  TASK-15
```
