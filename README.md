# brseAI - Realtime Interpreter (VI/EN/JA)

Realtime speech translation powered by the OpenAI Realtime API.
Captures audio from microphone, audio device, or Discord voice channels and streams translated text (and optionally TTS audio).

## Modes

- **Realtime mode**: Local microphone or audio device input
- **Fallback mode**: Testing with audio clips
- **Discord mode**: Discord voice channel integration

## Quickstart

### 1) Prerequisites

- Python 3.10+
- PortAudio (`sounddevice` backend)
- For Discord mode: libopus (see Discord Bot Setup below)

macOS:

```bash
brew install python@3.12 portaudio opus
```

Linux:

```bash
apt install python3.12 portaudio19-dev libopus-dev
```

### 2) Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Configure API key

```bash
cp .env.example .env
# edit .env and set:
#   OPENAI_API_KEY=sk-...
#   DISCORD_BOT_TOKEN=... (for Discord mode)
```

or:

```bash
export OPENAI_API_KEY="sk-..."
export DISCORD_BOT_TOKEN="..."  # for Discord mode
```

### 4) Run

#### Realtime mode with microphone input

```bash
python app.py --mode realtime --input mic
```

#### Realtime mode with device input

```bash
python app.py --mode realtime --input device --input-device <INDEX>
```

#### Fallback mode (for testing)

```bash
python app.py --mode fallback --input-device <INDEX>
```

#### List audio devices

```bash
python app.py --list-input-devices
python app.py --list-speakers
```

#### With speaker output enabled

```bash
python app.py --mode realtime --input mic --speaker
```

#### Specify language pair

```bash
python app.py --mode realtime --src vi --tgt en
python app.py --mode realtime --src ja --tgt en
```

## Discord Bot Setup

The Discord bot joins voice channels and provides live translation to text channels.

### Prerequisites

1. **Create Discord Bot**:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section and create a bot
   - Enable "Message Content Intent" and "Server Members Intent"
   - Copy the bot token

2. **Invite Bot to Server**:
   - Go to "OAuth2" -> "URL Generator"
   - Select scopes: `bot`
   - Select bot permissions: `Connect`, `Speak`, `Send Messages`, `Read Messages`
   - Copy the generated URL and open it in your browser to invite the bot

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt, `fallback`, or `discord
   ```
   
   Ensure you have `libopus` installed (see Prerequisites section above).

### Running the Discord Bot

#### Basic usage

```bash
python app.py --mode discord --token YOUR_DISCORD_BOT_TOKEN
```

or set the token in environment:

```bash
export DISCORD_BOT_TOKEN="YOUR_TOKEN"
python app.py --mode discord
```

#### With auto-join and text output

```bash
python app.py --mode discord \
  --voice-channel-id 123456789 \
  --text-channel-id 987654321 \
  --src auto --tgt en
```

#### Direct module invocation

```bash
python -m src.discord.main \
  --token YOUR_TOKEN \
  --src vi --tgt en \
  --debug
```

### Discord Bot Commands

Once the bot is running, use these commands in Discord:

- `!join` - Bot joins your current voice channel and starts translation
- `!leave` - Bot leaves voice channel and stops translation
- `!status` - Display current bot status

### Discord Bot Features

- ✅ Join voice channels and listen to audio
- ✅ Real-time translation from Vietnamese, English, and Japanese
- ✅ Translation output to terminal
- ✅ Translation output to Discord text channel (optional)
- ✅ Auto-join voice channel on startup (optional)
- ⏳ TTS speak-back to voice channel (coming in future version)

### Discord Bot Flags

| Flag | Description |
|---|---|
| `--token` | Discord bot token (or use env DISCORD_BOT_TOKEN) |
| `--voice-channel-id` | Auto-join this voice channel on startup (optional) |
| `--text-channel-id` | Send translation output to this text channel (optional) |
| `--src` | Source language: auto (default), vi, en, ja |
| `--tgt` | Target language: auto (default), vi, en, ja |
| `--pairs` | Allowed pairs, e.g. "vi<->en,ja<->en" |
| `--meeting-mode` | locked (default) or auto |
| `--debug` | Enable debug logging |

### Discord Bot Architecture

The Discord bot reuses the existing realtime translation pipeline:

```
Discord Voice Channel
    ↓ (48kHz stereo PCM)
DiscordAudioInput (audio.py)
    ↓ (convert to 16kHz mono, 20ms chunks)
RealtimeClient (existing translation engine)
    ↓ (translation text)
print_translation (hooked)
    ↓
Terminal + Discord Text Channel
```

Key components:
- `src/discord/audio.py`: Audio input adapter implementing AudioInput contract
- `src/discord/bot.py`: Discord bot with voice commands
- `src/discord/main.py`: CLI entry point

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

## CLI Flags

| Flag | Default | Notes |
|---|---|---|
| `--mode` | `realtime` | `realtime` or `fallback` |
| `--input` | `mic` | `mic` or `device` (realtime only) |
| `--input-device` | `None` | required with `--input device` |
| `--input-rate` | `16000` | input sample rate |
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

## Advanced Usage

For direct module invocation:

```bash
# Realtime mode
python -m src.realtime.main --input mic --src vi --tgt en

# Fallback mode
python -m src.fallback.pipeline --mic 1 --seconds 5
```

## Troubleshooting

### Microphone permission denied

- macOS: `System Settings -> Privacy & Security -> Microphone` and enable Terminal/iTerm.
- Verify detection:

```bash
python app.py --list-input-devices
```

### Input device opens but no transcript appears

- Wrong device index or silent source.
- Run realtime with `--debug` to inspect VAD events.

### Sample-rate mismatch / device open errors

- Match capture rate to device default rate from `--list-input-devices`.
- Common rates: `44100` or `48000`.
- Example:

```bash
python app.py --mode realtime --input device --input-device <INDEX> --input-rate 48000 --no-speaker
```

### Language routing not locking

If the startup shows:
```
[MeetingMode] locked | waiting for first confident detection to lock routing
```
and this message never changes after speech:

- The language-detection heuristic requires at least 2 marker characters (Japanese/Vietnamese) or 5 ASCII words (English). Very short utterances may return uncertain.
- To skip detection and lock immediately, pass explicit `--src` and `--tgt`:

```bash
python app.py --mode realtime --src vi --tgt en --meeting-mode locked
```

## Docs

- [Architecture](docs/architecture.md)
- [Realtime Protocol](docs/realtime_protocol.md)
- [Security](docs/security.md)
- [State](docs/STATE.md)
- [Tasks](docs/TASKS.md)

| `--transcribe-model` | `whisper-1` | fallback only |
| `--chat-model` | `gpt-4o-mini` | fallback only |
| `--src` | `auto` | language source |
| `--tgt` | `auto` | language target |
| `--pairs` | empty | empty means all pairs allowed |
| `--meeting-mode` | `locked` | `locked` or `auto` |
| `--show-input` | off | explicit input transcript flag |
| `--debug` | off | verbose runtime logs |

## Troubleshooting

### Microphone permission denied

- macOS: `System Settings -> Privacy & Security -> Microphone` and enable Terminal/iTerm.
- Verify detection:

```bash
python app.py --list-input-devices
```

### Input device opens but no transcript appears

- Wrong device index or silent source.
- Run realtime with `--debug` to inspect VAD events.

### Sample-rate mismatch / device open errors

- Match capture rate to device default rate from `--list-input-devices`.
- Common rates: `44100` or `48000`.
- Example:

```bash
python app.py --mode realtime --input device --input-device <INDEX> --input-rate 48000 --no-speaker
```

### Language routing not locking

If the startup shows:
```
[MeetingMode] locked | waiting for first confident detection to lock routing
```
and this message never changes after speech:

- The language-detection heuristic requires at least 2 marker characters (Japanese/Vietnamese) or 5 ASCII words (English). Very short utterances may return uncertain.
- To skip detection and lock immediately, pass explicit `--src` and `--tgt`:

```bash
python app.py --mode realtime --src vi --tgt en --meeting-mode locked
```

## Docs

- [Architecture](docs/architecture.md)
- [Realtime Protocol](docs/realtime_protocol.md)
- [Security](docs/security.md)
- [State](docs/STATE.md)
- [Tasks](docs/TASKS.md)
