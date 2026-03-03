# brseAI — Real-Time Bilingual Interpreter (Vietnamese ↔ English)

Stream microphone audio to the OpenAI Realtime API and get live translated text printed to your terminal. Supports both a low-latency **realtime** mode (WebSocket streaming) and a simpler **fallback** mode (record → transcribe → translate).

---

## Quickstart

### 1. Prerequisites

| Dependency | Install |
|---|---|
| Python 3.10+ | `brew install python@3.12` (macOS) |
| PortAudio | `brew install portaudio` (macOS) or `sudo apt-get install portaudio19-dev` |
| ffmpeg (optional) | `brew install ffmpeg` |

### 2. Clone and set up environment

```bash
cd brseAI

# Create virtual environment with Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure API key

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

Or export directly:

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

### 4. Run

**List microphones:**
```bash
python app.py --list-mics
```

**List speakers:**
```bash
python app.py --list-speakers
```

**Realtime interpreter — voice + text (default):**
```bash
python app.py --mode realtime
```

**Realtime with specific mic and speaker:**
```bash
python app.py --mode realtime --mic 3 --speaker-device 1
```

**Realtime — text only (disable audio playback):**
```bash
python app.py --mode realtime --no-speaker
```

**Realtime — verbose debug mode (shows all events + input transcripts):**
```bash
python app.py --mode realtime --debug
```

**Fixed meeting language — Japanese → English, locked for whole session:**
```bash
python app.py --mode realtime --meeting-mode locked --src ja --tgt en
```

**Auto-detect mode — language can switch mid-session:**
```bash
python app.py --mode realtime --meeting-mode auto
```

**Fallback mode — record 8 seconds then translate:**
```bash
python app.py --mode fallback --seconds 8
```

---

## All CLI Flags

```
python app.py --help
```

| Flag | Default | Description |
|---|---|---|
| `--mode` | `realtime` | `realtime` or `fallback` |
| `--mic INDEX` | system default | Mic device index from `--list-mics` |
| `--list-mics` | — | Print input devices and exit |
| `--speaker` / `--no-speaker` | on | Enable/disable audio playback |
| `--speaker-device INDEX` | system default | Speaker device index from `--list-speakers` |
| `--list-speakers` | — | Print output devices and exit |
| `--debug` | off | Verbose event logging + show input transcripts |
| `--seconds N` | `5` | Fallback only: recording duration |
| `--sample-rate HZ` | `16000` | Audio sample rate |
| `--model` | `gpt-4o-realtime-preview-2024-12-17` | Realtime model ID |
| `--transcribe-model` | `whisper-1` | Fallback transcription model |
| `--chat-model` | `gpt-4o-mini` | Fallback translation model |
| `--src {auto,vi,en,ja}` | `auto` | Source language |
| `--tgt {auto,vi,en,ja}` | `auto` | Target language |
| `--meeting-mode {locked,auto}` | `locked` | `locked`: fix routing after first detection; `auto`: re-detect mid-session |
| `--pairs PAIRS` | all | Restrict routing, e.g. `"vi<->en,ja<->en"` |
| `--show-input` | off | Always print `[You]` transcript |

---

## How It Works

### Realtime Mode
```
Mic → PCM16 chunks (20ms) → WebSocket → OpenAI Realtime API
                                              ↓ server VAD
                                   response.text.delta   → [Interp] terminal
                                   response.audio.delta  → SpeakerPlayer → speaker
```
- Server-side VAD detects speech start/stop automatically.
- Text translation streams to terminal; audio plays through speaker simultaneously.
- **Barge-in**: if you speak while the interpreter is talking, playback stops immediately and the new turn begins.
- `[You] <transcript>` shown after each of your turns; `[Interp] <translation>` streams in real time.
- Reconnects automatically on WebSocket drops (up to 5 attempts).

### Fallback Mode
```
Mic → record N seconds → WAV file → Whisper transcription → GPT translation → terminal
```
- Reliable alternative when Realtime API is unavailable.
- Recordings saved to `recordings/` with timestamps.

### Translation Behavior
The model is instructed (via system prompt / session instructions):
- If user speaks **Vietnamese** → output **English** only
- If user speaks **English** → output **Vietnamese** only
- No labels, no commentary — translation text only

---

## Repo Structure

```
brseAI/
├── app.py                     Main CLI entrypoint
├── requirements.txt
├── .env.example
├── docs/
│   ├── TASKS.md               Task breakdown
│   ├── STATE.md               Progress log (resume point)
│   ├── architecture.md        Mermaid diagrams
│   ├── realtime_protocol.md   WebSocket event reference
│   ├── security.md            Security notes
│   ├── phase2_google_meet.md  Phase 2 design + compliance spec
│   └── next_steps_google_meet.md
├── src/
│   ├── common/
│   │   ├── audio.py           AudioInput ABC, MicInput, DeviceLoopbackInput, SpeakerPlayer
│   │   ├── lang.py            Language detection + routing
│   │   └── logging_utils.py   Timestamped logger
│   ├── realtime/
│   │   ├── client.py          RealtimeClient (WebSocket)
│   │   └── main.py            Realtime entrypoint
│   ├── fallback/
│   │   ├── pipeline.py        Record → transcribe → translate
│   │   └── main.py            Fallback entrypoint
│   └── meet/
│       ├── bot.py             MeetBot Playwright joiner
│       ├── audio.py           MeetAudioListenerInput, MeetAudioMicOutput
│       ├── selectors.py       Resilient Meet DOM selector map
│       └── main.py            Meet-bot entrypoint
├── recordings/                WAV clips (fallback mode output)
└── logs/                      Log files
```

---

## Google Meet Bot Mode

> **Internal use only.** Requires participant consent and legal review before
> any production or third-party meeting deployment.
> See `docs/phase2_google_meet.md` for compliance constraints.

The bot joins a Google Meet as a visible participant, listens to meeting audio
through a virtual loopback device, translates speech in real time, and speaks
the translation back into the meeting through a second virtual device configured
as the bot's microphone input.

### Prerequisites

| Requirement | macOS install |
|---|---|
| Python 3.10+ venv | (already set up) |
| PortAudio | `brew install portaudio` |
| Playwright + Chromium | `pip install playwright && playwright install chromium` |
| Virtual audio device | [BlackHole 2ch](https://existential.audio/blackhole/) (free) or [Loopback](https://rogueamoeba.com/loopback/) (paid) |

### Virtual Audio Device Setup (macOS)

You need **two virtual audio devices**:

1. **Meet → Bot capture device** (e.g. BlackHole 2ch)
   - In Chrome: `⋮` → Settings → Sound → set **Output** to BlackHole 2ch
   - Meeting audio flows: Chrome speaker → BlackHole → bot's `--meet-speaker-device`

2. **Bot TTS → Meet mic device** (e.g. a second BlackHole or Loopback virtual device)
   - In Chrome: set **Input** (microphone) to this device
   - TTS audio flows: bot `--meet-mic-device` → virtual device → Chrome mic → participants

```bash
# Find device indexes
python app.py --list-audio-devices
```

### First-Time Google Sign-In

Run once to save your Google credentials in a persistent profile:

```bash
python app.py --mode meet-bot \
  --setup-profile \
  --profile-dir ~/.brseai_profile
```

A browser window opens. Sign in to Google, then close the browser.
The profile is saved to `~/.brseai_profile` and reused on all future runs.

### Run the Bot

```bash
python app.py --mode meet-bot \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device 4 \
  --meet-mic-device 5 \
  --src ja --tgt vi \
  --meeting-mode locked
```

**Japanese → English, auto-detect, no bot speech output (listen only):**
```bash
python app.py --mode meet-bot \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device 4 \
  --src ja --tgt en
```

**Auto-leave after 2 hours:**
```bash
python app.py --mode meet-bot \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device 4 \
  --meet-mic-device 5 \
  --leave-after-minutes 120
```

### Meet-Bot CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--meeting-url URL` | required | Google Meet URL |
| `--profile-dir PATH` | `~/.brseai_profile` | Persistent Chromium profile directory |
| `--setup-profile` | off | First-time sign-in helper; opens browser, then exits |
| `--headless` / `--no-headless` | false | Run Chromium headless (not recommended; Meet may block) |
| `--display-name NAME` | `Interpreter Bot` | Bot's name shown in meeting |
| `--join-timeout-seconds N` | 90 | Seconds to wait for admission |
| `--leave-after-minutes N` | off | Auto-leave after N minutes |
| `--meet-speaker-device INDEX` | required | Loopback INPUT device to capture meeting audio |
| `--meet-mic-device INDEX` | off | Virtual OUTPUT device to send bot TTS into Meet mic |
| `--meet-sample-rate HZ` | 48000 | Capture sample rate (match device native rate) |
| `--list-audio-devices` | — | Print all I/O devices and exit |
| `--src` | `auto` | Source language (`auto`, `vi`, `en`, `ja`) |
| `--tgt` | `auto` | Target language |
| `--meeting-mode` | `locked` | `locked` / `auto` |
| `--debug` | off | Verbose Playwright + audio event logs |

### Troubleshooting: Meet Bot

**Bot never gets past waiting room:**
- Ask the meeting host to admit the bot, or make sure your Google account is
  allowed to join without approval (Google Workspace setting).
- Increase `--join-timeout-seconds`.

**No audio captured (bot produces no translations):**
- Confirm Chrome's audio OUTPUT is set to your loopback device.
- `python app.py --list-audio-devices` — verify `--meet-speaker-device` index.
- Check macOS `System Settings → Sound → Output` is not overriding Chrome's setting.

**Bot TTS not heard in meeting:**
- Confirm Chrome's microphone INPUT is set to your virtual mic device.
- Verify `--meet-mic-device` index is the OUTPUT side of the virtual device.
- Use `--debug` to see if `response.audio.delta` events are received.

**Meet blocks automated browser:**
- Use `--no-headless` (default). Fully headless Chromium is often blocked.
- Ensure `--profile-dir` points to a profile where you are already signed in.

**`playwright` not installed:**
```bash
pip install playwright
playwright install chromium
```

---

## Troubleshooting

### No microphone detected
- **macOS:** Grant Terminal mic access in `System Settings → Privacy & Security → Microphone`.
- **Linux:** Check `pactl list short sources` or `arecord -l`.
- Verify Python can see your devices:
  ```bash
  python app.py --list-mics
  ```

### `OSError: [Errno -9996] Invalid input device` or similar
- Wrong device index. Run `--list-mics` and pass the correct `--mic INDEX`.

### PortAudio not found / sounddevice import error
- Install PortAudio **before** `pip install -r requirements.txt`:
  ```bash
  brew install portaudio   # macOS
  # then recreate venv and reinstall
  ```

### WebSocket / auth errors
- Confirm `OPENAI_API_KEY` is set: `echo $OPENAI_API_KEY`
- Confirm the realtime model name is correct and your account has access.
- Check outbound `wss://` (port 443) is not blocked by a firewall.

### `response.text.delta` never appears
- The model may not have received audio. Confirm mic is active and not muted.
- Try `--sample-rate 24000` if your device's native rate is 24kHz.

### Fallback: empty transcript
- Speak closer to the mic and increase `--seconds`.
- Check recording is saved in `recordings/` and is non-empty.

---

## Additional Docs

- [Architecture](docs/architecture.md)
- [Realtime Protocol Events](docs/realtime_protocol.md)
- [Security Notes](docs/security.md)
- [Google Meet Next Steps](docs/next_steps_google_meet.md)
- [Task List](docs/TASKS.md)
- [Progress Log](docs/STATE.md)
