# brseAI / MeetQ — System Design Docs

Bộ tài liệu này mô tả **hiện trạng thực tế của code** (snapshot 2026-10-01, branch `develop`), được viết lại từ source thay vì từ các doc lịch sử. Khi doc cũ trong `docs/` (ví dụ `architecture.md`, `STATE.md`) mâu thuẫn với bộ này, hãy ưu tiên bộ này và kiểm tra lại code.

| # | Tài liệu | Nội dung chính |
| --- | --- | --- |
| 1 | [01-system-design.md](01-system-design.md) | Kiến trúc tổng thể, các service, kênh giao tiếp, data model (Redis/Mongo), vòng đời room, BRSE modes, bảo mật, deploy, giới hạn scale |
| 2 | [02-ai-pipeline-flow.md](02-ai-pipeline-flow.md) | Flow AI end-to-end: lấy audio → ASR → kiểm định → policy → dịch → nói lại vào cuộc họp; cách thêm & lưu context; overlap; caption đa ngôn ngữ; chat dịch; meeting summary |
| 3 | [03-product-features-and-workflows.md](03-product-features-and-workflows.md) | **Không có tech.** Tính năng, quy tắc nghiệp vụ, workflow từng màn hình, hành trình người dùng, giới hạn, mẫu prompt viết tính năng mới. Dùng làm context cho AI |

## Cách đọc diagram

Tất cả diagram viết bằng **Mermaid** — hiển thị trực tiếp trên GitHub/GitLab và VS Code (Markdown Preview + extension Mermaid).

## Bản đồ code nhanh

```text
FE/src/                      React + Vite + livekit-client
BE/server/
├── brain/                   Code "chạm" model AI: prompt, realtime client, source policy, summary
├── service/
│   ├── gateway/             FastAPI REST + WebSocket, room state, fan-out event
│   ├── brain_runtime/       Daemon + RoomInterpreterManager (Perception/Understanding/Policy/Delivery)
│   ├── media/               LiveKit adapter: audio in, audio out, runtime participant
│   └── persistence/         MongoDB archive
├── integrations/            MongoDB client, Telegram
└── shared/                  Audio abstraction, logging
ops/                         nginx, livekit, mongo init
```

Tài liệu Admin Portal: [../admin/admin-overview.md](../admin/admin-overview.md) · [../admin/admin-api.md](../admin/admin-api.md)
