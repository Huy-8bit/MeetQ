# Architecture — brseAI Meeting Platform

---

## Tổng quan hệ thống

```text
┌─────────────────────────────────────────────────────────────┐
│                        BROWSER (A)                          │
│  React UI  ──  WebRTC  ──  WebSocket (signaling + events)  │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS / WSS
┌────────────────────────▼────────────────────────────────────┐
│                    GATEWAY SERVER                           │
│  FastAPI  ──  Signaling (room join/leave)  ──  Room State  │
└──────┬──────────────────────┬───────────────────────────────┘
       │                      │
┌──────▼──────┐    ┌──────────▼──────────────────────────────┐
│     SFU     │    │         INTERPRETER SERVICE              │
│  (LiveKit)  │    │  AudioRouter  ──  RealtimeClient pool   │
│             │    │  (Python core từ brseAI engine hiện tại)│
└──────┬──────┘    └──────────┬───────────────────────────────┘
       │                      │
       │              ┌───────▼──────────┐
       │              │  OpenAI Realtime │
       │              │  WebSocket API   │
       └──────────────┴──────────────────┘
```

---

## Các layer và trách nhiệm

### 1. Browser Client (Frontend)

**Tech:** React + TypeScript
**Thư mục:** `web/client/`

Trách nhiệm:

- UI phòng họp: grid video, controls, transcript panel
- WebRTC: lấy mic/camera, tạo peer connection đến SFU
- WebSocket đến Gateway: nhận transcript events, participant events
- Chọn ngôn ngữ khi vào phòng
- Hiển thị transcript song ngữ realtime

### 2. Gateway Server

**Tech:** Python FastAPI + WebSocket
**Thư mục:** `server/gateway/`

Trách nhiệm:

- REST API: tạo phòng, join, lấy config
- WebSocket: broadcast transcript và participant events
- Room state: danh sách participant, ngôn ngữ từng người
- Sinh LiveKit token cho browser khi join
- Điều phối Interpreter Service qua events

### 3. SFU — LiveKit

**Tech:** LiveKit (self-hosted hoặc LiveKit Cloud)
**Thư mục:** `server/sfu/` (config only)

Trách nhiệm:

- Nhận audio/video track từ mỗi participant qua WebRTC
- Forward track đến đúng người nghe
- Expose Python SDK để Interpreter Service subscribe/publish track

Lý do chọn LiveKit:

- SDK Python sẵn có — Interpreter Service subscribe track trực tiếp
- WebRTC internals (ICE, DTLS) được handle hoàn toàn
- Hosted option giảm ops burden cho MVP

### 4. Interpreter Service

**Tech:** Python asyncio
**Thư mục:** `server/interpreter/`

Đây là nơi brseAI engine được tích hợp vào platform.

Trách nhiệm:

- Subscribe audio track của từng speaker từ SFU
- Với mỗi utterance của speaker A, xác định routing (src → tgt cho từng người nghe)
- Chạy `RealtimeClient` để dịch — 1 client per (speaker, language_pair)
- Publish audio đã dịch lên SFU track riêng cho người nghe
- Gửi transcript text về Gateway để broadcast lên UI
- Fallback sang Whisper + GPT khi Realtime API lỗi

### 5. AI Engine (hiện có — tái sử dụng)

**Tech:** Python
**Thư mục:** `src/`

Modules được tái sử dụng trực tiếp:

- `src/realtime/client.py` — `RealtimeClient`: WebSocket session OpenAI Realtime API
- `src/common/lang.py` — detect ngôn ngữ, build instruction prompt
- `src/common/audio.py` — `AudioInput` abstraction (adapter mới: LiveKit track → AudioInput)
- `src/fallback/pipeline.py` — fallback Whisper + GPT

---

## Audio routing — ví dụ 3 người

```text
Phòng: A (vi), B (ja), C (en)

A nói tiếng Việt
  ├─ RealtimeClient(vi→ja) → audio ja → SFU track → B nghe tiếng Nhật
  └─ RealtimeClient(vi→en) → audio en → SFU track → C nghe tiếng Anh

B nói tiếng Nhật
  ├─ RealtimeClient(ja→vi) → audio vi → SFU track → A nghe tiếng Việt
  └─ RealtimeClient(ja→en) → audio en → SFU track → C nghe tiếng Anh

C nói tiếng Anh
  ├─ RealtimeClient(en→vi) → audio vi → SFU track → A nghe tiếng Việt
  └─ RealtimeClient(en→ja) → audio ja → SFU track → B nghe tiếng Nhật
```

Mỗi người nghe audio stream riêng — gốc hoặc bản dịch tương ứng ngôn ngữ của họ.

---

## Data flow chi tiết (một utterance)

```text
1.  Participant A nói vào mic (browser)
2.  WebRTC audio stream → LiveKit SFU
3.  Interpreter Service subscribe track A từ LiveKit Python SDK
4.  PCM16 frames → LiveKitAudioInput (implements AudioInput)
5.  LiveKitAudioInput → RealtimeClient._send_audio()
6.  OpenAI Realtime API: VAD → transcribe → translate → audio delta
7.  response.audio.delta (PCM16 24kHz) → SFU publish track riêng
8.  Browser B/C subscribe track → <audio> phát cho người nghe
9.  response.text.done → transcript text → Gateway WebSocket
10. Gateway broadcast transcript event → tất cả browser trong phòng
11. UI hiển thị transcript song ngữ trong transcript panel
```

---

## Tech stack

| Layer | Tech | Lý do |
| --- | --- | --- |
| Frontend | React + TypeScript | Ecosystem WebRTC tốt, type safety |
| WebRTC client | LiveKit JS SDK | Match với SFU, handle ICE/DTLS |
| UI components | shadcn/ui + Tailwind | Build nhanh cho MVP |
| Backend Gateway | Python FastAPI | Cùng ngôn ngữ với AI engine |
| WebSocket | FastAPI WebSocket | Native, không cần thêm dependency |
| SFU | LiveKit | Python SDK, self-host được |
| AI Engine | Python asyncio | Tái sử dụng brseAI engine hiện tại |
| AI Translation | OpenAI Realtime API | Proven, latency < 1s |
| AI Fallback | Whisper-1 + GPT-4o-mini | Có sẵn trong brseAI engine |
| Room state | In-memory dict (MVP) → Redis | Fast, đủ cho MVP |
| Deploy | Docker Compose | Dev đơn giản, dễ scale |

---

## REST API endpoints

```text
POST   /api/rooms                 tạo phòng mới, trả room_id + config
GET    /api/rooms/:id             thông tin phòng (participants, languages)
POST   /api/rooms/:id/join        join phòng, trả LiveKit token + room config
DELETE /api/rooms/:id/leave       leave phòng
GET    /api/health                health check
```

---

## WebSocket events (Gateway)

```text
Client → Server:
  { "type": "set_language", "lang": "vi" }
  { "type": "ping" }

Server → Client:
  { "type": "participant_joined",  "participant_id": "...", "display_name": "...", "lang": "vi" }
  { "type": "participant_left",    "participant_id": "..." }
  { "type": "language_changed",    "participant_id": "...", "lang": "en" }
  { "type": "transcript",          "speaker_id": "...", "src_lang": "vi", "tgt_lang": "en", "text": "..." }
  { "type": "interpreter_status",  "status": "active" | "fallback" | "error" }
  { "type": "pong" }
```

---

## Room state model

```python
@dataclass
class Participant:
    id: str
    display_name: str
    language: str           # "vi" | "en" | "ja"
    livekit_track_id: str
    joined_at: datetime

@dataclass
class Room:
    id: str
    created_at: datetime
    participants: dict[str, Participant]
```

---

## Deployment — Docker Compose (MVP)

```yaml
services:
  web:         # React, port 3000
  gateway:     # FastAPI, port 8000
  interpreter: # Python service, internal only
  livekit:     # SFU, port 7880 / 7881 UDP
  redis:       # port 6379, internal only
```

Production: LiveKit Cloud thay self-hosted, nginx reverse proxy, TLS Let's Encrypt.
