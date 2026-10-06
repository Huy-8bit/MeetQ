# MeetQ API Parity Matrix

Tài liệu này theo dõi mức độ tương thích và chuyển đổi API giữa **Python Gateway (FastAPI)** và **Go Backend** trong quá trình chuyển đổi kiến trúc sang mô hình Strangler Fig / Hybrid.

## Quy ước trạng thái:
- `[✓]` **Complete Go Parity**: Đã được reimplement hoàn chỉnh bằng Go, đạt 100% tương thích về URL, HTTP Method, Header, Cookie/Session, Status Code, JSON Response shape và validation. Đã có integration/unit test.
- `[~]` **Hybrid / Strangler Fig**: Go backend xử lý Authentication, State, Authorization và Persistence; đồng thời uỷ quyền các tác vụ tính toán AI sang Python AI Internal Service thông qua RPC nội bộ (`internal/ai`).
- `[P]` **Python AI Only**: Các luồng realtime media, xử lý âm thanh trực tiếp (STT, TTS, Audio Line Isolation, LLM agent loop) được giữ nguyên trong Python, không viết lại sang Go.
- `[ ]` **Not Implemented**: Chưa được triển khai.

---

## 1. Health & Configuration

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `/health` | GET | `[✓]` | `BE/server/service/gateway/main.py` | `internal/server/server.go` | Trả về `{"status":"ok"}` hoặc `{"status":"unhealthy"}` kèm check Redis & Mongo ping |
| `/readiness` | GET | `[✓]` | `BE/server/service/gateway/main.py` | `internal/server/server.go` | Trả về 200 khi dependency core sẵn sàng, 503 khi khởi động/lỗi kết nối |
| `/api/health` | GET | `[✓]` | `BE/server/service/gateway/main.py` | `internal/server/server.go` | Parity alias cho `/health` |
| `/api/config` | GET | `[✓]` | `BE/server/service/gateway/main.py` | `internal/server/server.go` | Trả về metadata cấu hình public: LiveKit WS URL, auth requirements, recording status |

---

## 2. Authentication & User Session

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `POST /api/auth/google` | POST | `[✓]` | `BE/server/service/auth/api.py` | `internal/auth/service.go` | Xác thực Google ID Token, kiểm tra whitelist domain, tạo session Redis `brseai:v1:auth:user:{id}` và set cookie `meetq_session` |
| `GET /api/auth/me` | GET | `[✓]` | `BE/server/service/auth/api.py` | `internal/auth/service.go` | Đọc cookie `meetq_session`, query Redis session, trả về thông tin user profile |
| `POST /api/auth/logout` | POST | `[✓]` | `BE/server/service/auth/api.py` | `internal/auth/service.go` | Xoá session trong Redis, invalidate cookie `meetq_session` (Set-Cookie Max-Age=0) |

---

## 3. Rooms & Meeting Lifecycle

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `POST /api/rooms` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Tạo phòng mới: validate metadata, sinh room_id, lưu state vào Redis `room:{id}`, phát Telegram alert (nếu bật) |
| `GET /api/rooms/{room_id}` | GET | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Đọc state phòng từ Redis: trả về title, languages, locks, password-protection, AI state, live participant count |
| `POST /api/rooms/{room_id}/join` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Kiểm tra password (argon2id/scrypt/bcrypt tương thích), room lock, quyền host/participant; cấp JWT token LiveKit |
| `POST /api/rooms/{room_id}/leave` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Participant rời phòng: cập nhật roster trong Redis, nếu host rời phòng xử lý lifecycle tương ứng |
| `POST /api/rooms/{room_id}/brse` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Bật/tắt AI participant / BRSE agent; broadcast control message |
| `POST /api/rooms/{room_id}/relay-mode` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Chuyển chế độ dịch song ngữ / relay (`bilingual`, `target_only`, `source_only`) |
| `POST /api/rooms/{room_id}/screenshare/start` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Đăng ký participant bắt đầu chia sẻ màn hình |
| `POST /api/rooms/{room_id}/screenshare/stop` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Dừng chia sẻ màn hình |
| `GET /api/rooms/{room_id}/permissions` | GET | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Kiểm tra quyền hạn của caller trong phòng (HOST, CO_HOST, PARTICIPANT) |
| `POST /api/rooms/{room_id}/lock` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Khoá phòng họp, chỉ HOST/CO_HOST có quyền |
| `POST /api/rooms/{room_id}/unlock` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Mở khoá phòng họp |
| `PATCH /api/rooms/{room_id}/password` | PATCH | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Đổi mật khẩu phòng họp |
| `DELETE /api/rooms/{room_id}/password` | DELETE | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Xoá mật khẩu phòng họp |
| `POST /api/rooms/{room_id}/participants/{id}/mute` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Tắt mic của người tham gia qua LiveKit Server SDK / room control |
| `POST /api/rooms/{room_id}/participants/{id}/remove`| POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Kích người tham gia khỏi phòng họp |
| `POST /api/rooms/{room_id}/participants/{id}/role` | POST | `[✓]` | `BE/server/service/gateway/api_rooms.py` | `internal/room/handler.go` | Nâng cấp / hạ cấp vai trò (HOST, CO_HOST, PARTICIPANT) |

---

## 4. Recordings & Meeting Archive (S3 / RustFS)

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `POST /api/rooms/{room_id}/recordings/start` | POST | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Gửi request start Room Composite Egress tới LiveKit; ghi nhận metadata trạng thái recording vào MongoDB |
| `POST /api/rooms/{room_id}/recordings/stop` | POST | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Dừng Egress job đang chạy; cập nhật MongoDB state |
| `GET /api/rooms/{room_id}/recordings/status` | GET | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Lấy trạng thái recording hiện thời của phòng (`idle`, `starting`, `active`, `stopping`) |
| `GET /api/recordings/{recording_id}/playback` | GET | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Sinh Presigned S3 GET URL cho streaming/playback MP4 |
| `GET /api/recordings/{recording_id}/download` | GET | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Sinh Presigned S3 GET URL kèm header `Content-Disposition: attachment; filename=...` |

---

## 5. Meeting History & Search

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `GET /api/meetings` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Phân trang cursor danh sách cuộc họp của user hiện tại, lọc theo date range |
| `GET /api/meetings/search` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Tìm kiếm full-text đa ngôn ngữ (CJK + Vietnamese) trên các cuộc họp mà user có quyền truy cập |
| `GET /api/meetings/{room_id}` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Chi tiết cuộc họp: thời gian, trạng thái, người tham gia, metadata recording |
| `GET /api/meetings/{room_id}/search` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Tìm kiếm scoped trong một cuộc họp cụ thể |
| `GET /api/meetings/{room_id}/transcript` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Phân trang cursor danh sách bản ghi audio transcript |
| `GET /api/meetings/{room_id}/relay` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Phân trang cursor danh sách câu dịch song ngữ |
| `GET /api/meetings/{room_id}/chat` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Phân trang cursor lịch sử chat text |
| `GET /api/meetings/{room_id}/summary` | GET | `[~]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Trả về summary đã lưu trong MongoDB; nếu chưa có, Go gọi Python AI internal để generate |
| `GET /api/meetings/{room_id}/participants`| GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Lịch sử danh sách người tham gia, thời gian join/leave |
| `GET /api/meetings/{room_id}/messages` | GET | `[✓]` | `BE/server/service/meetings/api.py` | `internal/meetings/handler.go` | Phân trang cursor tổng hợp timeline của cuộc họp |

---

## 6. Admin Management

| Endpoint | Method | Status | Python Implementation | Go Implementation | Ghi chú Parity |
|---|---|---|---|---|---|
| `POST /api/admin/auth/login` | POST | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Đăng nhập admin với username/password hash (Argon2id/Scrypt/Bcrypt), lưu session admin |
| `GET /api/admin/auth/me` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Lấy profile admin qua admin session cookie |
| `POST /api/admin/auth/logout` | POST | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Đăng xuất admin, xoá session cookie |
| `GET /api/admin/overview` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Thống kê KPI: live rooms, active participants, storage usage, meetings tổng |
| `GET /api/admin/rooms/live` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Danh sách các phòng đang hoạt động từ Redis |
| `GET /api/admin/rooms/{room_id}` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Chi tiết phòng live: roster, audio status, screen share status |
| `GET /api/admin/meetings` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Danh sách lịch sử toàn bộ các cuộc họp trong hệ thống |
| `GET /api/admin/meetings/{room_id}` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Chi tiết lịch sử meeting cho admin |
| `GET /api/admin/config` | GET | `[✓]` | `BE/server/service/admin/api.py` | `internal/admin/handler.go` | Xem cấu hình hệ thống hiện tại |
| `GET /api/admin/retention` | GET | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Xem chính sách lưu trữ retention hiện tại |
| `PUT /api/admin/retention` | PUT | `[✓]` | `BE/server/service/archive/api.py` | `internal/archive/handler.go` | Cập nhật cấu hình ngày lưu trữ (retention days) |

---

## 7. Python AI Internal Interface (Nội bộ giữa Go và Python)

| Endpoint | Method | Caller | Callee | Ghi chú |
|---|---|---|---|---|
| `POST /internal/ai/rooms/{room_id}/summary` | POST | Go Backend | Python AI | Yêu cầu Python tính toán tóm tắt cuộc họp (LLM prompt, key takeaways, action items) |
| `POST /internal/ai/rooms/{room_id}/final-summary` | POST | Go Backend | Python AI | Yêu cầu Python chốt tóm tắt cuối cùng khi phòng kết thúc |
| `POST /internal/ai/chat/translate` | POST | Go Backend | Python AI | Dịch tin nhắn chat qua mô hình ngôn ngữ |
| `GET /internal/ai/health` | GET | Go Backend | Python AI | Kiểm tra sức khoẻ của service AI Python |

---

## 8. Python Realtime Media & AI Ingestion (Giữ nguyên Python `[P]`)

| Tính năng | Service / Protocol | Ghi chú kiến trúc |
|---|---|---|
| Live Audio Ingestion | LiveKit WebRTC Audio Egress | Python Brain Runtime đăng ký làm LiveKit SIP/WebRTC participant |
| Line Isolation & Crosstalk cancellation | Python DSP Engine | Xử lý chống trùng tiếng và loại bỏ tiếng vọng giữa 2 kênh thoại |
| Realtime Speech-to-Text (STT) | OpenAI Realtime / Whisper | Python worker stream audio frames |
| Realtime Translation & TTS | Python Brain Runtime | Dịch câu và phát âm audio song ngữ về lại WebRTC room |
| In-room WebSocket Realtime Broadcast | Python Gateway WS Hub | WebSocket connection endpoint `/ws/rooms/{room_id}` |
