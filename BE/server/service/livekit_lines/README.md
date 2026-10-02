# livekit_lines — tách line âm thanh riêng cho từng người nói

## Vấn đề

Khi nhiều người nói, AI dịch bị "loạn": cùng một câu bị transcript ra ở hai
speaker, relay focus bị cướp, overlap bị báo sai.

Nguyên nhân **không nằm ở LiveKit server**. LiveKit là SFU và **không trộn
audio**: mỗi participant publish một track Opus riêng, và server forward
nguyên track đó. `LiveKitRuntime` vốn đã subscribe từng track và tạo một
`rtc.AudioStream` riêng cho mỗi `participant.identity`. Fork LiveKit server
cũng không tách thêm được gì.

Phần bị trộn nằm **trước trình duyệt, ở tầng âm học**. Khi nhiều người ngồi
chung phòng hoặc dùng loa ngoài, mic của A thu luôn giọng B. AEC của trình
duyệt chỉ khử được âm thanh do chính trang đó phát ra, không khử được giọng
người thật ngồi cạnh. Track của A vì vậy chứa giọng B, và server VAD của
session OpenAI cho A bắt được, rồi transcript lại như thể A nói.

## Cách giải quyết

```text
LiveKit track (per participant)
  -> rtc.AudioStream (PCM 24 kHz mono, 20 ms)
  -> SpeakerLine                 # 1 line / mic track, sống theo subscription
       level + VAD + band spectrum (16 band, 150 Hz-4 kHz)
       giữ lookahead 120 ms
       CrosstalkArbiter.decide()  # so với các line khác trong room
       bleed -> thay bằng silence (giữ nguyên timeline, có fade 20 ms)
  -> SpeakerLineStream           # drop-in thay rtc.AudioStream
  -> LiveKitAudioInput -> OpenAI Realtime session của speaker đó
```

Line X bị xem là bleed của line Y khi, ở một độ trễ nhỏ (±120 ms):

1. **Dấu vân tay phổ trùng khớp**: phổ 16 band của X bám theo phổ của Y qua
   cửa sổ 600 ms (correlation ≥ 0.75). Trừ trung bình theo band trước khi tính
   correlation, nên EQ cố định của phòng/mic và chênh lệch mức âm tổng thể đều
   bị triệt tiêu. Bleed là chính sóng âm của Y nên mang cùng cao độ và formant;
   hai người khác nhau thì có phổ khác nhau.
2. **Containment**: X chỉ có năng lượng khi Y đang nói (cho phép đuôi vang
   phòng 160 ms). Người nói độc lập có khoảng ngừng riêng nên rớt điều kiện này.
3. **Chênh mức**: X nhỏ hơn Y ít nhất 4 dB (median).

**Latch**: khi đã isolate, line được giữ tắt suốt cả câu của Y, với ngưỡng
correlation lỏng hơn (0.55), để không bị cắt lốm đốm (VAD sẽ bắt được những
mẩu rời rạc đó và transcript ra rác). Line được **mở ngay** khi mức âm vượt
mức bleed dự kiến (mức Y − suy hao đo được) ≥ 6 dB, tức người đó bắt đầu tự
nói. Ngược lại, line mở lại sau 80 ms liên tục không còn là bleed.

Line nguồn (to hơn) không bao giờ bị tắt bởi line nhỏ hơn.

## Kết quả đo (dữ liệu tổng hợp: giọng có formant + phòng vang RT60 0.4 s + EQ + trễ mạng 0–90 ms)

| Kịch bản | Kết quả |
| --- | --- |
| Bleed −10/−16/−24 dB, trễ 0/40/90 ms | tắt 99.9% frame bleed |
| Line nguồn | 0% bị tắt |
| Hai người nói độc lập cùng lúc | 0% bị tắt |
| B nói thật (−26 dB) đè lên bleed của A | 0% bị tắt |
| B nói nhỏ ngang mức bleed (khó về vật lý) | 4.4% bị tắt |

CPU: 1 người nói + 9 mic thu bleed ≈ 8% một core; 10 người cùng nói ≈ 10%.

## Cấu hình

| Env | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `LIVEKIT_LINE_ISOLATION_ENABLED` | `true` | Tắt thì quay về `rtc.AudioStream` thô như trước |
| `LIVEKIT_LINE_LOOKAHEAD_MS` | `120` | Độ trễ thêm vào để nhìn trước line khác |
| `LIVEKIT_LINE_CROSSTALK_CORRELATION` | `0.75` | Ngưỡng vào isolate; tăng nếu thấy tắt nhầm |
| `LIVEKIT_LINE_CROSSTALK_DOMINANCE_DB` | `4.0` | Chênh mức tối thiểu giữa nguồn và bleed |

Các knob khác nằm trong `LineIsolationConfig` (`config.py`).

## Log để kiểm tra trên môi trường thật

- `Speaker line isolated room=… line=… bleed_of=… corr=… gap_db=…`
- `Speaker line reopened on own voice …`
- `Speaker line stats … isolated_ms_recent=…` (mỗi 15 s, chỉ khi có isolate)
- `Speaker line closed … stats={…}`

## Giới hạn đã biết

- Số liệu ở trên đo trên audio tổng hợp, chưa đo trên audio phòng họp thật.
  Cần theo dõi log ở trên khi chạy thật rồi chỉnh ngưỡng.
- Người nói rất nhỏ, ngay dưới một người nói to cùng phòng, có thể bị tắt một
  phần (~4%).
- Relay audio của BRSE AI phát ra loa không phải là một line, nên echo của nó
  vẫn dựa vào AEC của trình duyệt.
- Arbiter chỉ tắt bleed. Chính sách relay focus một-người-một-lúc trong
  `room_manager` vẫn giữ nguyên.
