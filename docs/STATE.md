# STATE — Hiện trạng dự án brseAI

Cập nhật lần cuối: 2026-04-29

---

## Trạng thái hiện tại

CLI engine hoàn chỉnh và ổn định. Đang chuẩn bị build meeting platform.

| Chức năng | Trạng thái |
| --- | --- |
| Realtime interpreter (mic → OpenAI Realtime WS → text + loa) | DONE |
| Device loopback input (`--device`) | DONE |
| Fallback pipeline (record → Whisper → GPT → dịch) | DONE |
| Nhận diện ngôn ngữ tự động (vi / en / ja) | DONE |
| Routing ngôn ngữ cố định (`--src`, `--tgt`) | DONE |
| Barge-in (ngắt AI khi bắt đầu nói) | DONE |
| Loa TTS (OpenAI Realtime audio output) | DONE |
| Entry point đơn giản `main.py` | DONE |
| Xóa toàn bộ code Discord | DONE |
| Meeting platform (web + SFU + interpreter service) | TODO |

---

## Cách chạy CLI (hiện tại)

```bash
# Cài môi trường (chỉ lần đầu)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Cài API key
cp .env.example .env
# Mở .env, thêm: OPENAI_API_KEY=sk-...

# Chạy — nói vào mic, AI tự dịch liên tục
python main.py

# Các tuỳ chọn phổ biến
python main.py --src vi --tgt en       # cố định Việt → Anh
python main.py --no-speaker            # chỉ hiện text, không đọc loa
python main.py --mode fallback         # dùng Whisper+GPT thay Realtime API
python main.py --list-devices          # xem danh sách mic/loa
```

---

## Cấu trúc hiện tại (CLI engine)

```text
brseAI/
├── main.py                      ← entry point duy nhất
├── requirements.txt
├── .env                         ← chỉ cần OPENAI_API_KEY
├── .env.example
├── docs/
│   ├── STATE.md
│   ├── TASKS.md
│   ├── VISION.md
│   ├── architecture.md
│   ├── realtime_protocol.md
│   └── security.md
├── src/
│   ├── common/
│   │   ├── audio.py             ← AudioInput, MicInput, DeviceLoopbackInput, SpeakerPlayer
│   │   ├── lang.py              ← detect ngôn ngữ, build prompt dịch, routing
│   │   └── logging_utils.py     ← logger stderr + print_translation stdout
│   ├── realtime/
│   │   ├── client.py            ← RealtimeClient: WebSocket session OpenAI
│   │   └── main.py              ← CLI runner realtime mode
│   └── fallback/
│       ├── pipeline.py          ← record → transcribe → translate (one-shot)
│       └── main.py              ← CLI runner fallback mode
├── tests/
│   └── test_realtime_observability.py
├── recordings/                  ← WAV clips từ fallback mode (gitignored nội dung)
└── logs/
```

## Cấu trúc mục tiêu (Meeting Platform)

```text
brseAI/
├── main.py                      ← CLI engine (giữ nguyên)
├── src/                         ← AI engine (giữ nguyên, tái sử dụng)
├── server/
│   ├── gateway/                 ← FastAPI: REST API + WebSocket signaling
│   │   ├── main.py
│   │   ├── rooms.py
│   │   └── ws.py
│   └── interpreter/             ← Python service: SFU → AI → SFU
│       ├── service.py           ← orchestrator chính
│       ├── audio_adapter.py     ← LiveKitAudioInput implements AudioInput
│       └── router.py            ← language routing per room
├── web/
│   └── client/                  ← React + TypeScript
│       ├── src/
│       │   ├── pages/           ← Home, Room
│       │   ├── components/      ← VideoGrid, TranscriptPanel, Controls
│       │   └── lib/             ← LiveKit SDK, WebSocket client
│       └── package.json
├── docker-compose.yml
└── docs/
```

---

## Checklist khởi động lại

1. Kiểm tra `.env` có `OPENAI_API_KEY` hợp lệ.
2. `python main.py --list-devices` — xác nhận mic nhận diện đúng.
3. `python main.py` — nói thử, kiểm tra dịch ra terminal.
4. Nếu Realtime API lỗi: `python main.py --mode fallback`.

---

## Change Log

| Ngày | Thay đổi |
| --- | --- |
| 2026-03-03 | Phase 1: realtime + fallback interpreter hoàn thành |
| 2026-03-03 | Language routing: `--src`, `--tgt`, `--pairs`, `--meeting-mode` |
| 2026-03-03 | Device loopback input cho realtime mode |
| 2026-03-09 | Xóa code Google Meet. Tập trung vào core translation engine |
| 2026-04-29 | Xóa toàn bộ Discord bot. Viết lại `main.py` đơn giản |
| 2026-04-29 | Viết toàn bộ docs cho meeting platform. Bắt đầu phase 2 |
