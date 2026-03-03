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
│   └── next_steps_google_meet.md
├── src/
│   ├── common/
│   │   ├── audio.py           MicCapture, record_clip, list_input_devices
│   │   └── logging_utils.py   Timestamped logger
│   ├── realtime/
│   │   ├── client.py          RealtimeClient (WebSocket)
│   │   └── main.py            Realtime entrypoint
│   └── fallback/
│       ├── pipeline.py        Record → transcribe → translate
│       └── main.py            Fallback entrypoint
├── recordings/                WAV clips (fallback mode output)
└── logs/                      Log files
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
