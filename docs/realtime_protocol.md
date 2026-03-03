# Realtime Protocol

This document lists the key Realtime WebSocket events for this demo.

References:
- https://platform.openai.com/docs/guides/realtime-websocket
- https://platform.openai.com/docs/guides/realtime-model-capabilities
- https://platform.openai.com/docs/api-reference/realtime-client-events
- https://platform.openai.com/docs/api-reference/realtime-server-events

## Session Behavior

On connect, client sends `session.update` with:
- Audio input format: `pcm16` at `16000` Hz
- Audio output format: `pcm16` at `24000` Hz (when speaker enabled)
- Modalities: `["text", "audio"]` (or `["text"]` with `--no-speaker`)
- Voice: `alloy`
- Turn detection: `server_vad`
- Temperature: `0.8` (minimum allowed is `0.6`)
- Instructions that enforce translation-only behavior:
  - If user speaks Vietnamese → output English translation only
  - If user speaks English → output Vietnamese translation only
  - No commentary or explanations

## Event Flow — Voice-to-Voice Turn

```
1. Client opens wss://api.openai.com/v1/realtime?model=...
2. Server → session.created
3. Client → session.update
4. Server → session.updated
5. Client → input_audio_buffer.append  (continuous, ~20ms PCM16 chunks)
6. Server → input_audio_buffer.speech_started
7. Server → conversation.item.input_audio_transcription.delta  (streaming input transcript)
8. Server → input_audio_buffer.speech_stopped
9. Server → input_audio_buffer.committed
10. Server → response.created
11. Server → response.audio.delta          (streaming PCM16 audio — played by SpeakerPlayer)
12. Server → response.text.delta           (streaming translated text — printed to terminal)
13. Server → response.audio.done
14. Server → response.text.done
15. Server → response.audio_transcript.done
16. Server → response.done
```

## Barge-In / Interruption Flow

When `input_audio_buffer.speech_started` fires while assistant is speaking:

```
Server → input_audio_buffer.speech_started
Client → response.cancel                  (cancel in-progress response)
Client: SpeakerPlayer.restart()           (immediately flush audio buffer)
Client: _assistant_speaking = False
```

The server acknowledges with `response.done` (with status=cancelled).

## Important Client Events

| Event | When used |
|---|---|
| `session.update` | Configure model behavior, VAD, modalities, voice, temperature |
| `input_audio_buffer.append` | Stream mic PCM16 chunks continuously |
| `response.cancel` | Cancel in-progress response on barge-in |

## Important Server Events

| Event | Handled by client |
|---|---|
| `session.created` | Log session ID |
| `session.updated` | Confirm config applied |
| `input_audio_buffer.speech_started` | Trigger barge-in if assistant speaking |
| `input_audio_buffer.speech_stopped` | Log only |
| `input_audio_buffer.committed` | Log in debug mode |
| `conversation.item.input_audio_transcription.delta` | Show `[You]` prefix in debug mode |
| `conversation.item.input_audio_transcription.completed` | Print `[You] <transcript>` |
| `response.created` | Print `[Interp] ` prefix, mark assistant_speaking=True |
| `response.text.delta` | Stream translation text to stdout |
| `response.text.done` | Print newline, log final translation |
| `response.audio.delta` | Decode base64 PCM16, push to SpeakerPlayer |
| `response.audio.done` | Call SpeakerPlayer.flush() (50ms silence pad) |
| `response.audio_transcript.done` | Log in debug mode |
| `response.done` | Mark assistant_speaking=False |
| `error` | Log; abort on auth errors |

## Audio Format Details

| Direction | Format | Sample Rate | Channels |
|---|---|---|---|
| Input (mic → API) | PCM16 | 16000 Hz | 1 (mono) |
| Output (API → speaker) | PCM16 | 24000 Hz | 1 (mono) |

The API returns audio as base64-encoded PCM16 in `response.audio.delta`.
Client decodes with `base64.b64decode()` and passes raw bytes to `SpeakerPlayer.push()`.

## Minimal Instruction String

```text
You are a live bilingual interpreter between Vietnamese and English.
Detect whether the user spoke Vietnamese or English.
If Vietnamese, output ONLY the English translation.
If English, output ONLY the Vietnamese translation.
Output the translation text only. No explanations, no labels, no commentary.
```

## Known API Constraints

- `temperature` must be `>= 0.6`. Values below this are rejected with `decimal_below_min_value` error.
- Setting `modalities: ["text"]` disables audio output — `response.audio.*` events are not sent.
- `response.cancel` must be sent promptly when new speech starts to interrupt playback.
