# LiveKit Setup

Tài liệu này mô tả setup LiveKit cho MVP local development và contract kết nối cho Gateway, Interpreter, và FE.

Scope:

- Chạy LiveKit local bằng Docker Compose ở root project
- Config `livekit.yaml` tối thiểu
- Port mapping cần mở
- Cách Gateway cấp token
- Cách Interpreter subscribe/publish raw audio
- Cách FE connect và nhận translation tracks

## SDK Choice

Repo `livekit-server-sdk-python` cũ đã archived. Với implementation hiện tại nên dùng:

- `livekit` cho RTC participant SDK
- `livekit-api` cho access token generation và room service API

Hai package này là maintained successor phù hợp với yêu cầu backend participant của Interpreter.

## Environment Variables

```text
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
LIVEKIT_WS_URL_PUBLIC=ws://localhost:7880
LIVEKIT_WS_URL_INTERNAL=ws://livekit:7880
```

`LIVEKIT_WS_URL_PUBLIC` là URL browser dùng để connect.

`LIVEKIT_WS_URL_INTERNAL` là URL container nội bộ cho Gateway/Interpreter.

Production `meetqapp.com` deploy uses:

```text
LIVEKIT_WS_URL_PUBLIC=wss://rtc.meetqapp.com
LIVEKIT_WS_URL_INTERNAL=ws://livekit:7880
```

Local development uses `ops/livekit/livekit.yaml`; production uses `ops/livekit/livekit.prod.yaml`.

## Root `docker-compose.yml` Snippet

Snippet dưới đây chỉ tập trung vào phần LiveKit + Redis + hai backend services. Nó phải nằm trong file Compose ở root project, không nằm trong `BE/`.

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"

  livekit:
    image: livekit/livekit-server:latest
    restart: unless-stopped
    command: --config /etc/livekit/livekit.yaml
    volumes:
      - ./ops/livekit/livekit.yaml:/etc/livekit/livekit.yaml:ro
    ports:
      - "7880:7880/tcp"
      - "7881:7881/tcp"
      - "50000-50100:50000-50100/udp"
    depends_on:
      - redis

  gateway:
    build:
      context: ./BE
    command: uvicorn server.service.gateway.main:app --host 0.0.0.0 --port 8000
    environment:
      REDIS_URL: redis://redis:6379/0
      LIVEKIT_API_KEY: devkey
      LIVEKIT_API_SECRET: secret
      LIVEKIT_WS_URL_PUBLIC: ws://localhost:7880
      LIVEKIT_WS_URL_INTERNAL: ws://livekit:7880
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - livekit

  interpreter:
    build:
      context: ./BE
    command: python -m server.service.brain_runtime.main
    environment:
      REDIS_URL: redis://redis:6379/0
      LIVEKIT_API_KEY: devkey
      LIVEKIT_API_SECRET: secret
      LIVEKIT_WS_URL_INTERNAL: ws://livekit:7880
    depends_on:
      - redis
      - livekit
```

## `livekit.yaml` Minimal Config

File đề xuất: `ops/livekit/livekit.yaml`

```yaml
port: 7880

rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 50100
  use_external_ip: false

redis:
  address: redis:6379

keys:
  devkey: secret
```

### Why These Values

1. `port: 7880`
   Port signaling và room API mặc định của LiveKit.

2. `rtc.tcp_port: 7881`
   Fallback ICE/TCP khi UDP không usable.

3. `rtc.port_range_start/end`
   Giới hạn local dev UDP range nhỏ gọn, dễ map trong Docker.

4. `use_external_ip: false`
   Local dev không cần STUN-discovered public IP. Nếu deploy cloud/public host thì đổi `true`.

5. `redis.address: redis:6379`
   LiveKit dùng Redis nếu muốn distributed coordination; local single-node vẫn an toàn khi đã có Redis trong stack.

6. `keys`
   Key-pair dùng để Gateway và Interpreter generate JWT access token.

## Ports To Open

### Required For Local Dev

| Port | Proto | Purpose |
| --- | --- | --- |
| `7880` | TCP | LiveKit signaling, room API, WebSocket endpoint |
| `7881` | TCP | ICE/TCP fallback |
| `50000-50100` | UDP | WebRTC media transport |

### Optional

| Port | Proto | Purpose |
| --- | --- | --- |
| `5349` | TCP | TURN/TLS nếu sau này bật TURN |
| `3478` | UDP/TCP | TURN/STUN nếu tự host TURN riêng |

MVP local dev không bật TURN, nên `5349` và `3478` chưa cần expose.

## Gateway Authentication To LiveKit

Gateway không join room. Nó chỉ generate LiveKit JWT cho browser participant.

### Token Generation Contract

Gateway phải set các field sau:

```json
{
  "identity": "pt_01hs8x4e3m",
  "name": "Huy",
  "grants": {
    "roomJoin": true,
    "room": "rm_8f3k2v1m",
    "canPublish": true,
    "canSubscribe": true,
    "canPublishData": false
  },
  "metadata": {
    "participant_id": "pt_01hs8x4e3m",
    "language": "vi",
    "kind": "human"
  }
}
```

### Python Example

```python
from livekit import api

token = (
    api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    .with_identity("pt_01hs8x4e3m")
    .with_name("Huy")
    .with_grants(
        api.VideoGrants(
            room_join=True,
            room="rm_8f3k2v1m",
            can_publish=True,
            can_subscribe=True,
            can_publish_data=False,
        )
    )
    .with_metadata('{"participant_id":"pt_01hs8x4e3m","language":"vi","kind":"human"}')
    .to_jwt()
)
```

## Interpreter Authentication To LiveKit

Interpreter join room như một participant riêng.

### Token Contract

Interpreter token nên có:

```json
{
  "identity": "interp::rm_8f3k2v1m",
  "name": "Interpreter",
  "grants": {
    "roomJoin": true,
    "room": "rm_8f3k2v1m",
    "canPublish": true,
    "canSubscribe": true,
    "canPublishData": false
  },
  "metadata": {
    "kind": "interpreter",
    "room_id": "rm_8f3k2v1m"
  }
}
```

### Python Example

```python
from livekit import api

token = (
    api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    .with_identity("interp::rm_8f3k2v1m")
    .with_name("Interpreter")
    .with_grants(
        api.VideoGrants(
            room_join=True,
            room="rm_8f3k2v1m",
            can_publish=True,
            can_subscribe=True,
            can_publish_data=False,
        )
    )
    .with_metadata('{"kind":"interpreter","room_id":"rm_8f3k2v1m"}')
    .to_jwt()
)
```

## Interpreter Subscribe Flow

Interpreter connect bằng `LIVEKIT_WS_URL_INTERNAL`.

### Connection Example

```python
from livekit import rtc

room = rtc.Room()
await room.connect(
    LIVEKIT_WS_URL_INTERNAL,
    interpreter_token,
    rtc.RoomOptions(auto_subscribe=False),
)
```

### Subscribe Only Microphone Audio

Pseudo flow:

```python
@room.on("track_published")
def on_track_published(publication, participant):
    if participant.identity.startswith("interp::"):
        return
    if publication.kind == rtc.TrackKind.KIND_AUDIO:
        publication.set_subscribed(True)
```

Khi đã subscribed, convert raw frames:

```python
audio_stream = rtc.AudioStream.from_track(
    track=remote_audio_track,
    sample_rate=16000,
    num_channels=1,
    frame_size_ms=20,
)
```

Interpreter dùng `AudioStream` này để nuôi `LiveKitAudioInput`.

## Interpreter Publish Flow

Translated audio từ OpenAI là PCM16 24kHz mono.

### AudioSource Setup

```python
from livekit import rtc

audio_source = rtc.AudioSource(24000, 1, queue_size_ms=1500)
track = rtc.LocalAudioTrack.create_audio_track(
    "interp::pt_01hs8x4e3m::pt_01hs8y3n1z::vi::ja",
    audio_source,
)
publication = await room.local_participant.publish_track(track)
```

### Frame Push Contract

Interpreter phải rechunk audio delta về frame 20ms:

- sample rate `24000`
- samples per channel `480`
- bytes per frame `960`

Ví dụ `AudioFrame`:

```python
frame = rtc.AudioFrame(
    data=pcm_chunk_960_bytes,
    sample_rate=24000,
    num_channels=1,
    samples_per_channel=480,
)
await audio_source.capture_frame(frame)
```

### Queue Clearing

Khi barge-in hoặc listener leave:

```python
audio_source.clear_queue()
```

Điều này cần thiết để audio cũ không còn phát tiếp sau khi speaker bắt đầu câu mới.

## FE Authentication And Connect

FE luôn dùng object `livekit` trả về từ `POST /api/rooms/{room_id}/join`.

### Browser Connection Example

```ts
import { Room } from 'livekit-client';

const room = new Room();
await room.connect(join.livekit.url, join.livekit.token, {
  autoSubscribe: true,
});
```

### Publish Local Media

FE sau khi connect phải publish mic/camera của user như participant thông thường.

### Track Detection Rules On FE

FE có thể nhận:

1. human camera tracks
2. human microphone tracks
3. interpreter audio tracks

Interpreter track phải được detect bằng:

1. remote participant identity prefix `interp::`
2. track name prefix `interp::`

### Track Name Parsing

```text
interp::pt_01hs8x4e3m::pt_01hs8y3n1z::vi::ja
```

Mapping:

| Segment | Meaning |
| --- | --- |
| `interp` | fixed prefix |
| `pt_01hs8x4e3m` | speaker_id |
| `pt_01hs8y3n1z` | listener_id |
| `vi` | source language |
| `ja` | target language |

FE chỉ play track khi `listener_id == current participant_id`.

## Local Dev Checklist

1. `docker compose up livekit redis`
2. Verify `http://localhost:7880` reachable
3. Verify Gateway generate được LiveKit token bằng key `devkey/secret`
4. Join room từ browser
5. Check browser WebRTC connection established
6. Check Interpreter participant `interp::{room_id}` đã join LiveKit room
7. Check translated track publish với tên đúng format `interp::{speaker}::{listener}::{src}::{tgt}`

## Troubleshooting Notes

### Browser Connects To Gateway But Not LiveKit

Nguyên nhân thường gặp:

1. `LIVEKIT_WS_URL_PUBLIC` đang trỏ `ws://livekit:7880` thay vì URL browser truy cập được
2. UDP range chưa map ra host
3. `rtc.use_external_ip` sai với môi trường chạy thực tế

### Interpreter Connects But Browser Cannot Hear Translation

Check theo thứ tự:

1. Interpreter đã publish translation track chưa
2. track name có đúng format không
3. FE có filter nhầm interpreter track không
4. track subscription permissions có cấp cho đúng listener không
5. `audio_source.clear_queue()` có bị gọi nhầm liên tục không

### Localhost Works, LAN Device Fails

Nếu browser chạy từ máy khác trong cùng LAN:

1. đổi `LIVEKIT_WS_URL_PUBLIC` thành host LAN IP
2. cân nhắc `use_external_ip: false` và set `node_ip` thủ công nếu cần
3. mở `7880`, `7881`, `50000-50100/udp` trên firewall

## Production Notes Deferred Out Of MVP

Những phần này chưa bật trong MVP nhưng cần nhớ khi đi production:

1. TLS termination trước cổng `7880`
2. TURN/TLS trên `5349`
3. `use_external_ip: true` hoặc `node_ip` explicit
4. LiveKit Cloud thay self-hosted nếu muốn giảm ops burden
