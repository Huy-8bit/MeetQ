# brseAI - Google Meet Interpreter Bot (VI/EN/JA)

Realtime speech translation for Google Meet, powered by the OpenAI Realtime API.
Joins a meeting as a browser participant, captures meeting audio, and streams translated text (and optionally TTS audio) to the terminal.

## Quickstart

### 1) Prerequisites

- Python 3.10+
- PortAudio (`sounddevice` backend)
- `playwright` + Chromium
- Virtual audio device (BlackHole/Loopback) if not using ScreenCaptureKit path
- macOS 13+ + Screen Recording permission if using `--sck`

macOS:

```bash
brew install python@3.12 portaudio
```

### 2) Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
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

### 4) First-time sign-in (once)

```bash
python app.py --setup-profile
```

This opens a Chromium window. Sign in to your Google account, then close the window. Your session is saved to `~/.brseai_profile`.

### 5) Run

```bash
python app.py --meeting-url "https://meet.google.com/xxx-xxxx-xxx"
```

The browser opens. Click **Join** (or **Ask to join**) yourself — the interpreter pipeline starts automatically once you're in the call. Translation text prints to the terminal.

#### With audio speak-back (TTS into meeting via virtual mic)

```bash
python app.py \
  --meeting-url "https://meet.google.com/xxx-xxxx-xxx" \
  --meet-mic-device <OUTPUT_INDEX>
```

#### With loopback audio capture (instead of default SCK)

```bash
python app.py \
  --meeting-url "https://meet.google.com/xxx-xxxx-xxx" \
  --meet-speaker-device <INPUT_INDEX>
```

#### List audio devices

```bash
python app.py --list-audio-devices
python app.py --list-input-devices
python app.py --list-speakers
```

#### Auto-click join (instead of manual-join default)

```bash
python app.py \
  --meeting-url "https://meet.google.com/xxx-xxxx-xxx" \
  --no-manual-join
```

### Migration from `--mode meet-bot`

Old usage (still works):
```bash
python app.py --mode meet-bot --meeting-url https://meet.google.com/xxx ...
```

New usage (preferred):
```bash
python app.py --meeting-url https://meet.google.com/xxx ...
```

`--mode realtime` and `--mode fallback` are no longer supported in `app.py`.
Use `python -m src.realtime.main` or `python -m src.fallback.pipeline` directly.

### Advanced: `src.meet.main` entrypoint

For programmatic use or advanced flags:

```bash
python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device <INPUT_INDEX> \
  --src auto --tgt auto --meeting-mode locked
```

Optional speak-back:

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
| `--manual-join` | off | [meet-bot] skip auto-click; user joins by hand |
| `--manual-join-timeout` | `300` | [meet-bot] seconds to wait for manual join |

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
| `--manual-join` | off | skip auto-click; user joins by hand, interpreter starts on in-call detection |
| `--manual-join-timeout` | `300` | seconds to wait for manual join before giving up |
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

### Join button not found / auto-join blocked

If the bot fails with `Could not find or click the Join button`, use manual-join
mode to bypass auto-click and join by hand:

```bash
python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --sck \
  --manual-join \
  --manual-join-timeout 120
```

The browser will open and stay open. Join the meeting yourself (click the button,
wait for host admission if needed). Once the bot detects an in-call state the
interpreter pipeline starts automatically. Default timeout is 300 s.

### Listening but no translation output / speaker OFF

If the bot logs `[Listening... speaker OFF]` and you see `[You] ...` lines but no
translated speech or text:

**Symptom:** Startup prints:
```
[RealtimeClient] Audio output: DISABLED (speaker=off).
Translation text will print to stdout only.
Use --speaker / --meet-mic-device to enable TTS output.
```

**Cause:** `enable_speaker` is False. This happens automatically when:
- Running meet-bot without `--meet-mic-device` (no virtual output device configured).
- Running realtime with `--no-speaker`.

Translation text IS printed to stdout in this mode — check the terminal for `[Interp]` lines.

**Fix — text-only mode (confirm translation is working):**
Look for `[Interp]` lines on stdout after speaking.

**Fix — enable TTS audio output for meet-bot:**
```bash
python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device <INPUT_INDEX> \
  --meet-mic-device <OUTPUT_INDEX>
```
`--meet-mic-device` is the virtual output device (e.g. BlackHole) that Chrome uses as its microphone input.

**Fix — enable speaker for realtime mic mode:**
```bash
python app.py --mode realtime --speaker
```

### Language routing not locking / "waiting for first confident detection"

If the startup shows:
```
[MeetingMode] locked | waiting for first confident detection to lock routing
```
and this message never changes after speech:

- The language-detection heuristic requires at least 2 marker characters (Japanese/Vietnamese) or 5 ASCII words (English). Very short utterances may return uncertain.
- After 3 consecutive uncertain transcripts the system prints a reminder that the model is still translating using auto-detect instructions — translation IS happening.
- To skip detection and lock immediately, pass explicit `--src` and `--tgt`:

```bash
python -m src.meet.main ... --src vi --tgt en --meeting-mode locked
```

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
