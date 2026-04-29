# Realtime Protocol

Tài liệu này mô tả toàn bộ WebSocket event contract — cả OpenAI Realtime API lẫn internal WebSocket Gateway của platform.

---

## Phần 1 — OpenAI Realtime API (AI Engine)

Implement trong `src/realtime/client.py`. Tham chiếu: [OpenAI Realtime WebSocket docs](https://platform.openai.com/docs/guides/realtime-websocket)

### Session config client gửi lên

Khi kết nối WebSocket, client gửi `session.update` với:

```json
{
  "type": "session.update",
  "session": {
    "modalities": ["text", "audio"],
    "instructions": "<built by src/common/lang.py>",
    "input_audio_format": "pcm16",
    "input_audio_transcription": { "model": "whisper-1" },
    "output_audio_format": "pcm16",
    "voice": "alloy",
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.5,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 700
    },
    "temperature": 0.8
  }
}
```

Khi chỉ cần text (không có loa): `modalities: ["text"]`, bỏ `output_audio_format` và `voice`.

Khi routing ngôn ngữ thay đổi (auto-detect mode): gửi lại `session.update` với `instructions` mới.

### Sequence cơ bản

```text
Client                          OpenAI Realtime WS
  |-- session.update ---------->|
  |<-- session.created ---------|
  |<-- session.updated ---------|
  |                             |
  |-- input_audio_buffer.append (loop mỗi ~20ms)
  |                             |
  |<-- speech_started ----------|  (VAD phát hiện tiếng nói)
  |<-- speech_stopped ----------|  (VAD phát hiện im lặng)
  |<-- input_audio_buffer.committed
  |<-- transcription.completed -|  → [You] text
  |<-- response.created --------|  → in [Interp]
  |<-- response.text.delta* ----|  → stream bản dịch text
  |<-- response.audio.delta* ---|  → stream audio PCM16 24kHz
  |<-- response.audio.done -----|  → flush player
  |<-- response.text.done ------|
  |<-- response.done -----------|
```

### Server events được xử lý

| Event | Hành động |
| --- | --- |
| `session.created` | Log session ID |
| `session.updated` | Log config applied |
| `input_audio_buffer.speech_started` | Log; nếu AI đang nói → gửi `response.cancel` + restart player (barge-in) |
| `input_audio_buffer.speech_stopped` | Log |
| `input_audio_buffer.committed` | Debug log |
| `conversation.item.input_audio_transcription.delta` | Print `[You]` delta (debug mode) |
| `conversation.item.input_audio_transcription.completed` | Print `[You] transcript`; trigger language routing update nếu cần |
| `response.created` | Mark `assistant_speaking=True`; print `[Interp]` |
| `response.text.delta` | Stream text ra stdout / WebSocket |
| `response.text.done` | Newline; log |
| `response.audio.delta` | Decode base64 PCM16 → push SpeakerPlayer hoặc SFU track |
| `response.audio.done` | Flush player (thêm 50ms silence để không bị cắt) |
| `response.done` | Mark `assistant_speaking=False` |
| `error` | Log; nếu auth error → abort session |

### Client events gửi đi

| Event | Mục đích |
| --- | --- |
| `session.update` | Cấu hình session, cập nhật instructions khi routing đổi |
| `input_audio_buffer.append` | Stream audio liên tục mỗi ~20ms |
| `response.cancel` | Ngắt response đang chạy (barge-in) |

### Barge-in logic

```text
Điều kiện: speech_started nhận được khi _assistant_speaking == True

Hành động:
  1. player.restart()         → cắt audio đang phát ngay lập tức
  2. send response.cancel     → báo OpenAI dừng generate
  3. _assistant_speaking = False
  4. _current_response_id = None
```

### Audio format

| Chiều | Format | Sample rate |
| --- | --- | --- |
| Client → OpenAI (input) | PCM16 mono, base64 | 16000 Hz (default) |
| OpenAI → Client (output) | PCM16 mono, base64 | 24000 Hz |

---

## Phần 2 — Gateway WebSocket (Platform)

WebSocket endpoint: `wss://host/ws/rooms/:room_id?token=<join_token>`

Dùng để: signaling phòng họp, broadcast transcript, participant events.

### Client → Server

```json
{ "type": "set_language", "lang": "vi" }
{ "type": "ping" }
```

### Server → Client

```json
{ "type": "participant_joined", "participant_id": "abc", "display_name": "Huy", "lang": "vi" }
{ "type": "participant_left",   "participant_id": "abc" }
{ "type": "language_changed",   "participant_id": "abc", "lang": "en" }
{ "type": "transcript", "speaker_id": "abc", "src_lang": "vi", "tgt_lang": "en", "text": "Hello", "ts": 1234567890 }
{ "type": "interpreter_status", "status": "active" }
{ "type": "pong" }
```

### Transcript event chi tiết

`transcript` event được gửi đến **từng participant** với `tgt_lang` là ngôn ngữ của họ.  
Participant nghe ngôn ngữ gốc vẫn nhận event với `src_lang == tgt_lang` (dùng để hiển thị transcript gốc).

---

## Phần 3 — Audio routing trong platform

Trong meeting platform, `RealtimeClient` không nhận mic và không phát ra loa.  
Thay vào đó, Interpreter Service đóng vai trò bridge:

```text
LiveKit track (speaker A) → LiveKit Python SDK subscribe
  → PCM16 frames → LiveKitAudioInput (implements AudioInput)
    → RealtimeClient._send_audio()
      → OpenAI Realtime WS
        → response.audio.delta
          → SFU publish (track riêng cho participant B)
            → LiveKit JS SDK subscribe (browser B)
              → <audio> element phát cho người nghe B
```

`LiveKitAudioInput` là adapter mới cần viết trong `server/interpreter/audio_adapter.py`, implement interface `AudioInput` từ `src/common/audio.py`.

---

## Phần 4 — Language routing trong platform

Mỗi participant khai báo ngôn ngữ khi join (`set_language`).  
Interpreter Service build routing table khi có người nói:

```text
Room participants:
  A: lang=vi
  B: lang=ja
  C: lang=en

A nói → cần dịch cho:
  B: RealtimeClient(src=vi, tgt=ja)
  C: RealtimeClient(src=vi, tgt=en)
  A: không dịch (gốc)

→ Tạo 2 RealtimeClient, mỗi cái stream audio output ra track riêng trên SFU
```

Khi participant đổi ngôn ngữ (`set_language` mới): Interpreter Service hủy client cũ, tạo client mới với routing mới.
