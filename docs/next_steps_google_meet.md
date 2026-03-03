# Next Steps: Google Meet Audio Ingestion (Phased Plan)

This plan extends the local mic demo into Google Meet scenarios without implementing Meet integration yet.

## Phase 0: Stabilize Local Demo

- Finalize realtime mic interpreter flow with robust logs and reconnection.
- Validate fallback mode reliability under poor network conditions.
- Add basic test harnesses for event parsing and language-direction policy.

Exit criteria:
- Realtime mode handles 30+ minute sessions without crash.
- Fallback mode succeeds for common mic formats.

## Phase 1: Desktop Loopback Prototype (No Meet API Yet)

- Ingest meeting audio from system loopback device.
- macOS options: BlackHole/Loopback virtual device.
- Linux options: PulseAudio/PipeWire monitor source.
- Reuse same chunking, VAD, and translation output pipeline.

Exit criteria:
- Can translate mixed EN/VI audio played from local meeting app.

## Phase 2: Multi-Channel and Speaker Context

- Separate local microphone vs remote meeting audio channels.
- Add speaker labeling heuristics if channel metadata is available.
- Improve turn segmentation for overlapping speech.

Exit criteria:
- Translation output is clearly attributable (self vs remote).

## Phase 3: Meet-Native Integration Design

- Evaluate Google Meet ingestion options (bot participant or approved APIs).
- Define auth, consent UX, and participant notification requirements.
- Define buffering and latency budget per stage.

Exit criteria:
- Approved architecture doc with legal/security review.

## Phase 4: Production-Readiness Work

- Add robust retries, backoff, and rate-limit handling.
- Add metrics dashboard (latency, error rate, speech-to-text quality).
- Add configurable privacy controls and retention settings.

Exit criteria:
- Controlled pilot with observability and incident runbook.

## Risks To Resolve Before Meet Integration

- Legal and consent requirements for recording/transcribing meetings.
- Audio quality variance across devices and conferencing setups.
- Latency growth with multi-hop streaming and translation.
- Cross-platform audio routing complexity.
