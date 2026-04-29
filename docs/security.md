# Security

---

## API Keys và Secrets

### Nguyên tắc

- `OPENAI_API_KEY` là secret duy nhất cần thiết cho CLI engine hiện tại.
- Platform sẽ cần thêm: `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `REDIS_URL`.
- Không bao giờ commit key thật vào git. `.env` đã có trong `.gitignore`.
- Dùng `.env.example` làm template — chỉ chứa key names, không có giá trị thật.

### Lưu trữ

| Môi trường | Cách lưu |
| --- | --- |
| Local dev | File `.env` local |
| Production | Environment variables qua secrets manager (AWS Secrets Manager, Doppler, v.v.) |
| CI/CD | GitHub Actions secrets |

---

## Xác thực phòng họp

### Room token (MVP)

- Khi join phòng, Gateway sinh một short-lived JWT token (TTL 24h).
- Token mã hóa: `room_id`, `participant_id`, `issued_at`.
- LiveKit token được sinh riêng từ `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` — chỉ cấp quyền publish/subscribe cho room cụ thể.
- Token **không được lưu phía client** vào localStorage — chỉ dùng trong memory cho session hiện tại.

### Room ID

- Room ID sinh ngẫu nhiên (UUID v4 hoặc short slug), không predictable.
- Không có danh sách phòng công khai — chỉ ai có link mới vào được.

---

## Dữ liệu âm thanh

### CLI engine (hiện tại)

- Realtime mode: audio stream in-memory qua WebSocket đến OpenAI. Không lưu file.
- Fallback mode: WAV clip lưu vào `recordings/clip_<timestamp>.wav` trước khi transcribe. Coi `recordings/` là dữ liệu nhạy cảm.

### Platform (tương lai)

- Audio của participant **không được lưu** trên server trừ khi có tính năng recording được bật tường minh.
- Audio stream từ SFU đến Interpreter Service chỉ tồn tại trong memory (buffer để xử lý), không persist.
- Transcript text có thể lưu tạm trong Redis để hiển thị lại khi participant reconnect — TTL 24h, sau đó tự xóa.

---

## Transport

| Kết nối | Protocol | Ghi chú |
| --- | --- | --- |
| Browser ↔ Gateway | HTTPS / WSS (TLS) | Bắt buộc trong production |
| Browser ↔ SFU | WebRTC (DTLS-SRTP) | Mã hóa audio/video end-to-end ở transport layer |
| Interpreter ↔ OpenAI | WSS | `wss://api.openai.com/v1/realtime` |
| Interpreter ↔ SFU | Internal (Docker network) | Không expose ra ngoài |

### Lưu ý WebRTC

WebRTC DTLS-SRTP mã hóa media stream giữa browser và SFU — SFU giải mã để forward, không phải E2E encryption toàn đường. Đây là trade-off cần thiết để Interpreter Service có thể đọc audio.

---

## Logging

### Hiện tại (CLI)

- Operational log → stderr qua `logging` module.
- File logging không bật mặc định.
- Translation text và transcript có thể xuất hiện trong log ở một số flow (fallback pipeline, `response.text.done`).

### Platform

- Không log nội dung transcript vào file log production.
- Log chỉ chứa metadata: `room_id`, `participant_id`, event type, latency, error codes.
- Nếu cần debug transcript: dùng flag tường minh `DEBUG_LOG_TRANSCRIPT=true`, chỉ trong môi trường dev có kiểm soát.
- Không bao giờ log API key, auth header, hay LiveKit token.

---

## Privacy

### Yêu cầu tối thiểu trước khi dùng trong môi trường thật

- [ ] Thông báo rõ ràng cho participant rằng âm thanh được xử lý bởi AI (OpenAI API).
- [ ] Chính sách lưu trữ và xóa dữ liệu được định nghĩa.
- [ ] Không ghi âm tự động — recording phải là opt-in tường minh.
- [ ] Tuân thủ quy định địa phương về ghi âm cuộc trò chuyện (GDPR, PDPA, v.v.) nếu deploy ra ngoài.

### Dữ liệu gửi lên OpenAI

Mỗi utterance được gửi tới OpenAI Realtime API để transcribe và dịch. Tham khảo [OpenAI Privacy Policy](https://openai.com/policies/privacy-policy) để biết chi tiết về cách OpenAI xử lý dữ liệu audio.

---

## Khuyến nghị vận hành

1. Rotate `OPENAI_API_KEY` định kỳ hoặc sau mỗi demo có người ngoài.
2. Giới hạn quyền API key (nếu OpenAI hỗ trợ) chỉ cho Realtime API và Audio API.
3. Đặt quota alert trên OpenAI dashboard để tránh overspend.
4. Trong production: restrict outbound từ Interpreter Service chỉ đến `api.openai.com` và LiveKit server.
5. Set `recordings/` permission `700` nếu fallback mode được dùng.
