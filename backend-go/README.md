# MeetQ Go Backend Service

Backend hiệu năng cao viết bằng Golang cho MeetQ, chịu trách nhiệm xử lý toàn bộ các public API NON-AI (Authentication, Room State & Moderation, Meeting History, Search, LiveKit Egress Recordings, Admin Dashboard). Hoạt động song song với Python AI Service theo mô hình Strangler Fig.

---

## 1. Yêu Cầu Môi Trường

- **Go**: `1.22+` (khuyến nghị Go 1.24 hoặc 1.26)
- **Redis**: `7.x+` (lưu trữ room state, auth sessions, distributed locks)
- **MongoDB**: `7.x+` (lưu trữ meeting archives, recordings, system settings)
- **LiveKit Server & Egress**: SFU & Room Composite Recorder
- **S3 / RustFS**: S3-compatible object storage cho video và tài liệu họp

---

## 2. Cấu Trúc Mã Nguồn

```
backend-go/
├── cmd/
│   └── api/
│       └── main.go          # Điểm khởi chạy chính của Go service
├── internal/
│   ├── admin/               # Admin auth, dashboard overview, KPI & room inspections
│   ├── ai/                  # Client gọi nội bộ tới Python AI Service (/internal/ai)
│   ├── archive/             # S3 storage, LiveKit egress recording, retention policy
│   ├── auth/                # Google OAuth ID token, password verification, Redis sessions
│   ├── config/              # Đọc biến môi trường tương thích với Python gateway
│   ├── history/             # MongoDB collections adapter & repositories
│   ├── httpx/               # Middlewares (RequestID, AccessLog, CORS, Recovery, Context)
│   ├── livekit/             # LiveKit JWT generation & Egress client integration
│   ├── meetings/            # Lịch sử cuộc họp, CJK/Vietnamese search, transcripts
│   ├── models/              # Data structures & Enums
│   ├── notify/              # Telegram alert dispatching
│   ├── platform/            # Tiện ích thời gian tương thích định dạng Python ISO
│   ├── room/                # Room lifecycle, roles, permissions, passwords, locking
│   ├── server/              # HTTP ServeMux routes wiring & integration tests
│   └── store/               # Redis room state repository
├── Dockerfile               # Multi-stage production Docker build
├── go.mod
└── go.sum
```

---

## 3. Cấu Hình Biến Môi Trường (.env)

Go Backend đọc cùng bộ biến môi trường của Python Gateway:

```ini
PORT=8080
LOG_LEVEL=INFO
REDIS_URL=redis://localhost:6379/0
MONGODB_URL=mongodb://localhost:27017/brseai
ROOM_JWT_SECRET=dev-room-secret
ROOM_TOKEN_TTL_SECONDS=86400
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devkeysecretdevkeysecretdevkey12
LIVEKIT_WS_URL_PUBLIC=ws://localhost:7880
LIVEKIT_WS_URL_INTERNAL=ws://livekit:7880
PUBLIC_APP_URL=http://localhost:3000
PUBLIC_GATEWAY_URL=http://localhost:8080

# S3 Storage (Recordings)
MEETING_ARCHIVE_BUCKET=meetq-archive-local
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=meetq-local
AWS_SECRET_ACCESS_KEY=meetq-local-secret
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_ENDPOINT_URL=http://localhost:9000
S3_FORCE_PATH_STYLE=true

# Python AI Internal Bridge
PYTHON_AI_BASE_URL=http://localhost:8000
PYTHON_AI_SERVICE_TOKEN=meetq-internal-ai-token
```

---

## 4. Hướng Dẫn Phát Triển & Kiểm Thử

### 4.1. Chạy Tests
```bash
# Chạy toàn bộ test suite kèm race detector
go test -v -race ./...

# Chạy riêng integration test của server
go test -v -race ./internal/server/...
```

### 4.2. Định Dạng & Kiểm Tra Mã Nguồn
```bash
go fmt ./...
go vet ./...
```

### 4.3. Chạy Server Cục Bộ
```bash
go run ./cmd/api/main.go
```

---

## 5. Chạy Với Docker & Docker Compose

### 5.1. Build Docker Image
```bash
docker build -t meetq-backend-go:latest -f Dockerfile .
```

### 5.2. Chạy cùng Docker Compose toàn hệ thống
```bash
# Từ thư mục gốc dự án
docker compose up -d --build go-backend
```

---

## 6. Endpoints Cung Cấp

- **Health Checks**: `/health`, `/readiness`, `/api/health`, `/api/config`
- **Authentication**: `/api/auth/google`, `/api/auth/me`, `/api/auth/logout`
- **Rooms & Roles**: `/api/rooms`, `/api/rooms/{id}`, `/api/rooms/{id}/join`, `/api/rooms/{id}/leave`, `/api/rooms/{id}/lock`, `/api/rooms/{id}/password`, `/api/rooms/{id}/participants/{pid}/role`, `/api/rooms/{id}/participants/{pid}/mute`, `/api/rooms/{id}/participants/{pid}/remove`
- **Recordings & S3**: `/api/rooms/{id}/recordings/start`, `/api/rooms/{id}/recordings/stop`, `/api/recordings/{id}/playback`, `/api/recordings/{id}/download`
- **Meeting History & Search**: `/api/meetings`, `/api/meetings/search`, `/api/meetings/{id}/transcript`, `/api/meetings/{id}/summary`
- **Admin**: `/api/admin/auth/login`, `/api/admin/auth/me`, `/api/admin/overview`, `/api/admin/rooms/live`, `/api/admin/retention`
