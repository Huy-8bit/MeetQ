import pytest
import time
from datetime import datetime, timezone
from server.service.gateway.room_store import RoomStore
from server.models import RoomState, ParticipantState, TranscriptEvent

@pytest.mark.asyncio
async def test_room_lifecycle(fake_redis):
    store = RoomStore(fake_redis)
    
    room_id = "rm_123"
    now = datetime.now(timezone.utc).isoformat()
    room = RoomState(
        room_id=room_id,
        state="created",
        created_at=now,
        expires_at=now,
        participant_limit=8,
        supported_languages=["vi", "en"]
    )
    
    # Test Create
    await store.create_room(room)
    
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot is not None
    assert snapshot.room.state == "created"
    assert snapshot.room.participant_count == 0
    
    # Test Add Participant
    part = ParticipantState(
        participant_id="pt_1",
        session_id="ses_1",
        display_name="User 1",
        language="vi",
        status="connected",
        joined_at=now
    )
    await store.add_participant(room_id, part)
    
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot.room.participant_count == 1
    assert len(snapshot.participants) == 1
    assert snapshot.participants[0].status == "connected"
    
    # Test update participant
    await store.update_participant(room_id, "pt_1", {"language": "en"})
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot.participants[0].language == "en"
    
    # Test leave
    await store.mark_participant_left(room_id, "pt_1", now)
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot.participants == []
    assert snapshot.room.participant_count == 0  # Since count checks non-left participants
    
    # Test mark empty
    await store.mark_room_empty(room_id)
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot.room.state == "empty"
    
    # Test delete
    await store.delete_room(room_id)
    snapshot = await store.get_room_snapshot(room_id)
    assert snapshot is None

@pytest.mark.asyncio
async def test_transcript_trim(fake_redis):
    store = RoomStore(fake_redis, transcript_limit=2)
    room_id = "rm_123"
    
    now = datetime.now(timezone.utc).isoformat()
    room = RoomState(
        room_id=room_id,
        state="created",
        created_at=now,
        expires_at=now,
        participant_limit=8,
        supported_languages=["vi", "en"]
    )
    await store.create_room(room)
    
    # Add 3 transcripts
    for i in range(3):
        t = TranscriptEvent(
            transcript_id=f"tr_{i}",
            speaker_id="pt_1",
            speaker_display_name="U1",
            src_lang="vi",
            source_text=f"test {i}",
            created_at=now
        )
        await store.append_transcript(room_id, t)
        
    snapshot = await store.get_room_snapshot(room_id)
    # Since limit is 2, the oldest one (tr_0) should be gone
    assert len(snapshot.recent_transcripts) == 2
    assert snapshot.recent_transcripts[0].transcript_id == "tr_1"
    assert snapshot.recent_transcripts[1].transcript_id == "tr_2"
