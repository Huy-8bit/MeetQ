"""In-room AI relay mode switching (Voice + Text <-> Text Only): API, validation, events, runtime."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import server.service.brain_runtime.room_manager as room_manager_module
from server.events import EventType
from server.service.brain_runtime.daemon import InterpreterDaemon
from server.service.brain_runtime.room_manager import RoomInterpreterManager
from server.service.gateway.app_state import app_state


def _create(client, languages, **extra):
    res = client.post("/api/rooms", json={"room_languages": languages, **extra})
    assert res.status_code == 200, res.text
    return res.json()["room"]["room_id"]


def _join(client, room_id, name, language):
    res = client.post(f"/api/rooms/{room_id}/join", json={"display_name": name, "language": language})
    assert res.status_code == 200, res.text
    return res.json()


def _auth(join):
    return {"Authorization": f"Bearer {join['room_token']['token']}"}


def _set_mode(client, room_id, join, mode):
    return client.patch(f"/api/rooms/{room_id}/relay-mode", json={"mode": mode}, headers=_auth(join))


def _mode_events(fake_redis):
    events = [json.loads(message) for _channel, message in fake_redis.published]
    return [event for event in events if event["type"] == EventType.ROOM_RELAY_MODE_UPDATED]


# ── API & validation ───────────────────────────────────────────────────────

def test_two_language_room_switches_both_ways_and_broadcasts(gateway_app, fake_redis):
    room_id = _create(gateway_app, ["vi", "ja"], brse_output_mode="voice_text")
    huy = _join(gateway_app, room_id, "Huy", "vi")

    res = _set_mode(gateway_app, room_id, huy, "text_only")
    assert res.status_code == 200, res.text
    room = res.json()
    assert room["brse_output_mode"] == "text_only"
    assert room["brse_enabled"] is True
    assert room["audio_routing"]["ai_audio_output_enabled"] is False
    assert room["audio_routing"]["relay_text_output_enabled"] is True

    events = _mode_events(fake_redis)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["previous_output_mode"] == "voice_text"
    assert payload["brse_output_mode"] == "text_only"
    assert payload["changed_by"] == huy["participant"]["participant_id"]

    back = _set_mode(gateway_app, room_id, huy, "voice_text")
    assert back.status_code == 200
    assert back.json()["audio_routing"]["ai_audio_output_enabled"] is True
    assert [event["payload"]["brse_output_mode"] for event in _mode_events(fake_redis)] == ["text_only", "voice_text"]


def test_same_mode_is_a_no_op_without_event(gateway_app, fake_redis):
    room_id = _create(gateway_app, ["vi", "ja"], brse_output_mode="voice_text")
    huy = _join(gateway_app, room_id, "Huy", "vi")
    assert _set_mode(gateway_app, room_id, huy, "voice_text").status_code == 200
    assert _mode_events(fake_redis) == []


@pytest.mark.parametrize("languages", [["en"], ["vi", "ja", "en"]])
def test_voice_text_rejected_outside_two_language_rooms(gateway_app, languages):
    room_id = _create(gateway_app, languages)
    member = _join(gateway_app, room_id, "Huy", languages[0])
    res = _set_mode(gateway_app, room_id, member, "voice_text")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "relay_mode_not_supported"


def test_invalid_mode_value_rejected(gateway_app):
    room_id = _create(gateway_app, ["vi", "ja"])
    huy = _join(gateway_app, room_id, "Huy", "vi")
    assert _set_mode(gateway_app, room_id, huy, "off").status_code == 422


def test_expired_room_rejects_update(gateway_app, fake_redis):
    room_id = _create(gateway_app, ["vi", "ja"])
    huy = _join(gateway_app, room_id, "Huy", "vi")
    key = f"room:{room_id}:meta"
    meta = json.loads(fake_redis.data[key])
    meta["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    fake_redis.data[key] = json.dumps(meta)
    res = _set_mode(gateway_app, room_id, huy, "text_only")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "room_expired"


def test_requires_participant_of_the_room(gateway_app):
    room_id = _create(gateway_app, ["vi", "ja"])
    other_room = _create(gateway_app, ["vi", "ja"])
    outsider = _join(gateway_app, other_room, "Mallory", "vi")
    res = gateway_app.patch(f"/api/rooms/{room_id}/relay-mode", json={"mode": "text_only"}, headers=_auth(outsider))
    assert res.status_code == 403
    assert gateway_app.patch(f"/api/rooms/{room_id}/relay-mode", json={"mode": "text_only"}).status_code in (401, 403)


def test_mode_change_while_ai_off_keeps_ai_off_then_applies_on_enable(gateway_app, fake_redis):
    room_id = _create(gateway_app, ["vi", "ja"], brse_output_mode="voice_text")
    huy = _join(gateway_app, room_id, "Huy", "vi")
    assert gateway_app.post(f"/api/rooms/{room_id}/brse/disable", headers=_auth(huy)).status_code == 200

    res = _set_mode(gateway_app, room_id, huy, "text_only")
    assert res.status_code == 200
    assert res.json()["brse_enabled"] is False
    assert res.json()["brse_output_mode"] == "text_only"

    enabled = gateway_app.post(f"/api/rooms/{room_id}/brse/enable", headers=_auth(huy)).json()
    assert enabled["brse_enabled"] is True
    assert enabled["brse_output_mode"] == "text_only"
    assert enabled["audio_routing"]["ai_audio_output_enabled"] is False


def test_late_joiner_and_rejoin_get_current_mode(gateway_app):
    room_id = _create(gateway_app, ["vi", "ja"], brse_output_mode="voice_text")
    huy = _join(gateway_app, room_id, "Huy", "vi")
    _set_mode(gateway_app, room_id, huy, "text_only")

    kenji = _join(gateway_app, room_id, "Kenji", "ja")
    assert kenji["room"]["brse_output_mode"] == "text_only"
    brse = next(p for p in kenji["snapshot"]["participants"] if p.get("is_virtual"))
    assert brse["metadata"]["brse_output_mode"] == "text_only"
    assert brse["metadata"]["publishes_audio"] is False

    snapshot = gateway_app.get(f"/api/rooms/{room_id}").json()
    assert snapshot["room"]["brse_output_mode"] == "text_only"


@pytest.mark.asyncio
async def test_concurrent_updates_are_serialized_and_converge(gateway_app, fake_redis):
    room_id = _create(gateway_app, ["vi", "ja"], brse_output_mode="voice_text")
    huy = _join(gateway_app, room_id, "Huy", "vi")
    kenji = _join(gateway_app, room_id, "Kenji", "ja")
    service = app_state.room_service

    async def change(member, mode):
        return await service.set_relay_mode(
            room_id,
            mode,
            actor_participant_id=member["participant"]["participant_id"],
            session_id=member["participant"]["session_id"],
            reason="test",
        )

    await asyncio.gather(change(huy, "text_only"), change(kenji, "voice_text"), change(huy, "text_only"))
    stored = (await service.store.get_room_state(room_id)).brse_output_mode
    events = _mode_events(fake_redis)
    # Every event is a real transition and the last one equals the stored state, so all clients converge.
    assert events[-1]["payload"]["brse_output_mode"] == stored
    for previous, current in zip(events, events[1:]):
        assert current["payload"]["previous_output_mode"] == previous["payload"]["brse_output_mode"]


# ── Runtime ────────────────────────────────────────────────────────────────

class _Publisher:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record

    def named(self, name):
        return [(args, kwargs) for call, args, kwargs in self.calls if call == name]


class _Router:
    def __init__(self, voice):
        self.output_enabled = voice
        self.voice_active = voice
        self.captured = 0
        self.enabled_calls = 0

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
        self.captured += 1
        return True

    async def flush(self):
        return True

    async def shutdown(self):
        pass

    async def enable_voice(self, *, output_mode):
        self.enabled_calls += 1
        self.output_enabled = True
        self.voice_active = True

    def disable_voice(self, *, output_mode, suppressed_reason):
        self.voice_active = False

    def audio_track_name(self):
        return "brse::pt_huy::vi::ja"

    def track_descriptor(self):
        return {"track_available": self.voice_active}


class _Client:
    def __init__(self, audio):
        self.request_audio_output = audio
        self.source_id = None
        self.audio_updates = []

    def current_response_source_id(self):
        return self.source_id

    def pending_relay_count(self):
        return 0

    async def set_audio_output(self, enabled):
        self.request_audio_output = enabled
        self.audio_updates.append(enabled)


@pytest_asyncio.fixture
async def runtime(fake_settings, monkeypatch):
    monkeypatch.setattr(room_manager_module, "_RELAY_STATE_CLEANUP_DELAY_SECONDS", 0.01)

    def build(mode):
        publisher = _Publisher()
        manager = RoomInterpreterManager(
            "rm_mode", fake_settings, publisher, room_languages=["vi", "ja"], brse_output_mode=mode
        )
        for pid, name, lang in (("pt_huy", "Huy", "vi"), ("pt_kenji", "Kenji", "ja")):
            manager.participants[pid] = {
                "participant_id": pid, "display_name": name, "language": lang,
                "status": "connected", "kind": "human", "is_virtual": False,
            }
        voice = mode == "voice_text"
        client, router = _Client(voice), _Router(voice)
        generation = manager._next_speaker_generation("pt_huy")
        manager.speaker_sources["pt_huy"] = "vi"
        manager.speaker_targets["pt_huy"] = "ja"
        manager.speaker_audiences["pt_huy"] = frozenset({"pt_kenji"})
        manager.speaker_relay_enabled["pt_huy"] = True
        manager.speaker_route_modes["pt_huy"] = "cross_language"
        manager.routers["pt_huy"] = router
        manager.clients["pt_huy"] = client
        manager._bind_client_callbacks(
            speaker_id="pt_huy", src_lang="vi", target_lang="ja", generation=generation, client=client, router=router
        )
        return manager, publisher, client, router

    return build


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0.02)


def _start_utterance(client, item, text):
    client.on_speech_started()
    client.on_speech_stopped(1500)
    client.on_input_audio_committed(item)
    client.on_transcript_complete(text)
    approval = client.approve_transcript_for_relay(text, item)
    assert approval
    client.source_id = approval["relay_source_id"]
    client.on_relay_response_starting(approval["relay_source_id"])
    return approval["relay_source_id"]


@pytest.mark.asyncio
async def test_runtime_voice_to_text_keeps_text_relay_and_stops_new_voice(runtime):
    manager, publisher, client, router = runtime("voice_text")

    await manager.set_output_mode("text_only")
    assert manager.relay_audio_enabled is False
    assert client.request_audio_output is False
    assert router.voice_active is False

    source = _start_utterance(client, "i1", "Mình sẽ deploy production tối nay nhé mọi người")
    client.on_text_delta("今夜、本番環境にデプロイします。")
    client.on_audio_delta("AAAA")  # would-be audio is not published for a text-only relay
    client.on_text_done("今夜、本番環境にデプロイします。")
    client.on_response_done(source)
    await _settle()

    assert router.captured == 0
    assert len(publisher.named("publish_relay_transcript_final")) == 1
    trace = publisher.named("publish_relay_trace")[0][0][0]
    assert trace["outcome"] == "delivered" and trace["audio_requested"] is False


@pytest.mark.asyncio
async def test_runtime_text_to_voice_enables_voice_for_new_relays(runtime):
    manager, publisher, client, router = runtime("text_only")
    assert router.output_enabled is False

    await manager.set_output_mode("voice_text")
    assert client.audio_updates == [True]
    assert router.enabled_calls == 1

    source = _start_utterance(client, "i2", "Bên em đã fix bug login rồi ạ, mọi người kiểm tra giúp")
    client.on_text_delta("ログインのバグはすでに修正しました。")
    client.on_audio_delta("AAAA")
    client.on_text_done("ログインのバグはすでに修正しました。")
    client.on_response_done(source)
    await _settle()

    assert router.captured == 1
    assert len(publisher.named("publish_relay_transcript_final")) == 1


@pytest.mark.asyncio
async def test_runtime_in_flight_voice_relay_finishes_across_switch(runtime):
    manager, publisher, client, router = runtime("voice_text")

    source = _start_utterance(client, "i3", "Mình sẽ deploy production tối nay nhé mọi người")
    client.on_text_delta("今夜、本番環境に")
    client.on_audio_delta("AAAA")
    await _settle()

    await manager.set_output_mode("text_only")  # switch lands mid-utterance
    client.on_audio_delta("BBBB")  # same response keeps its voice: no mid-sentence cut
    client.on_text_done("今夜、本番環境にデプロイします。")
    client.on_response_done(source)
    await _settle()
    assert router.captured == 2

    # The next utterance follows the new mode.
    source2 = _start_utterance(client, "i4", "Mọi người có câu hỏi gì về release không ạ")
    client.on_audio_delta("CCCC")
    client.on_text_done("リリースについて質問はありますか？")
    client.on_response_done(source2)
    await _settle()
    assert router.captured == 2
    assert len(publisher.named("publish_relay_transcript_final")) == 2


@pytest.mark.asyncio
async def test_queued_relay_follows_mode_at_send_time():
    from server.brain.realtime.interpreter_client import InterpreterRealtimeClient

    class _Ws:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(json.loads(payload))

    client = InterpreterRealtimeClient(api_key="k", src_lang="vi", tgt_lang="ja", request_audio_output=True)
    ws = _Ws()
    client._ws = ws
    queued = {"relay_source_id": "seg_q", "source_text": "xin chào mọi người", "relay_style": "normal", "queued_at": 0}

    await client.set_audio_output(False)  # mode switched while the relay waited in the queue
    await client._send_relay_response(ws, queued)

    response = [message for message in ws.sent if message["type"] == "response.create"][-1]["response"]
    assert response["output_modalities"] == ["text"]
    assert "audio" not in response
    assert any(message["type"] == "session.update" for message in ws.sent)


@pytest.mark.asyncio
async def test_daemon_applies_mode_to_running_manager(fake_settings, fake_redis):
    daemon = InterpreterDaemon(fake_settings, fake_redis)
    applied = []

    class _Manager:
        async def set_output_mode(self, mode):
            applied.append(mode)

    daemon.managers["rm_live"] = _Manager()
    await daemon._handle_gateway_event({
        "type": EventType.ROOM_RELAY_MODE_UPDATED,
        "room_id": "rm_live",
        "payload": {"brse_output_mode": "text_only"},
    })
    # No manager (AI off): ignored, the stored room mode is used on the next spawn.
    await daemon._handle_gateway_event({
        "type": EventType.ROOM_RELAY_MODE_UPDATED,
        "room_id": "rm_off",
        "payload": {"brse_output_mode": "voice_text"},
    })
    assert applied == ["text_only"]
