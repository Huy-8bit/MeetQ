````markdown
# Phase 3: Discord Voice Bot

## Status Snapshot (2026-03-08)

Phase 3 implements the Discord voice channel interpreter bot as an alternative to the Google Meet browser automation approach.

## Overview

The Discord bot joins a voice channel, receives audio from all participants via discord.py's voice receive API, pipes it through the same OpenAI Realtime API interpreter pipeline, and optionally speaks translations back into the voice channel.

### Key advantages over Meet mode

- **No browser automation** — no Playwright, no Chromium, no fragile DOM selectors.
- **No virtual audio devices** — no BlackHole/Loopback/SCK setup needed.
- **Native voice API** — discord.py handles voice connection, encoding, and decoding natively.
- **Simpler deployment** — single process, single dependency chain.
- **Text channel output** — translations are posted to a Discord text channel in addition to terminal.

## Architecture

```
Discord Voice Channel
  └── InterpreterBot (discord.py)
        ├── DiscordAudioSink (voice receive → PCM)
        │     └── DiscordAudioInput (48kHz stereo → 16kHz mono)
        │           └── RealtimeClient (OpenAI Realtime WebSocket)
        │                 ├── [Interp] text → terminal + Discord text channel
        │                 └── response.audio.delta → DiscordAudioOutput
        │                       └── (24kHz mono → 48kHz stereo → voice send)
        └── Commands: !join, !leave, !status, !lang
```

## Module Map

| Module | Responsibility |
|---|---|
| `src/discord/bot.py` | Discord bot lifecycle, command handling, interpreter orchestration |
| `src/discord/audio.py` | Audio adapters: `DiscordAudioInput`, `DiscordAudioOutput`, `DiscordAudioSink` |
| `src/discord/main.py` | CLI entrypoint, argument parsing, bot startup |

## Prerequisites

### 1. Discord Bot Setup

1. Go to https://discord.com/developers/applications
2. Create a new Application
3. Go to **Bot** tab → create a bot, copy the **Token**
4. Enable **Privileged Gateway Intents**:
   - Message Content Intent
   - Server Members Intent (optional, for auto-leave detection)
5. Go to **OAuth2** → URL Generator:
   - Scopes: `bot`
   - Permissions: Connect, Speak, Use Voice Activity, Send Messages, Read Message History
   - Generated URL example:
     ```
     https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=3214336&scope=bot
     ```
6. Open the URL to invite the bot to your server

### 2. System Dependencies

discord.py requires **libopus** for Opus audio encoding/decoding.  
PyNaCl wheel bundles libsodium — no separate install needed.  
FFmpeg is **NOT required** (we use raw PCM `AudioSource`, not `FFmpegPCMAudio`).

```bash
# macOS
brew install opus

# Linux (Debian/Ubuntu)
apt install libopus0
```

### 3. Python Dependencies

```bash
pip install -r requirements.txt
```

Or specifically:
```bash
pip install 'discord.py[voice]>=2.3.0' PyNaCl>=1.5.0
```

### 4. Environment Variables

```bash
export DISCORD_BOT_TOKEN="your-discord-bot-token"
export OPENAI_API_KEY="sk-..."
```

Or add to `.env`:
```
DISCORD_BOT_TOKEN=your-discord-bot-token
OPENAI_API_KEY=sk-...
```

## Usage

### Basic (interactive via commands)

```bash
python app.py --mode discord
```

Then in Discord:
- Join a voice channel
- Type `!join` in any text channel
- Bot joins your voice channel and starts translating
- Translations appear in the text channel and terminal
- Type `!leave` to stop

### Auto-join specific channel

```bash
python app.py --mode discord --voice-channel-id 123456789012345678
```

### Text-only (no TTS speak-back)

```bash
python app.py --mode discord --no-tts
```

### Fixed language pair

```bash
python app.py --mode discord --src ja --tgt vi --meeting-mode locked
```

### Direct module execution

```bash
python -m src.discord.main --voice-channel-id 123456789012345678
```

## Bot Commands

| Command | Description |
|---|---|
| `!join` | Join the user's current voice channel and start interpreting |
| `!leave` | Leave voice channel and stop interpreting |
| `!status` | Show current connection status and stats |
| `!lang <src> <tgt>` | Change language pair (e.g. `!lang ja en`) |

## Audio Pipeline Details

### Input path (Discord → OpenAI)

1. discord.py decodes Opus voice packets from all participants
2. `DiscordAudioSink.write()` receives 48 kHz stereo PCM16 per user
3. Audio is mixed, downsampled to 16 kHz mono, and pushed to queue
4. `DiscordAudioInput.stream_frames()` yields 20ms chunks to `RealtimeClient`
5. Client base64-encodes and sends via `input_audio_buffer.append`

### Output path (OpenAI → Discord)

1. OpenAI sends `response.audio.delta` with 24 kHz mono PCM16
2. `DiscordAudioOutput.push()` upsamples to 48 kHz stereo
3. `DiscordPCMSource.read()` produces 20ms frames for discord.py Opus encoder
4. Bot plays audio into the voice channel

### Text output path

1. OpenAI sends `response.text.delta` / `response.text.done`
2. `print_translation()` prints to terminal (same as Meet/realtime modes)
3. Monkeypatched `print_translation` also forwards to Discord text channel
4. Translation appears as a message in the configured text channel

## Behavioral Features

- **Auto-leave**: Bot automatically disconnects when all human users leave the voice channel.
- **Barge-in**: Same interruption behavior as other modes — new speech cancels in-progress TTS.
- **Language detection**: Same auto-detect/locked/auto modes as Meet bot.
- **Multiple guilds**: Bot can be invited to multiple servers; one voice session at a time.

## Comparison with Meet Mode

| Feature | Meet Bot | Discord Bot |
|---|---|---|
| Platform | Google Meet (browser) | Discord (native API) |
| Audio capture | Virtual device / SCK | discord.py voice receive |
| Audio output | Virtual mic device | discord.py voice send |
| Browser needed | Yes (Playwright/Chromium) | No |
| Virtual audio device | Required (BlackHole/Loopback) or SCK | Not needed |
| Bot identity | Chromium participant | Discord bot user |
| Join method | URL + browser automation | `!join` command or auto-join |
| Text output | Terminal only | Terminal + Discord text channel |
| Setup complexity | High (profile, devices, permissions) | Low (bot token + libopus) |

## Limitations & Known Issues

- **Voice receive** requires discord.py 2.x voice support which depends on libopus for Opus codec.
- **Multi-speaker mixing**: All voice participants are mixed into one audio stream. No speaker diarization.
- **One voice session**: Bot supports one active voice connection at a time per process.
- **Latency**: End-to-end translation latency depends on Discord voice encoding, network, VAD, and OpenAI response time.
- **Rate limits**: Frequent Discord API calls (e.g., posting every translation line) may hit rate limits for busy channels. Consider batching or debouncing in production.

## Next Steps

- [ ] Add slash command support (`/join`, `/leave`, `/lang`) alongside prefix commands
- [ ] Add translation debouncing for text channel output (batch short translations)
- [ ] Add per-user speaker labels using discord.py user detection
- [ ] Test with multi-server simultaneous connections
- [ ] Add reconnection handling for voice disconnects
- [ ] Production hardening: rate limit handling, error recovery, health checks

````
