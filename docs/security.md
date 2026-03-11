# Security Notes

## Secret Handling

### API key source

- Runtime requires `OPENAI_API_KEY`.
- `app.py` loads `.env` from repo root via `python-dotenv`, then reads env var.
- Do not commit real keys; keep `.env` local and `.gitignore`-protected.

### Other env keys in `.env.example`

`.env.example` includes additional values (`OPENAI_REALTIME_MODEL`, `OPENAI_TRANSCRIBE_MODEL`, etc.), but current Python runtime primarily consumes `OPENAI_API_KEY`.

## Data Handling

### Realtime mode

- Audio is streamed in-memory to Realtime WS (`input_audio_buffer.append`).
- No raw realtime audio files are intentionally persisted by current code.

### Fallback mode

- Raw clip is always saved to `recordings/clip_<timestamp>.wav` before transcription.
- Transcript and translation are sent to OpenAI APIs.
- Treat `recordings/` as sensitive data storage.

## Logging Behavior

### Where logs go

- `get_logger()` writes operational logs to stderr.
- File logging (`logs/<name>.log`) exists in utility code but is not enabled by default in current runners.

### What is logged today

- Session lifecycle and event types.
- In some flows, transcript/translation text is logged (`fallback.pipeline`, realtime `response.text.done`).
- Errors/exceptions may include context text.

### Redaction guidance

- Never log API keys or auth headers.
- Avoid logging full transcript content in production contexts.
- If file logging is enabled in future, apply redaction filters before persistence.

## Transport and Network

- Realtime uses TLS WebSocket endpoint `wss://api.openai.com/v1/realtime`.
- Authentication errors (`authentication_error`, `invalid_api_key`) terminate session.
- Restrict outbound network paths where possible to required OpenAI endpoints.

## Privacy Considerations

- Audio capture should be treated as recording/transcription activity.
- Minimum requirements before external use:
  - explicit participant notice and consent
  - approved data retention/deletion policy
  - access controls for any saved artifacts
  - legal/compliance approval for automation path

## Operational Recommendations

1. Store `OPENAI_API_KEY` in a secrets manager or local secure env, not in code.
2. Limit and rotate keys used for demos.
3. Restrict permissions on `recordings/` directory.
4. Add transcript redaction before any persistent logging.
5. Define retention windows and deletion workflows before pilot rollout.

