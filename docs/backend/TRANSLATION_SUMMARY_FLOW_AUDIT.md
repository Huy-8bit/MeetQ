# Translation And Summary Flow Audit

Audit date: 2026-05-10

Scope: current codebase inspection only. No code was changed for this audit.

## Short Conclusion

Live meeting translation is not batched across multiple users or multiple transcript lines in the normal path. The backend creates a separate realtime runtime per speaker microphone track, opens a separate utterance state per committed audio item, validates the completed source transcript, then creates a relay response from that single validated transcript.

Meeting summary is not updated incrementally per line. The official meeting summary is generated on demand or at room end by collecting many transcript/chat messages from Redis snapshot or Mongo archive, then making one OpenAI Chat Completions call for the whole selected source set.

There is a separate live "overlap summary relay" path. During heavy overlap, the backend can collect several validated source turns from a short overlap window and generate one summary-style relay. This is not the official meeting recap.

## Entry Points And Runtime Boundaries

### Frontend To Backend

The frontend does not send meeting audio over the Gateway WebSocket. It connects to LiveKit and publishes local microphone media:

- `FE/src/features/room/useMeetingRoom.ts`
  - `connectLiveKit(...)`
  - `publishLocalMedia(...)`
- `FE/src/lib/livekit.ts`
  - `publishLocalMedia`
  - `buildMicrophoneCaptureOptions`

Gateway WebSocket `/ws/rooms/{room_id}` handles control events, chat, language changes, BRSE toggles, screen share controls, ping/pong, and receives transcript events from backend fan-out. It does not receive meeting audio frames.

Evidence:

- `BE/server/service/gateway/ws_endpoint.py`
  - `websocket_endpoint`
  - event names handled: `ping`, `set_language`, `chat.send`, `room.brse.enable`, `room.brse.disable`, `screen_share.start`, `screen_share.stop`

### Gateway To Brain Runtime

Gateway publishes room/participant control events to Redis. The Brain runtime daemon listens on the Gateway control channel and creates a room interpreter manager when a participant joins and BRSE is enabled.

Evidence:

- `BE/server/service/brain_runtime/daemon.py`
  - `InterpreterDaemon._handle_gateway_event`
  - `EventType.PARTICIPANT_JOINED`
  - `_spawn_manager`
- `BE/server/service/brain_runtime/main.py`
  - starts `InterpreterDaemon`

### Brain Runtime To LiveKit

`LiveKitRuntime` joins the LiveKit room as the virtual BRSE participant, subscribes to human microphone tracks, and passes each subscribed human audio stream to the room manager.

Evidence:

- `BE/server/service/media/livekit_runtime.py`
  - `LiveKitRuntime.connect`
  - `LiveKitRuntime._on_track_subscribed`
  - `rtc.AudioStream.from_track(..., sample_rate=..., frame_size_ms=20)`
  - `_is_human_microphone_audio`

## Live Translation Flow

Sequence:

1. Browser publishes microphone audio to LiveKit.
2. Brain runtime joins the same LiveKit room as BRSE virtual participant.
3. Brain runtime subscribes to each human microphone track.
4. `RoomInterpreterManager._handle_audio_stream` registers that speaker stream.
5. `_reconcile_speaker` builds a route for that speaker from room language pair.
6. `_ensure_speaker_runtime` creates one `LiveKitAudioInput`, one `OutputRouter`, and one `InterpreterRealtimeClient` for that speaker.
7. `InterpreterRealtimeClient._send_audio` streams audio chunks to OpenAI Realtime via `input_audio_buffer.append`.
8. OpenAI Realtime server VAD emits speech/commit/transcription events.
9. On `input_audio_buffer.committed`, backend opens one utterance state.
10. Transcript deltas update/publish source partials.
11. Completed source transcript is validated.
12. If approved, backend sends `response.create` with only the validated transcript text as input.
13. Translation/relay text deltas and final text are published as transcript partial/final events.
14. Gateway consumes interpreter Redis events, stores final transcripts in Redis/Mongo, and fans out to FE via Gateway WebSocket.

Evidence:

- `BE/server/service/brain_runtime/room_manager.py`
  - `_handle_audio_stream`
  - `_reconcile_speaker`
  - `_build_routing_resolution`
  - `_ensure_speaker_runtime`
  - `_bind_client_callbacks`
  - `_open_transcript_state`
  - `_publish_source_partial`
  - `_publish_source_final`
  - `_publish_partial`
  - `_publish_final`
- `BE/server/brain/realtime/interpreter_client.py`
  - `_send_audio`
  - `_handle_event`
  - `_create_response_from_source_transcript`
  - `_send_relay_response`
- `BE/server/service/gateway/event_consumer.py`
  - `_handle_interpreter_events`
  - `_build_transcript_event`
- `BE/server/service/brain_runtime/events.py`
  - `RedisEventPublisher.publish_source_transcript_partial`
  - `RedisEventPublisher.publish_source_transcript_final`
  - `RedisEventPublisher.publish_relay_transcript_partial`
  - `RedisEventPublisher.publish_relay_transcript_final`

## Translation Level

### Live Audio Translation

Live audio translation is per speaker runtime and per utterance. It is not per room batch in the normal path.

Details:

- One `InterpreterRealtimeClient` is created per `speaker_id`.
- One `LiveKitAudioInput` is created per `speaker_id`.
- One `OutputRouter` is created per `speaker_id`.
- One utterance state is opened per OpenAI `input_audio_buffer.committed` event.
- Relay response is created from one validated source transcript or from one overlap-summary source text.

Evidence:

- `BE/server/service/brain_runtime/room_manager.py`
  - `_ensure_speaker_runtime`
  - `_open_transcript_state`
  - callback `on_input_audio_committed`
  - callback `on_transcript_complete`
  - callback `approve_transcript_for_relay`
- `BE/server/brain/realtime/interpreter_client.py`
  - `conversation.item.input_audio_transcription.completed`
  - `_create_response_from_source_transcript`
  - `_send_relay_response`

### Chat Translation

Chat translation is a separate text-only path and is per chat message.

Flow:

1. FE sends Gateway WebSocket event `chat.send`.
2. `ws_endpoint.py` calls `RoomService.send_chat_message`.
3. If `translation_mode == "translate"`, backend resolves target language from room pair and sender language.
4. `translate_chat_message` calls OpenAI Chat Completions for that single chat message.
5. Original chat plus optional translation is stored and broadcast as `chat.message`.

Evidence:

- `BE/server/service/gateway/ws_endpoint.py`
  - event `chat.send`
- `BE/server/service/gateway/room_service.py`
  - `send_chat_message`
- `BE/server/service/gateway/chat_translator.py`
  - `resolve_chat_target_language`
  - `translate_chat_message`

### Translation Test Flow

Translation test is independent of meeting rooms and LiveKit.

Flow:

1. REST `POST /api/test/translation` creates a test session.
2. FE connects to `/ws/test/translation/{session_id}`.
3. FE sends binary PCM16 audio frames over the WebSocket.
4. Gateway process runs a `TranslationTestClient`.
5. Translation test emits `translation_test.partial` and `translation_test.final`.

Evidence:

- `BE/server/service/gateway/api_test_sessions.py`
  - `create_translation_test_session`
- `BE/server/service/gateway/ws_test_translation.py`
  - websocket `/ws/test/translation/{session_id}`
  - `client.push_audio(pcm_bytes)`
- `BE/server/brain/realtime/translation_test_client.py`
  - `TranslationTestClient`
  - `_QueueAudioInput`

## Official Meeting Summary Flow

Official meeting summary is room-level and source-set-level, not per-line.

There are two summary types:

- `interim`: generated on demand while the room is active.
- `final`: generated on demand after room end, or automatically when room becomes empty/expired.

### Interim Summary

Trigger:

- HTTP `POST /api/rooms/{room_id}/summary?type=interim`
- If no explicit type is passed and room is still active, backend resolves to `interim`.

Source:

- Redis room snapshot.
- Final transcripts only.
- Recent chat messages.
- Limited by `MEETING_SUMMARY_MAX_SOURCE_ITEMS`.

Evidence:

- `BE/server/service/gateway/api_rooms.py`
  - `generate_room_summary`
- `BE/server/service/gateway/room_service.py`
  - `generate_meeting_summary`
  - `_resolve_summary_type`
  - `_build_interim_summary_source`
- `BE/server/service/gateway/meeting_summary_service.py`
  - `generate_interim_from_source`

### Final Summary

Triggers:

- Scheduled expiry task after room `expires_at`.
- Room becomes empty when last human leaves.
- HTTP `POST /api/rooms/{room_id}/summary?type=final`, but only after room is expired or empty.

Source:

- Mongo archive.
- Messages with kind in `source`, `translated`, `relay`, `chat`.
- Limited by `MEETING_SUMMARY_MAX_SOURCE_ITEMS`.

Evidence:

- `BE/server/service/gateway/room_service.py`
  - `_schedule_room_expiry_summary`
  - `_persist_room_expiry_after_delay`
  - `_persist_room_expired_and_summary`
  - `cleanup_participant`
  - `generate_meeting_summary`
- `BE/server/service/gateway/meeting_summary_service.py`
  - `generate_for_room_end`
  - `_generate_and_persist`
- `BE/server/service/persistence/room_history.py`
  - `collect_meeting_summary_source`
  - `create_meeting_summary_pending`
  - `persist_meeting_summary_completed`
  - `persist_meeting_summary_skipped`
  - `persist_meeting_summary_failed`
- `BE/server/brain/meeting_summary.py`
  - `generate_meeting_summary`

### Summary Model Call

Official meeting summary uses OpenAI Chat Completions, not Realtime API.

Evidence:

- `BE/server/brain/meeting_summary.py`
  - `openai.AsyncOpenAI`
  - `client.chat.completions.create`
  - `response_format={"type": "json_object"}`

## Live Overlap Summary Relay

This is not the same as official meeting summary.

During live relay, when multiple speakers overlap, backend uses a room-level relay focus. One speaker can hold focus; other speakers are marked as blocked for public relay, while capture continues. If overlap becomes heavy, backend can build a bounded summary prompt from recent validated source turns and relay that summary to target-language listeners.

Parameters found in code:

- `_OVERLAP_FOCUS_COOLDOWN_SECONDS = 0.85`
- `_CHAOS_RECENT_WINDOW_SECONDS = 9.0`
- `_OVERLAP_UNDERSTANDING_WINDOW_SECONDS = 9.0`
- `_OVERLAP_SUMMARY_MIN_TURNS = 2`
- `_CHAOS_MIN_DISTINCT_SPEAKERS = 2`
- `_OVERLAP_SUMMARY_MIN_SIGNAL_CHARS = 24`
- `_OVERLAP_SUMMARY_MAX_TURNS = 6`
- `_SUMMARY_MAX_SOURCE_CHARS = 1400`

Flow:

1. `on_speech_started` calls `_handle_speech_started`.
2. If no speaker has focus, current speaker claims relay focus.
3. If another speaker already has focus, current speaker is blocked for public relay and an overlap window is opened.
4. Completed valid source turns are recorded in `recent_validated_source_turns`.
5. `_build_summary_plan_if_chaotic` checks overlap level and window content.
6. If eligible, it creates a summary source text from recent/window turns and marks the current state as `relay_style = "summary"`.
7. `InterpreterRealtimeClient._send_relay_response` uses summary instructions and sends `response.create`.
8. Relay final is published as a normal transcript final with `relay_style = "summary"`.

Evidence:

- `BE/server/service/brain_runtime/room_manager.py`
  - constants near top of file
  - `_handle_speech_started`
  - `_block_speaker_due_to_overlap`
  - `_open_overlap_understanding_window`
  - `_current_overlap_understanding_window`
  - `_record_validated_source_turn`
  - `_overlap_level`
  - `_build_summary_plan_if_chaotic`
  - callback `on_transcript_complete`
  - `_publish_final`
- `BE/server/brain/realtime/interpreter_client.py`
  - `_send_relay_response`
  - `relay_style == "summary"`
- `BE/server/brain/realtime/session_config.py`
  - `build_interpreter_summary_instructions`

## Persistence And Caches

### Active State In Redis

Redis is active runtime state and recent-room cache.

Keys:

- `room:{room_id}:meta`
- `room:{room_id}:participants`
- `room:{room_id}:transcripts`
- `room:{room_id}:chat`

Limits:

- Transcript list limit defaults to 50.
- Chat list limit defaults to 100.
- TTL is room meeting duration plus grace period.

Evidence:

- `BE/server/service/gateway/room_store.py`
  - `RoomStore`
  - `_meta_key`
  - `_parts_key`
  - `_trans_key`
  - `_chat_key`
  - `append_transcript`
  - `append_chat_message`

### Durable Archive In Mongo

Mongo sidecar collections:

- `rooms`
- `room_participants`
- `room_messages`
- `meeting_summaries`

Transcript final messages are persisted as one document keyed by room, message id, and kind. Official meeting summary source is later collected from `room_messages`.

Evidence:

- `BE/server/service/persistence/room_history.py`
  - `MongoRoomHistoryRepository`
  - `persist_transcript`
  - `collect_meeting_summary_source`
  - `persist_meeting_summary_completed`

## Batching, Windowing, Debounce, Rate Limit, Retry

### Translation

Normal live translation:

- No batch across multiple users.
- No batch across multiple utterances in normal relay.
- Translation response is created from one validated source transcript.

Queueing:

- `InterpreterRealtimeClient` queues relay responses if a response is already busy or room focus does not allow start.
- Queue is per speaker client.

Evidence:

- `BE/server/brain/realtime/interpreter_client.py`
  - `_pending_relay_requests`
  - `_create_response_from_source_transcript`
  - `_start_next_pending_relay`
  - `pending_relay_count`

Debounce/hold:

- `INTERPRETER_FINAL_TRANSCRIPT_HOLD_MS = 240`
- Normal relay waits briefly after speech stop before `response.create`, unless relay style is `summary`.

Evidence:

- `BE/server/brain/realtime/session_config.py`
  - `INTERPRETER_FINAL_TRANSCRIPT_HOLD_MS`
- `BE/server/brain/realtime/interpreter_client.py`
  - `_hold_for_turn_completion`

Audio queue/drop:

- `LiveKitAudioInput` has queue capacity, warmup chunks, and drop counters.
- `InterpreterRealtimeClient` has send queue maxsize and logs queue drops.

Evidence:

- `BE/server/service/media/audio_input.py`
  - `LiveKitAudioInput`
  - `_enqueue_chunk`
  - `stats_snapshot`
- `BE/server/brain/realtime/interpreter_client.py`
  - `_send_audio`
  - `_log_send_queue_drop`

Retry:

- OpenAI Realtime connection retries are implemented in base `RealtimeClient._run_with_retry`.
- Constants: `MAX_RECONNECT_ATTEMPTS = 5`, `RECONNECT_BASE_DELAY = 1.0`.

Evidence:

- `BE/server/brain/realtime/client.py`
  - `MAX_RECONNECT_ATTEMPTS`
  - `RECONNECT_BASE_DELAY`
  - `_run_with_retry`

### Meeting Summary

Official meeting summary is batch-style by source set:

- Interim: latest final transcripts/chat from Redis snapshot.
- Final: archived messages from Mongo.
- No per-line incremental update.
- No cron found in repo.
- Scheduled room expiry task is an in-process async task, not cron.

Evidence:

- `BE/server/service/gateway/room_service.py`
  - `_schedule_room_expiry_summary`
  - `_persist_room_expiry_after_delay`
- `BE/server/service/gateway/meeting_summary_service.py`
  - `generate_for_room_end`
  - `generate_interim_from_source`
- `BE/server/service/persistence/room_history.py`
  - `collect_meeting_summary_source`

## Multiple Users Speaking At Once

Backend captures each speaker independently because each human microphone track gets its own `LiveKitAudioInput` and `InterpreterRealtimeClient`.

Public relay is coordinated room-wide:

- One speaker can hold relay focus.
- Another simultaneous speaker is marked blocked for public relay.
- Blocked speaker capture can continue.
- Normal relay output for blocked/overlapped turns may be suppressed or queued.
- Heavy overlap can produce one overlap summary relay from multiple validated turns.

So the answer is mixed:

- Capture/transcription/runtime: independent per speaker.
- Public live relay arbitration: room-level focus, not fully independent.
- Heavy overlap fallback: can combine multiple speakers/turns into one summary relay.

Evidence:

- `BE/server/service/brain_runtime/room_manager.py`
  - `self.clients: Dict[str, InterpreterRealtimeClient]`
  - `self.active_inputs: Dict[str, LiveKitAudioInput]`
  - `_handle_speech_started`
  - `_claim_relay_focus`
  - `_block_speaker_due_to_overlap`
  - `_speaker_generation_can_publish`
  - `_build_summary_plan_if_chaotic`

## Direct Answers To Requested Questions

### 1. Each audio/transcript line processed separately or batched?

Normal live audio translation: separately per speaker and per utterance. Not batched across users/lines.

Exception: overlap summary relay can batch several validated source turns inside a short overlap window when heavy overlap is detected.

### 2. Translation level?

Live audio translation:

- Per speaker runtime.
- Per utterance/line response after completed source transcript.

Chat translation:

- Per chat message.

Translation test:

- Per test session, utterance-oriented through realtime VAD.

Not confirmed/found:

- No normal room-wide translation batch.
- No post-process translation after collected transcript in live meeting path.

### 3. Summary level?

Official meeting summary:

- Interim: on-demand room-level batch from Redis snapshot.
- Final: room-end/on-demand room-level batch from Mongo archive.
- Not incremental per line.

Live overlap summary relay:

- Window/chunk style over recent validated source turns during heavy overlap.
- It is a live relay fallback, not meeting recap.

### 4. Backend trigger points?

Translation:

- Meeting audio path: LiveKit track subscription in Brain runtime, triggered by participant room events over Redis.
- Gateway WebSocket is used for fan-out/control, not audio ingestion.
- Chat translation: Gateway WebSocket event `chat.send`.
- Translation test: HTTP creates session, test WebSocket streams binary PCM.

Summary:

- HTTP `GET /api/rooms/{room_id}/summary` fetches persisted summary.
- HTTP `POST /api/rooms/{room_id}/summary` generates interim/final depending type/state.
- Background async task on scheduled room expiry can generate final summary.
- Participant cleanup when room becomes empty can generate final summary.

### 5. Data steps?

Live meeting:

1. Browser microphone
2. LiveKit media track
3. Brain `LiveKitRuntime`
4. `LiveKitAudioInput`
5. `InterpreterRealtimeClient`
6. OpenAI Realtime transcription
7. Source transcript partial/final
8. Validated source transcript
9. OpenAI Realtime `response.create` for relay
10. Relay transcript/audio deltas/final
11. Redis interpreter event
12. Gateway event consumer
13. Redis recent transcript cache
14. Mongo `room_messages`
15. Gateway WebSocket fan-out to FE

Official summary:

1. Final transcript/chat persisted
2. Summary trigger by HTTP or room end
3. Source collected from Redis snapshot or Mongo archive
4. OpenAI Chat Completions summary
5. Mongo `meeting_summaries`
6. FE fetch/poll via HTTP

### 6. Debounce/batching/windowing/rate limit/retry?

Found:

- 240 ms final transcript hold before normal relay.
- Per-client relay queue.
- Audio input queue/warmup/drop.
- OpenAI realtime reconnect retry.
- 9 second overlap recent/window logic.
- Official summary source item max limit.

Not found:

- Explicit global rate limiter for translation.
- Cron-based summary job.
- DB-triggered workflow.

### 7. Multiple users speak at once?

Capture and ASR remain per speaker. Public relay is arbitrated by room-level focus. Heavy overlap may produce a combined summary relay over multiple validated turns.

## Ambiguities / Not Confirmed

The audit did not run a live meeting, so runtime ordering and provider behavior are inferred from code paths and OpenAI event handlers only.

No external cron or DB trigger was found in the repository. If deployment has infrastructure-level scheduled jobs outside this repo, they are not confirmed here.

`translated` transcript kind exists in models/persistence, but the inspected live BRSE path primarily publishes `source` and `relay`. A separate live `translated` flow was not confirmed in current backend code.

