# HANDOFF — Bàn giao ngữ cảnh làm việc (chuyển máy)

Cập nhật: 2026-10-05 · Nhánh làm việc: `develop` (remote `origin` = github.com/Huy-8bit/cimopen)

Tài liệu này ghi lại toàn bộ quá trình làm việc với Claude Code trên dự án MeetQ (brseAI): đã làm gì, đang dở
ở đâu, việc gì còn chờ bạn và những ràng buộc cần giữ. Đọc mục 1–3 trước khi làm tiếp trên máy mới.

---

## 1. Tóm tắt nhanh

| Hạng mục | Trạng thái |
| --- | --- |
| Admin portal, relay mode, sửa lỗi BRSE tự nói | ✅ Xong |
| Google login (user) + admin username/password + CSRF/CORS | ✅ Xong (backend + FE) |
| Frontend production trên Cloudflare Pages (`meetqapp.com`, `www`) | ✅ Live từ 2026-10-04 |
| Backend production | ❌ Chưa deploy (không có quyền vào server) |
| Meeting Recording + Archive + Retention (LiveKit Egress → S3) | ✅ Xong, đã test E2E local |
| Tool Database Backup & Restore (MongoDB → S3) | ✅ Xong, có test integration |
| **Feature A** — Phòng họp có mật khẩu | ✅ Xong (backend + FE + test + doc 03) |
| **Feature B** — Chia sẻ màn hình chất lượng cao 30/60 FPS + âm thanh | ✅ Xong 2026-10-05 (xem mục 6), chưa test tay trên trình duyệt thật |

Kết quả test tại thời điểm bàn giao:

- Backend: `262 passed`.
- Frontend: `103 passed` (2026-10-05); `tsc --noEmit` OK; `npm run build` OK.
  - Trên Node 22+ (máy mới dùng Node 25), `localStorage` toàn cục của Node che mất bản của jsdom làm 13 test auth fail;
    `FE/src/test/setup.ts` đã thay bằng Storage trong bộ nhớ.
- Tool backup: 28 test (23 unit + 5 integration, integration cần Docker + S3 local).

---

## 2. Checklist chuyển sang máy mới

### 2.1 File KHÔNG có trong git — phải copy tay từ máy cũ (qua kênh an toàn, không gửi qua chat)

| File | Nội dung |
| --- | --- |
| `.env` | Biến môi trường gốc cho docker compose (OpenAI key, Mongo, LiveKit, …) |
| `.env.local` | Cấu hình local |
| `.env.deploy` | Cloudflare API token + account id để deploy FE |
| `BE/.env` | Biến môi trường backend khi chạy ngoài Docker |
| `.env.backup` (nếu đã tạo) | Cấu hình tool backup DB |
| `infra/terraform/frontend/terraform.tfstate.d/prod/terraform.tfstate` (+ `.backup`) | **Quan trọng:** state Terraform của Cloudflare prod (state đang để local). Mất file này thì Terraform không còn biết các resource đang chạy. |
| `infra/terraform/storage/terraform.tfstate.d/` | Workspace của module storage (chưa apply, nhưng copy cho đủ) |

Tất cả các file trên đều đã nằm trong `.gitignore`. Các file `*.example` tương ứng đã có trong repo để tham khảo.

### 2.2 Công cụ cần cài

- Docker Desktop (compose v2).
- Node.js 20+ và npm (FE: React 18 + Vite + TS).
- Python 3.12 (BE dùng `BE/.venv`).
- Terraform ≥ 1.6 và Wrangler (Cloudflare CLI) để deploy.
- AWS CLI (nếu apply module storage/db-backups).
- Không bắt buộc:
  - `shellcheck` (cho `make infra-check`).
  - MongoDB Database Tools; nếu không cài thì tool backup tự chạy chúng trong Docker image `mongo:<major>`.

### 2.3 Dựng lại môi trường

```bash
git clone https://github.com/Huy-8bit/cimopen.git brseAI && cd brseAI
git checkout develop
# copy các file ở mục 2.1 vào đúng chỗ

# Backend
python3.12 -m venv BE/.venv && BE/.venv/bin/pip install -r BE/requirements.txt

# Frontend
make fe-install

# Stack local: redis, mongo, livekit, s3 (RustFS), egress, gateway, interpreter
make local-services      # hoặc: make dev
make fe-dev

# Kiểm tra
(cd BE && .venv/bin/python -m pytest -q)
make fe-test
make db-backup-test      # tool backup (tự tạo venv tools/db_backup/.venv)
make infra-check         # terraform fmt/validate + shellcheck
```

Chạy `make help` để xem toàn bộ target. Các target chính gồm:

- `deploy-dev` / `deploy-prod`, `destroy-*`
- `db-backup`, `db-backup-list`, `db-restore-test`
- `logs`, `ps`

---

## 3. Việc còn chờ BẠN làm (không tự động được)

1. **Xoay vòng (rotate) các secret đã từng dán vào chat:**
   - Cloudflare API token (`cfut_…`, đang nằm trong `.env.deploy`)
   - OPENAI_API_KEY
   - Telegram bot token
   - mật khẩu MongoDB

   Sau khi tạo mới, cập nhật lại các file `.env*` tương ứng.
2. **Google OAuth Client ID:**
   - Tạo client ID theo `docs/google-login-setup.md`.
   - Đặt `GOOGLE_CLIENT_ID` cho backend và `VITE_GOOGLE_CLIENT_ID` cho FE.
   - Chạy lại `make deploy-prod`, lần này **không** kèm `ALLOW_MISSING_GOOGLE_CLIENT_ID=1`.
3. **Deploy backend production:**
   - `api.meetqapp.com` (217.15.164.206) hiện là Traefik với cert self-signed và trả 404. Claude không có quyền vào server.
   - Cần TLS hợp lệ.
   - Cần đặt các biến: `CORS_ALLOWED_ORIGINS=https://meetqapp.com`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` (tạo hash bằng `python -m server.service.auth.passwords`), cùng các biến archive `ARCHIVE_AWS_*`.
   - Dùng `docker-compose.prod.yml`.
4. **Terraform cho S3 (mới chỉ chạy `plan`, cố ý chưa `apply`):**
   - `infra/terraform/storage`: bucket ghi âm/archive (plan: 9 resource).
   - `infra/terraform/db-backups`: bucket backup DB.
   - Xem README trong từng thư mục.
5. **Lịch backup DB trên server:**
   - Chạy `scripts/install-backup-schedule.sh` (systemd, 02:00 hằng ngày) hoặc `--print-cron`.
   - Unit mẫu nằm ở `deploy/systemd/`.

---

## 4. Ràng buộc phải giữ (đã thống nhất trong quá trình làm)

- Không commit secret thật. Không log hay echo secret, token, API key, presigned URL hoặc AWS secret.
- Không log raw transcript hay chat ở production. Không đưa transcript raw ra browser console. Không render stack trace backend lên UI.
- `/admin` bắt buộc đăng nhập. Admin API không public. Admin không bao giờ thấy mật khẩu phòng, chỉ thấy "Password protected / Public link".
- **Không đụng** vào tài nguyên AWS của dự án khác:
  - bucket `vstep-…`
  - CloudFront `E50RZVSAC9PO6`
  - các record DNS của ACM/SES
- Không tự `terraform apply` hạ tầng production. Chỉ chạy `plan`.
- Tool backup:
  - S3 luôn private, có checksum trước khi restore.
  - Không ghi đè production nếu chưa có xác nhận (`--confirm-production` + gõ `RESTORE PRODUCTION`).
  - Không tự drop DB production.
- Mật khẩu phòng: không lưu plaintext, không trả về trong API, không đặt vào URL, log hay localStorage.
- Ghi âm: không ghi âm ẩn. Mọi người, kể cả người vào sau, đều thấy chỉ báo REC. Nội dung hết hạn phải bị **xóa thật** khỏi S3 và Mongo.
- Chỉ commit khi được yêu cầu.

---

## 5. Kiến trúc & quá trình làm việc

### 5.1 Stack

- **FE** (`FE/`):
  - React 18 + Vite + TypeScript + react-router v6, `livekit-client` 2.18.7.
  - Admin portal nằm trong `FE/src/admin`.
- **BE** (`BE/`):
  - FastAPI gateway (`server/service/gateway`) và interpreter/brain daemon (`server/service/brain_runtime`).
  - Redis giữ trạng thái phòng (TTL), MongoDB 7 standalone giữ lịch sử.
  - LiveKit self-hosted; tên room LiveKit = `room_id`.
- **AI relay**: OpenAI Realtime (`server/brain/realtime`), fallback pipeline (`server/brain/fallback`).
- Tài liệu thiết kế:
  - `docs/system-design/01..03` (03 là tài liệu sản phẩm/luồng màn hình).
  - `docs/architecture.md`, `docs/security.md`.

### 5.2 Các chặng đã làm (theo thứ tự thời gian)

1. Viết docs và trả lời câu hỏi về pipeline AI.
2. Admin portal: overview, live rooms, meetings, AI relay, issues, analytics, settings. Xem `docs/admin/`.
3. Relay mode: đổi Voice + Text ↔ Text only ngay trong phòng.
4. Sửa lỗi BRSE tự nói khi không có ai nói (`BE/tests/test_no_unprompted_speech.py`).
   - Liên quan: speaker line isolation cho audio LiveKit (`server/service/livekit_lines`).
5. Auth và hạ tầng FE:
   - Google login (cookie `meetq_session`) và admin login (cookie `meetq_admin_session`, hash scrypt).
   - CSRF origin check, CORS allowlist.
   - Code ở `BE/server/service/auth`. Contract: `docs/auth-backend-contract.md`.
6. Deploy FE lên Cloudflare Pages bằng Terraform + Wrangler, một lệnh (`make deploy-prod`, `scripts/deploy.sh`).
   - Project `meetq-prod`, workspace Terraform `prod`.
   - CNAME apex/www đã được import vào Terraform.
   - Pages tự redirect http→https.
   - Xem `docs/deployment-cloudflare.md`.
7. Sửa 4 test cũ đang fail.
8. **Meeting Recording + Archive + Retention** (mục 5.3).
9. **Tool Database Backup & Restore** (mục 5.4).
10. **Feature A — phòng có mật khẩu** (mục 5.5).
11. **Feature B — screen share chất lượng cao** (mục 6, đang dở).

### 5.3 Recording / Archive / Retention

Chi tiết đầy đủ: `docs/meeting-recording-and-retention.md`.

**Luồng ghi âm**
- LiveKit Egress Room Composite (layout `speaker`) ghi MP4 thẳng lên S3.
  - Cấu hình egress phải để dưới `storage: s3:`. Key `s3:` ở top-level bị bỏ qua.
- State ghi âm lưu ở Mongo `meeting_recordings` (CAS theo status, có `version`).
- Event `recording.*` phát qua WS.

**Archive theo phòng**
- Lưu ở `meeting_archives` (`arc_<roomhex>`), trạng thái: open → finalizing → processing_recording → ready/partial/failed → deleting → deleted.
- Layout S3: `meetings/<room>/<archive>/{manifest,meeting,participants,transcript,relay,chat,summaries}.json` và `recordings/<id>.mp4`.

**Retention**
- Mặc định 7 ngày, snapshot theo từng archive, admin override được.
- Worker cleanup xóa thật S3 + Mongo, chỉ để lại tombstone; user nhận 410.
- Meeting cũ trước `system_settings.archive_lifecycle.managed_since` không bị quản lý.

**Code**
- BE: `BE/server/service/archive/*`, `BE/server/service/admin/archives_api.py`.
- FE: `RecordingControls`, `useRoomRecording`, `pages/meetings/*`, `admin/pages/RecordingsPage`, `ArchiveDetailPage`.

**Hạ tầng local và Terraform**
- S3 local là **RustFS** (`rustfs/rustfs`, cổng 9000, key `meetq-local` / `meetq-local-secret`). MinIO và LocalStack không còn pull được.
- Terraform: `infra/terraform/storage` (chưa apply).

**API**
- User:
  - `POST /api/rooms/{id}/recordings`, `…/{rec}/stop`, `GET …/current`
  - `GET /api/meetings`, `/api/meetings/{room}`, `…/messages`
  - `/api/recordings/{id}` (+ `playback-url` / `download-url`)
- Admin:
  - `/api/admin/recordings`, `/api/admin/archives/{id}`
  - `PATCH /api/admin/settings/retention`, `PATCH /api/admin/archives/{id}/retention`
  - `DELETE /api/admin/archives/{id}`

### 5.4 Tool Database Backup & Restore

Chi tiết: `docs/database-backup-restore.md`. Code ở `tools/db_backup/`. DB là MongoDB (không phải PostgreSQL).

**Cơ chế backup**
- `mongodump --archive --gzip`, sau đó kiểm tra bằng `mongorestore --dryRun`.
- SHA-256 tính theo stream. File manifest được upload sau cùng và đóng vai trò dấu hiệu backup đã hoàn tất.
- Mật khẩu truyền qua file `--config` (quyền 0600), không xuất hiện trên command line.
- Khóa `flock` chống chạy đồng thời.
- Exit code: 0/2/3/4/5/6/7/130.

**Lưu trữ và thông báo**
- Key S3: `database-backups/<env>/<YYYY>/<MM>/<DD>/<id>/{database.archive.gz,manifest.json}`.
- Telegram báo khi backup lỗi.

**Lệnh**
- Các lệnh: `backup | list | info | download | verify | restore | restore-test | prune | cleanup-local`.
- Script bọc: `scripts/db-backup.sh`, `db-backup-list.sh`, `db-restore.sh`.

**Hạ tầng**
- Terraform: `infra/terraform/db-backups` (chưa apply). Lifecycle: dev/staging 14 ngày, prod 30 ngày.
- `docker-compose.prod.yml` publish Mongo chỉ trên `127.0.0.1:27017` để tool chạy trên host truy cập.

### 5.5 Feature A — Phòng họp có mật khẩu (xong)

**Backend**
- `BE/server/service/gateway/room_access.py`:
  - Hash Argon2id (`argon2-cffi`, m=19456, t=2, p=1). Hash lưu trong key Redis riêng `room:{id}:access`, cùng TTL với phòng. Hash không bao giờ nằm trong RoomState hay Mongo.
  - Đếm lần nhập sai theo (room, IP) và (room, user): tối đa 10 lần / 10 phút, vượt thì trả 429 kèm `Retry-After`.
- Model:
  - `CreateRoomRequest.access` (`"link"` hoặc `"password"`) và `password` (6–128 ký tự, không có quy tắc phức tạp).
  - `JoinRoomRequest.password`.
  - `password_required` trong RoomState, các response và Mongo room doc.
- Join (`room_service.join_room`) kiểm tra mật khẩu **trước** khi phát token. Các lỗi trả về:
  - `room_password_required` (403)
  - `invalid_room_password` (403, "Incorrect meeting password.")
  - `room_password_rate_limited` (429)
- `GET /api/rooms/{id}` khi không có room token: phòng có mật khẩu chỉ trả thông tin cấu hình. Ẩn tên người tham gia, transcript và chat; vẫn trả số người.
- Summary của phòng có mật khẩu chỉ đọc được khi có room token hoặc user đã từng join.
- `main.py`: handler lỗi 422 bỏ `input`/`ctx` để không trả lại mật khẩu. Lỗi liên quan mật khẩu có code `invalid_room_password_setting`.
- Admin: `password_protected` trong LiveRoomRow / MeetingRow; trang chi tiết hiển thị "Access: Password protected / Public link".

**Frontend**
- `RoomAccessFields` + `ui/PasswordInput` + `lib/roomAccess.ts` trên HomePage:
  - "Room access: Anyone with the link / Require a password".
  - Ô Password và Confirm password.
- Lobby (`JoinRoomCard`):
  - Dòng "This meeting requires a password." và ô "Meeting password".
  - Lỗi hiển thị ngay dưới ô nhập.
  - Danh sách người tham gia chỉ hiện số lượng.

**Test**
- `BE/tests/test_room_password.py` (22 test).

Doc 03 đã cập nhật (R-06…R-09, S1, S2, mục 14–16). Có thể viết thêm test FE cho RoomAccessFields và lobby.

---

## 6. Feature B — Screen share chất lượng cao (XONG 2026-10-05)

### 6.1 Đã xong

- **Backend (quan trọng, đã sửa bug thật):**
  - `livekit_runtime._is_human_microphone_audio` giờ chỉ nhận `rtc.TrackSource.SOURCE_MICROPHONE`.
  - Trước đây code so tên chứa "screen" trên một giá trị int protobuf (screen-share audio = 4). Điều kiện đó không bao giờ khớp, nên audio share màn hình sẽ bị đưa vào AI.
  - Test: `BE/tests/test_brse_audio_sources.py`.
- **`FE/src/lib/livekit.ts`:**
  - Có 2 profile trong `SCREEN_SHARE_PROFILES`, đã ghi chú trong code:

    | Profile | Capture | Layer trên | Layer thấp (simulcast) | contentHint | Degradation |
    | --- | --- | --- | --- | --- | --- |
    | `detail` — "High quality" (mặc định) | 1920×1080 ≤ 30 fps | 5 Mbps / 30 fps | 720p15 @ 1.5 Mbps | detail | maintain-resolution |
    | `motion` — "Smooth motion" | 1920×1080 ≤ 60 fps | 8 Mbps / 60 fps | 720p30 @ 2.5 Mbps | motion | maintain-framerate |

  - `publishScreenShareTrack(room, { quality, includeAudio })`:
    - Tự gọi `getDisplayMedia` với ràng buộc `ideal`/`max` (không upscale) và audio tùy chọn (tắt xử lý giọng nói). Nếu engine không chịu ràng buộc thì thử lại với tùy chọn đơn giản.
    - Đọc `track.getSettings()`; chỉ log khi chạy DEV.
    - Publish tối đa 1 track video + 1 track audio màn hình (`ScreenShareAudio`).
    - Trả về `audioUnavailable` khi người dùng xin audio mà không nhận được.
  - Lỗi: `ScreenShareCancelledError` khi người dùng đóng picker (không phải lỗi thật) và `ScreenShareUnsupportedError`.
  - Phát hiện khả năng bằng `isScreenShareSupported()`, không sniff UA. Đã xóa hàm sniff Safari 17 cũ.
  - `unpublishScreenShareTrack(room, video, audio)` gỡ cả hai track.
  - `HumanAudioFeed` có thêm `source` (`microphone` | `screen_share_audio`) và `trackSid`.
  - Audio màn hình của người khác đã phát được qua `AudioTrackSink`; key sink `human-${participantId}-${track.sid}` là duy nhất.

### 6.2 Đã làm thêm ngày 2026-10-05

- `useMeetingRoom.ts`: `startScreenShare({ quality, includeAudio })`; `localScreenAudioTrackRef`; video `ended` → dừng cả 2 track,
  audio `ended` → chỉ gỡ audio; bỏ lỗi "ended from browser controls"; `screenShareNotice`, `canShareScreen`.
  Helper export: `buildScreenShareNotice`, `screenShareStartErrorMessage`.
- `ScreenShareDialog.tsx` (mới): 2 lựa chọn chất lượng, "Include shared audio" luôn tắt khi mở; chỉ nhớ chất lượng
  (`meetq:screen-share-quality`, helper trong `lib/uiPreferences.ts`). Nút "Share" gọi `startScreenShare` đồng bộ.
- `RoomControlBar`: prop `canShareScreen`; khi không hỗ trợ dùng `aria-disabled` + tooltip. `RoomPage`: mở dialog, hiện notice.
- `MeetingStage`: `ScreenShareActions` = nút "Full screen" (chỉ khi `document.fullscreenEnabled`) + Pin; CSS `:fullscreen` nền đen.
- Test mới: `lib/livekit.screenShare.test.ts`, `components/ScreenShareDialog.test.tsx`,
  `features/room/useMeetingRoom.screenShare.test.ts`, `features/room/screenShareMessages.test.ts`.
- Doc 03: R-60…R-64, S3.2–S3.4, mục 14–16 (G18–G20).

**Còn lại:** test tay trên Chrome/Edge/Firefox/Safari (share tab có audio, 60 FPS, dừng bằng nút native, fullscreen).

Giới hạn trình duyệt cần ghi vào doc:
- Chrome và Edge chia sẻ được audio của tab. Audio toàn hệ thống chỉ có trên Windows/ChromeOS.
- Firefox và Safari thường không có shared audio. Khi đó UI hiện warning, việc share màn hình vẫn tiếp tục.
- Điện thoại và tablet không có `getDisplayMedia`.

---

## 7. Gotchas đã gặp (đừng lặp lại)

- **S3 local:**
  - Image `minio/minio` và quay MinIO không pull được; `localstack/localstack:s3-latest` đã ngừng. Dùng RustFS.
  - Egress: `EGRESS_CONFIG_BODY` phải dùng `storage: s3:`. Nếu sai, egress ghi `/meetings/...` local và báo lỗi "mkdir /meetings: permission denied".
- **MongoDB 7 standalone:**
  - Không có `--oplog`.
  - Không đếm được `system.views` (bỏ qua `system.*`).
  - Biến credential trong compose là `MONGODB_ROOT_*`, không phải `MONGO_INITDB_*`.
- **Test harness:**
  - `managed_since` khiến meeting test bị coi là legacy, nên phải lùi mốc thời gian.
  - `FakeRedis` trong `BE/tests/conftest.py` là bản tối giản. Đã thêm `set(nx)` và `incr`; nếu code dùng lệnh Redis mới thì phải thêm vào đây.
  - Test tạo `rtc.Room()` trong fixture sync sẽ lỗi khi chạy cả suite (không có event loop). Dùng `LiveKitRuntime.__new__`.
- **CLI backup:** giá trị `AWS_*` trong env file phải được đẩy vào `os.environ` thì boto3 mới thấy.
- **shellcheck:** cần `-x -P SCRIPTDIR/..` và `# shellcheck source=`.
- **Docker:** sau `compose up gateway`, container interpreter có thể bị dừng. Kiểm tra bằng `make ps`.
- **FE:**
  - Prop của `SkeletonLines` là `count`.
  - Các trang có `UserMenu` cần `AuthProvider` trong test.
- **Repo:** `.wrangler/cache/pages.json` đang được commit. File chỉ có account id và tên project, không phải secret, nhưng có thể đưa vào `.gitignore`.

---

## 8. Chỉ mục tài liệu

| File | Nội dung |
| --- | --- |
| `docs/DEVELOPMENT.md` | Hướng dẫn dev |
| `docs/system-design/01-system-design.md` | Thiết kế hệ thống |
| `docs/system-design/02-ai-pipeline-flow.md` | Luồng AI relay |
| `docs/system-design/03-product-features-and-workflows.md` | Tính năng, màn hình, rule R-xx |
| `docs/admin/` | Admin portal |
| `docs/auth-backend-contract.md`, `docs/google-login-setup.md` | Auth |
| `docs/deployment-cloudflare.md` | Deploy FE |
| `docs/meeting-recording-and-retention.md` | Ghi âm / archive / retention |
| `docs/database-backup-restore.md` | Tool backup DB |
| `docs/security.md` | Bảo mật |
| `docs/STATE.md`, `docs/TASKS.md` | Trạng thái/tác vụ cũ (cập nhật lần cuối 2026-04-29, đã lỗi thời so với file này) |

Khi mở phiên Claude Code mới trên máy mới, hãy bảo Claude đọc `docs/HANDOFF.md` trước. Feature A/B đã xong; việc còn lại xem mục 3 và mục 6.2.
