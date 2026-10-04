"""Drives RoomInterpreterManager callbacks through one utterance to check ops tracing.

The manager is real; the realtime client, output router and publisher are fakes.
"""
import asyncio

import pytest
import pytest_asyncio

import server.service.brain_runtime.room_manager as room_manager_module
from server.service.brain_runtime.room_manager import RoomInterpreterManager


class FakePublisher:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record

    def named(self, name):
        return [(args, kwargs) for call, args, kwargs in self.calls if call == name]


class FakeRouter:
    def clear_queue(self):
        pass

    def hold_public_output(self, *, reason):
        pass

    def reset_public_output_gate(self):
        pass

    async def release_public_output(self, *, reason):
        pass

    async def reject_public_output(self, *, reason):
        pass

    async def capture_base64_audio(self, encoded):
        return True

    async def flush(self):
        return True

    async def shutdown(self):
        pass

    def audio_track_name(self):
        return "brse::pt_huy::vi::ja"

    def track_descriptor(self):
        return {"track_available": True, "track_name": "brse::pt_huy::vi::ja"}


class FakeClient:
    def __init__(self):
        self.source_id = None
        self.request_audio_output = True

    def current_response_source_id(self):
        return self.source_id

    def pending_relay_count(self):
        return 0


@pytest_asyncio.fixture
async def manager(fake_settings, monkeypatch):
    monkeypatch.setattr(room_manager_module, "_RELAY_STATE_CLEANUP_DELAY_SECONDS", 0.01)
    publisher = FakePublisher()
    instance = RoomInterpreterManager("rm_trace", fake_settings, publisher, room_languages=["vi", "ja"])
    for participant_id, name, language in (("pt_huy", "Huy", "vi"), ("pt_kenji", "Kenji", "ja")):
        instance.participants[participant_id] = {
            "participant_id": participant_id,
            "display_name": name,
            "language": language,
            "status": "connected",
            "kind": "human",
            "is_virtual": False,
        }
    return instance, publisher


def _bind(instance):
    client = FakeClient()
    router = FakeRouter()
    generation = instance._next_speaker_generation("pt_huy")
    instance.speaker_sources["pt_huy"] = "vi"
    instance.speaker_targets["pt_huy"] = "ja"
    instance.speaker_audiences["pt_huy"] = frozenset({"pt_kenji"})
    instance.speaker_relay_enabled["pt_huy"] = True
    instance.speaker_route_modes["pt_huy"] = "cross_language"
    instance.routers["pt_huy"] = router
    instance.clients["pt_huy"] = client
    instance._bind_client_callbacks(
        speaker_id="pt_huy", src_lang="vi", target_lang="ja", generation=generation, client=client, router=router
    )
    return client


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_delivered_relay_emits_one_trace_with_stage_timings(manager):
    instance, publisher = manager
    client = _bind(instance)

    client.on_speech_started()
    client.on_speech_stopped(1500)
    client.on_input_audio_committed("item_1")
    client.on_transcript_complete("Mình sẽ deploy production tối nay nhé mọi người")
    approval = client.approve_transcript_for_relay("Mình sẽ deploy production tối nay nhé mọi người", "item_1")
    assert approval and approval["relay_style"] == "normal"
    client.source_id = approval["relay_source_id"]
    client.on_relay_response_starting(approval["relay_source_id"])
    client.on_text_delta("今夜、本番環境に")
    client.on_audio_delta("AAAA")
    client.on_text_delta("デプロイします。")
    client.on_text_done("今夜、本番環境にデプロイします。")
    client.on_response_done(approval["relay_source_id"])
    await _settle()

    traces = publisher.named("publish_relay_trace")
    assert len(traces) == 1
    payload = traces[0][0][0]
    assert payload["outcome"] == "delivered"
    assert payload["audio_delivered"] is True
    assert payload["policy_decision"] == "publish"
    for key in ("stt_ms", "first_text_ms", "first_audio_ms", "total_ms"):
        assert payload["metrics"][key] is not None, key
    # Meeting output is unchanged: the relay final is still published once.
    assert len(publisher.named("publish_relay_transcript_final")) == 1


@pytest.mark.asyncio
async def test_rejected_source_and_stt_failure_emit_traces(manager):
    instance, publisher = manager
    client = _bind(instance)

    client.on_input_audio_committed("item_a")
    client.on_transcript_complete("ừm")
    client.on_input_audio_committed("item_b")
    client.on_input_rejected("item_b", "input_transcription_failed")
    await _settle()

    outcomes = [args[0]["outcome"] for args, _ in publisher.named("publish_relay_trace")]
    assert outcomes == ["source_rejected", "stt_failed"]
    assert not publisher.named("publish_relay_transcript_final")


@pytest.mark.asyncio
async def test_connection_errors_are_published_as_ops_only_errors(manager):
    instance, publisher = manager
    client = _bind(instance)

    client.on_connection_error("WebSocket closed: invalid_api_key", 1, False)
    client.on_connection_error("WebSocket closed: going away", 5, True)
    await _settle()

    codes = [args[0] for args, _ in publisher.named("publish_ai_error")]
    assert codes == ["realtime_auth_error", "realtime_unavailable"]
    assert not publisher.named("publish_error")  # nothing new is broadcast to participants
