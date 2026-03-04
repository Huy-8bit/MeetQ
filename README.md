# brseAI - Realtime Interpreter (VI/EN/JA)

Realtime speech translation on top of OpenAI Realtime, plus a fallback record/transcribe/translate path.

Implemented runtimes:
- `realtime`: stream audio chunks over WebSocket, print translated text, optional audio playback.
- `fallback`: record fixed-length clip, transcribe, then translate.
- `meet-bot`: Playwright Google Meet participant + meeting audio capture + realtime interpreter.

## Quickstart

### 1) Prerequisites

- Python 3.10+
- PortAudio (`sounddevice` backend)
- Optional for meet-bot:
  - `playwright` + Chromium
  - Virtual audio device (BlackHole/Loopback) if not using ScreenCaptureKit path
  - macOS 13+ + Screen Recording permission if using `--sck`

macOS example:

```bash
brew install python@3.12 portaudio
```

### 2) Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Install Chromium for meet-bot:

```bash
playwright install chromium
```

### 3) Configure API key

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=...
```

or:

```bash
export OPENAI_API_KEY="sk-..."
```

### 4) List audio devices

```bash
python app.py --list-input-devices
python app.py --list-speakers
python app.py --list-audio-devices
```

`--list-mics` is a legacy alias of `--list-input-devices`.

### 5) Run

#### Realtime mic interpreter

```bash
python app.py --mode realtime
```

Verbose logging + streamed event details:

```bash
python app.py --mode realtime --debug
```

#### Realtime device input (loopback / virtual device)

```bash
python app.py --mode realtime \
  --input device \
  --input-device <INPUT_INDEX> \
  --input-rate 48000 \
  --no-speaker
```

Note: speaker defaults to `OFF` when `--input device` is used (echo prevention).

#### Fallback mode

```bash
python app.py --mode fallback --seconds 8
```

With explicit language routing:

```bash
python app.py --mode fallback --seconds 8 --src ja --tgt en --meeting-mode locked
```

#### Meet-bot / connect_to_meet mode

Use the meet module entrypoint:

```bash
python -m src.meet.main --setup-profile --profile-dir ~/.brseai_profile
```

Then run bot (loopback device path):

```bash
python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device <INPUT_INDEX> \
  --src auto --tgt auto --meeting-mode locked
```

Optional bot speak-back (virtual mic output device):

```bash
python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device <INPUT_INDEX> \
  --meet-mic-device <OUTPUT_INDEX>
```

## Language Routing

Supported languages: `auto`, `vi`, `en`, `ja`.

Key flags:
- `--src`: source language (`auto` by default)
- `--tgt`: target language (`auto` by default)
- `--pairs`: allowed pair filter (example: `"vi<->en,ja<->en"`)
- `--meeting-mode locked|auto`:
  - `locked` (default): keep one routing after lock
  - `auto`: re-detect during session

Default auto table in code:
- `vi -> en`
- `en -> vi`
- `ja -> en`

## CLI Flags (Current)

### `app.py` (realtime + fallback + shared helpers)

| Flag | Default | Notes |
|---|---|---|
| `--mode` | `realtime` | `realtime`, `fallback`, `meet-bot` |
| `--input` | `mic` | `mic` or `device` (realtime) |
| `--input-device` | `None` | required with `--input device` |
| `--input-rate` | `16000` | realtime input sample rate |
| `--list-input-devices` | off | list input devices and exit |
| `--mic` | `None` | legacy alias for input device |
| `--list-mics` | off | legacy alias for `--list-input-devices` |
| `--speaker/--no-speaker` | dynamic | realtime default: ON for mic, OFF for device input |
| `--speaker-device` | `None` | output device index |
| `--list-speakers` | off | list output devices and exit |
| `--seconds` | `5.0` | fallback clip duration |
| `--sample-rate` | `None` | legacy; fallback uses `sample-rate` or `input-rate` |
| `--model` | `None` | falls back to `gpt-4o-realtime-preview-2024-12-17` |
| `--transcribe-model` | `whisper-1` | fallback only |
| `--chat-model` | `gpt-4o-mini` | fallback only |
| `--src` | `auto` | language source |
| `--tgt` | `auto` | language target |
| `--pairs` | empty | empty means all pairs allowed |
| `--meeting-mode` | `locked` | `locked` or `auto` |
| `--show-input` | off | explicit input transcript flag |
| `--debug` | off | verbose runtime logs |
| `--list-audio-devices` | off | lists full I/O table via `src.meet.audio` |
| `--setup-profile` | off | opens profile sign-in flow and exits |

### `src.meet.main` (recommended meet-bot entrypoint)

| Flag | Default | Notes |
|---|---|---|
| `--meeting-url` | required at runtime | Meet URL |
| `--profile-dir` | `~/.brseai_profile` | persistent Chromium profile |
| `--setup-profile` | off | sign in and persist session |
| `--headless/--no-headless` | `--no-headless` | Meet is often less reliable in headless mode |
| `--display-name` | `Interpreter Bot` | pre-join name |
| `--join-timeout-seconds` | `90` | waiting-room timeout |
| `--leave-after-minutes` | off | auto-leave timer |
| `--sck` | off | macOS ScreenCaptureKit capture path |
| `--sck-app` | `None` | with `--sck`, capture one app bundle ID |
| `--meet-speaker-device` | `None` | loopback input device (required unless `--sck`) |
| `--meet-mic-device` | `None` | optional output device for bot TTS |
| `--meet-sample-rate` | auto | effective default `16000` (`--sck`) or `48000` (loopback) |
| `--list-audio-devices` | off | print all devices and exit |
| `--src` | `auto` | language source |
| `--tgt` | `auto` | language target |
| `--pairs` | empty | pair filter |
| `--meeting-mode` | `locked` | routing lock policy |
| `--show-input` | off | show transcript lines |
| `--debug` | off | verbose bot/interpreter logs |

## Troubleshooting

### Microphone permission denied

- macOS: `System Settings -> Privacy & Security -> Microphone` and enable Terminal/iTerm.
- Verify detection:

```bash
python app.py --list-input-devices
```

### Input device opens but no transcript appears

- Wrong device index or silent source.
- For loopback capture, confirm Chrome/Meet audio is routed to that device.
- Run realtime with `--debug` to inspect VAD events.

### Sample-rate mismatch / device open errors

- Match capture rate to device default rate from `--list-input-devices`.
- Common loopback rates: `44100` or `48000`.
- Example:

```bash
python app.py --mode realtime --input device --input-device <INDEX> --input-rate 48000 --no-speaker
```

### Virtual audio setup notes (high-level)

- Loopback path requires two routes:
  - Meet speaker output -> virtual input device captured by bot/interpreter.
  - Bot TTS output -> virtual output device selected as Meet microphone input.
- Keep capture and playback on separate routes to avoid feedback.

### Playwright / Chromium issues

- Install browser runtime:

```bash
playwright install chromium
```

- Use persistent profile (`--profile-dir`) and run setup once with `--setup-profile`.
- Prefer non-headless mode when meeting join UI is blocked.

### Waiting room / admit behavior

- Bot can wait up to `--join-timeout-seconds` (default `90`).
- Host must admit the bot if waiting-room policy requires approval.
- If timed out, rerun after host-side policy adjustment or manual admit.

### Known implementation caveats

- `python app.py --mode meet-bot` currently does not expose the full meet parser surface (`--sck`, `--sck-app`); use `python -m src.meet.main` for meet operations.
- `--sck` path exists in code but is less battle-tested than loopback-device capture.
- Fallback mode always writes WAV clips to `recordings/`.

## Docs

- [Architecture](docs/architecture.md)
- [Realtime Protocol](docs/realtime_protocol.md)
- [Security](docs/security.md)
- [Phase 2 Meet Status](docs/phase2_google_meet.md)
- [State](docs/STATE.md)
- [Tasks](docs/TASKS.md)
- [Meet Next Steps](docs/next_steps_google_meet.md)
