# VISION — brseAI Meeting Platform

> Nền tảng họp trực tuyến tích hợp phiên dịch AI realtime.  
> Người Việt nói tiếng Việt. Người Nhật nói tiếng Nhật. Cả hai hiểu nhau ngay lập tức.

---

## Vấn đề cần giải quyết

Các nền tảng họp hiện tại (Google Meet, Zoom, Teams) **không có phiên dịch tích hợp**.  
Giải pháp hiện tại rất tệ:

- Thuê phiên dịch viên người thật → đắt, chậm, không scale
- Google Meet "live captions" chỉ dịch text, không dịch giọng nói sang giọng nói
- Zoom AI companion chỉ summary sau cuộc họp, không realtime
- Không có nền tảng nào cho phép mỗi người nói ngôn ngữ mẹ đẻ và nghe bằng ngôn ngữ của mình ngay lập tức

---

## Giải pháp

**brseAI Meeting** = WebRTC meeting platform + AI interpreter engine tích hợp sâu.

Mỗi participant:
1. Nói bằng ngôn ngữ của mình (vi / en / ja)
2. Giọng nói được stream lên server
3. AI dịch realtime, tạo ra audio bằng ngôn ngữ của người nghe
4. Người kia nghe bản dịch giọng nói, không cần làm gì

Giống như có một phiên dịch viên chuyên nghiệp ngồi trong phòng, nhưng:
- Không thêm độ trễ đáng kể (< 2 giây end-to-end)
- Không giới hạn số phòng
- Hỗ trợ nhiều cặp ngôn ngữ đồng thời

---

## Demo hiện có (CLI engine)

`main.py` — chạy trên máy cục bộ, nói vào mic, AI dịch và đọc lại ngay.  
Engine này là **core** của toàn bộ platform. Đã hoạt động ổn định với:
- OpenAI Realtime API (WebSocket streaming)
- Nhận diện ngôn ngữ tự động (vi / en / ja)
- Barge-in: ngắt AI ngay khi người dùng bắt đầu nói lại
- Fallback pipeline (Whisper + GPT) khi Realtime API không khả dụng

---

## Target users (MVP)

| Nhóm | Nhu cầu |
| --- | --- |
| Công ty Nhật - Việt | Họp kỹ thuật, báo cáo tiến độ hàng tuần |
| Startup làm việc với khách hàng quốc tế | Sales call, demo, support |
| Giáo viên / học sinh đa quốc gia | Lớp học online |
| Freelancer nhận dự án nước ngoài | Onboarding, standup |

MVP tập trung vào cặp ngôn ngữ **Việt–Nhật–Anh**, 2–8 người trong một phòng.

---

## Differentiators

| Tính năng | Google Meet | Zoom | brseAI |
| --- | --- | --- | --- |
| Phiên dịch giọng nói realtime | Không | Không | **Có** |
| Mỗi người nghe ngôn ngữ của mình | Không | Không | **Có** |
| Không cần plugin hay app | Không | Không | **Có (Web)** |
| Tích hợp sâu, không cần tab mở song song | Không | Không | **Có** |
| Transcript song ngữ | Không | Không | **Có** |

---

## Scope MVP

### Trong scope

- Phòng họp web (tối đa 8 người)
- Video + audio 2 chiều (WebRTC)
- AI interpreter: mỗi người nói → AI dịch → người khác nghe
- Mỗi user chọn ngôn ngữ của mình khi vào phòng
- Transcript song ngữ realtime hiển thị trong UI
- Tạo phòng instant (không cần đăng ký)
- Share link mời

### Ngoài scope MVP

- Ghi hình / recording
- Whiteboard, screen share
- Chat text
- Mobile app native
- Đăng nhập / tài khoản người dùng
- Billing / subscription
- Hỗ trợ > 3 ngôn ngữ đồng thời trong một phòng
