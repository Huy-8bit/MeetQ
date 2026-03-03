# Security Notes

## API Key Handling

- Use `OPENAI_API_KEY` from environment variables.
- Do not hardcode secrets in source files.
- Keep `.env` out of version control.
- Rotate keys if exposed or shared accidentally.

## Data Handling

- Treat microphone audio as sensitive user data.
- Default to in-memory processing for realtime chunks.
- Save recordings only when explicitly enabled by user.
- If recordings are saved, store them under `recordings/` and document retention policy.

## Logging Safety

- Include operational telemetry (timestamps, event types, latency).
- Avoid logging full API keys, raw auth headers, or highly sensitive transcripts.
- Redact secrets in exception paths.

## Transport and Endpoint Safety

- Use `wss://api.openai.com` with TLS.
- Validate model names and reject untrusted endpoint overrides.
- Fail closed on auth errors or malformed server events.

## Abuse and Misuse Guardrails

- Surface clear consent guidance before capturing microphone audio.
- For shared environments, indicate when mic capture is active.
- If extended to meeting platforms later, require explicit participant consent and policy review.

## Dependency Hygiene

- Pin minimal dependency versions in `requirements.txt`.
- Keep dependencies updated for security fixes.
- Prefer well-maintained libraries (`sounddevice`, `websockets`, official OpenAI SDK).
