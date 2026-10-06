"""My meetings, full history and keyword search: user-scoped by stable user ID, paginated,
retention-aware. Nothing here may ever return another user's meeting content."""
import asyncio
from datetime import timedelta

import pytest

from server.models import RoomState
from server.service.archive.archive_service import ArchiveService
from server.service.archive.repository import ArchiveRepository
from server.service.archive.retention import utcnow
from server.service.auth.cookies import USER_COOKIE
from server.service.auth.sessions import USER_REALM, SessionStore
from server.service.gateway.app_state import app_state
from server.service.meetings.search import SearchQueryError, normalize_query, snippet, compile_query
from server.service.meetings.service import MeetingHistoryError, MeetingHistoryService, decode_cursor
from server.service.persistence.room_history import MongoRoomHistoryRepository
from tests.fake_mongo import FakeMongoDatabase


def _run(coro):
    return asyncio.run(coro)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class World:
    """A Mongo with meetings M1, M2 (user A) and M3 (user B), written through the real repositories."""

    def __init__(self):
        self.db = FakeMongoDatabase()
        self.history = MongoRoomHistoryRepository(self.db)
        self.repo = ArchiveRepository(self.db, default_retention_days=7)
        self.service = MeetingHistoryService(self.db, self.repo)
        self.archives = ArchiveService(_Settings(), self.repo, None, room_is_live=_never_live)

    async def meeting(self, room_id, *, creator, members=(), title=None, ended_ago=timedelta(hours=1), messages=()):
        ended = utcnow() - ended_ago
        created = ended - timedelta(minutes=30)
        room = RoomState(
            room_id=room_id,
            state="created",
            created_at=_iso(created),
            expires_at=_iso(created + timedelta(minutes=30)),
            room_languages=["vi", "ja"],
            title=title,
        )
        await self.history.persist_room_created(room, created_by_user_id=creator)
        for index, (user_id, name) in enumerate(members):
            participant = {
                "participant_id": f"pt_{room_id}_{index}",
                "session_id": f"ses_{index}",
                "display_name": name,
                "language": "vi",
                "kind": "human",
                "joined_at": _iso(created + timedelta(minutes=index)),
            }
            await self.history.persist_participant_join(
                room, participant, current_human_count=index + 1, client_meta=None, user_id=user_id
            )
            await self.history.persist_membership(
                room_id, user_id, display_name=name, language="vi", joined_at=_iso(created + timedelta(minutes=index))
            )
        for doc in messages:
            await self.db["room_messages"].insert_one({"room_id": room_id, **doc})
        await self.db["rooms"].update_one(
            {"room_id": room_id},
            {
                "$set": {
                    "ended_at": _iso(ended),
                    "ended_at_dt": ended,
                    "history_sort_at_dt": ended,
                    "status_summary": {"state": "empty", "terminal": True, "reason": "empty"},
                }
            },
        )


class _Settings:
    meeting_archive_prefix = "meetings"
    deployment_environment = "test"
    archive_summary_wait_seconds = 0


async def _never_live(room_id):
    return False


def _msg(message_id, kind, minute, text, **extra):
    created = _iso(utcnow() - timedelta(hours=2) + timedelta(minutes=minute))
    return {"message_id": message_id, "kind": kind, "created_at": created, "text": text, "display_name": "Huy", **extra}


@pytest.fixture
def world():
    w = World()
    _run(
        w.meeting(
            "rm_m1",
            creator="usr_a",
            members=[("usr_a", "Huy"), ("usr_c", "Kenji")],
            title="Vikki Lending Weekly",
            messages=[
                _msg("s1", "source", 1, "Chúng ta sẽ deploy production tối nay.", utterance_id="u1", source_text="Chúng ta sẽ deploy production tối nay.", language="vi"),
                _msg("t1", "translated", 1.1, "今夜、本番環境にデプロイします。", utterance_id="u1", translated_text="今夜、本番環境にデプロイします。", target_lang="ja"),
                _msg("r1", "relay", 1.2, "今夜、本番環境にデプロイします。", utterance_id="u1", brse_text="今夜、本番環境にデプロイします。", source_text="Chúng ta sẽ deploy production tối nay.", src_lang="vi", target_lang="ja"),
                _msg("c1", "chat", 2, "Production deployment cần chạy sau test.", translations=[{"language": "ja", "text": "本番デプロイはテストの後。"}]),
            ],
        )
    )
    _run(w.meeting("rm_m2", creator="usr_b", members=[("usr_a", "Huy")], title="API Design Review", ended_ago=timedelta(days=2)))
    _run(
        w.meeting(
            "rm_m3",
            creator="usr_b",
            members=[("usr_b", "Huy")],  # same display name as A: must not matter
            title="Secret production plan",
            messages=[_msg("x1", "source", 1, "production secrets for B only", language="vi")],
        )
    )
    _run(
        w.db["meeting_summaries"].insert_one(
            {
                "room_id": "rm_m1",
                "summary_type": "final",
                "status": "completed",
                "summary_id": "sum_1",
                "summary_text": "Production deployment remains dependent on testing.",
                "decisions": ["Deploy tonight"],
            }
        )
    )
    _run(w.db["rooms"].update_one({"room_id": "rm_m1"}, {"$set": {"meeting_summary": {"status": "completed"}, "has_recording": True}}))
    return w


# ── My meetings ────────────────────────────────────────────────────────────


def test_my_meetings_only_lists_created_or_joined_meetings(world):
    a = _run(world.service.list_meetings("usr_a"))
    assert [m["room_id"] for m in a["items"]] == ["rm_m1", "rm_m2"]  # most recent end first
    assert a["total"] == 2
    b = _run(world.service.list_meetings("usr_b"))
    assert {m["room_id"] for m in b["items"]} == {"rm_m2", "rm_m3"}
    row = a["items"][0]
    assert row["title"] == "Vikki Lending Weekly" and row["my_role"] == "host" and row["created_by_me"] is True
    assert row["participant_count"] == 2 and row["summary_status"] == "completed" and row["meeting_state"] == "ended"
    assert a["items"][1]["my_role"] == "participant" and a["items"][1]["created_by_me"] is False


def test_my_meetings_filters_search_and_pagination(world):
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", filter="created"))["items"]] == ["rm_m1"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", filter="recorded"))["items"]] == ["rm_m1"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", filter="summary"))["items"]] == ["rm_m1"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", range="today"))["items"]] == ["rm_m1"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", query="api design"))["items"]] == ["rm_m2"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", query="kenji"))["items"]] == ["rm_m1"]
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a", query="rm_m2"))["items"]] == ["rm_m2"]
    # A matches B's title only if A is a member: "Secret production plan" never shows up.
    assert _run(world.service.list_meetings("usr_a", query="secret"))["items"] == []
    page1 = _run(world.service.list_meetings("usr_a", page=1, page_size=1))
    page2 = _run(world.service.list_meetings("usr_a", page=2, page_size=1))
    assert page1["total"] == 2 and [page1["items"][0]["room_id"], page2["items"][0]["room_id"]] == ["rm_m1", "rm_m2"]


def test_meeting_detail_is_not_reachable_by_other_users(world):
    access = _run(world.service.access("rm_m1", "usr_a"))
    detail = _run(world.service.detail(access))
    assert detail["meeting"]["host"] == "Huy" and detail["counts"]["chat"] == 1
    people = {p["display_name"]: p for p in detail["participants"]}
    assert people["Huy"]["role"] == "host" and people["Huy"]["is_you"] is True
    assert people["Kenji"]["role"] == "participant"
    with pytest.raises(MeetingHistoryError) as exc:
        _run(world.service.access("rm_m3", "usr_a"))
    assert exc.value.status_code == 404
    with pytest.raises(MeetingHistoryError):
        _run(world.service.access("rm_m1", None))


def test_removed_user_loses_history_access(world):
    _run(world.history.persist_membership_removed("rm_m1", "usr_c", removed_at=_iso(utcnow()), removed_by_user_id="usr_a"))
    with pytest.raises(MeetingHistoryError):
        _run(world.service.access("rm_m1", "usr_c"))
    assert _run(world.service.list_meetings("usr_c"))["items"] == []


# ── Full transcript ────────────────────────────────────────────────────────


def test_full_transcript_pages_without_gaps_or_duplicates():
    w = World()
    created = utcnow() - timedelta(hours=3)
    messages = []
    for index in range(100):
        # Pairs share a timestamp: the message ID breaks the tie.
        stamp = _iso(created + timedelta(seconds=index // 2))
        messages.append({"message_id": f"m{index:03d}", "kind": "source", "created_at": stamp, "text": f"line {index}", "utterance_id": f"u{index}"})
    messages.append({"message_id": "t005", "kind": "translated", "created_at": _iso(created + timedelta(seconds=3)), "translated_text": "dòng 5", "target_lang": "vi", "utterance_id": "u5"})
    _run(w.meeting("rm_long", creator="usr_a", members=[("usr_a", "Huy")], messages=messages))
    access = _run(w.service.access("rm_long", "usr_a"))
    seen, cursor = [], None
    while True:
        page = _run(w.service.transcript(access, cursor=cursor, limit=30))
        seen.extend(item["message_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [f"m{index:03d}" for index in range(100)]  # all 100, in order, once each
    first = _run(w.service.transcript(access, limit=10))["items"]
    assert next(i for i in first if i["message_id"] == "m005")["translations"] == [{"language": "vi", "text": "dòng 5"}]
    # Jump to an item, then page backwards from it.
    jump = _run(w.service.transcript(access, start=first[6]["cursor"], limit=5))
    assert [i["message_id"] for i in jump["items"]] == ["m006", "m007", "m008", "m009", "m010"]
    back = _run(w.service.transcript(access, before=jump["prev_cursor"], limit=3))
    assert [i["message_id"] for i in back["items"]] == ["m003", "m004", "m005"]
    with pytest.raises(MeetingHistoryError):
        decode_cursor("not-a-cursor")


def test_relay_and_chat_history_keep_stored_translations(world):
    access = _run(world.service.access("rm_m1", "usr_a"))
    relay = _run(world.service.relay(access))["items"]
    assert relay == [
        {
            "message_id": "r1",
            "cursor": relay[0]["cursor"],
            "created_at": relay[0]["created_at"],
            "speaker_name": "Huy",
            "source_language": "vi",
            "target_language": "ja",
            "source_text": "Chúng ta sẽ deploy production tối nay.",
            "translated_text": "今夜、本番環境にデプロイします。",
        }
    ]
    chat = _run(world.service.chat(access))["items"]
    assert chat[0]["translations"] == [{"language": "ja", "text": "本番デプロイはテストの後。"}]


# ── Search ─────────────────────────────────────────────────────────────────


def test_search_this_meeting_covers_every_source_type(world):
    access = _run(world.service.access("rm_m1", "usr_a"))
    result = _run(world.service.search_meeting(access, "production"))
    types = [item["source_type"] for item in result["items"]]
    assert types[0] == "summary" and {"transcript", "relay", "chat", "summary"} <= set(types)
    transcript = next(i for i in result["items"] if i["source_type"] == "transcript")
    start, end = transcript["highlights"][0]
    assert transcript["text"][start:end].lower() == "production"
    assert transcript["source_item_id"] == "s1" and transcript["cursor"]
    # Japanese has no spaces: substring search still finds it (also inside a translation).
    jp = _run(world.service.search_meeting(access, "本番"))
    assert {i["source_type"] for i in jp["items"]} >= {"transcript", "relay", "chat"}
    hit = next(i for i in jp["items"] if i["source_type"] == "transcript")
    assert hit["source_item_id"] == "s1"  # translated hit jumps to the spoken utterance


def test_global_search_never_leaks_other_users_meetings(world):
    a = _run(world.service.search_all("usr_a", "production"))
    assert a["total"] > 0 and {i["meeting_id"] for i in a["items"]} == {"rm_m1"}
    assert "secrets" not in str(a)
    b = _run(world.service.search_all("usr_b", "production"))
    assert {i["meeting_id"] for i in b["items"]} == {"rm_m3"}
    assert _run(world.service.search_all("usr_nobody", "production"))["items"] == []


def test_search_pagination():
    w = World()
    messages = [{"message_id": f"m{i:02d}", "kind": "chat", "created_at": _iso(utcnow() - timedelta(minutes=60 - i)), "text": f"deploy step {i}"} for i in range(45)]
    _run(w.meeting("rm_many", creator="usr_a", members=[("usr_a", "Huy")], messages=messages))
    access = _run(w.service.access("rm_many", "usr_a"))
    pages = [_run(w.service.search_meeting(access, "deploy", page=n, page_size=20)) for n in (1, 2, 3)]
    ids = [i["source_item_id"] for p in pages for i in p["items"]]
    assert pages[0]["total"] == 45 and len(ids) == 45 and len(set(ids)) == 45
    assert [len(p["items"]) for p in pages] == [20, 20, 5]


def test_search_query_rules():
    assert normalize_query("  deploy   prod ") == "deploy prod"
    assert normalize_query("本") == "本"  # one CJK character is a word
    with pytest.raises(SearchQueryError):
        normalize_query("a")
    with pytest.raises(SearchQueryError):
        normalize_query("x" * 101)
    # Regex characters are literal; highlights are offsets, never HTML.
    text, highlights = snippet("cost is $5 (est.)", compile_query("$5 (est"))
    assert highlights and text[highlights[0][0]:highlights[0][1]] == "$5 (est"


# ── Retention ──────────────────────────────────────────────────────────────


def test_expired_meeting_disappears_from_history_and_search(world):
    room = _run(world.db["rooms"].find_one({"room_id": "rm_m1"}))
    _run(world.archives.build_archive(room))
    archive = _run(world.repo.get_archive_by_room("rm_m1"))
    assert "usr_a" in archive["participant_user_ids"]
    _run(world.repo.update_archive(archive["_id"], {"expires_at": utcnow() - timedelta(minutes=1)}))
    # Expired but not yet cleaned up: already hidden everywhere.
    assert [m["room_id"] for m in _run(world.service.list_meetings("usr_a"))["items"]] == ["rm_m2"]
    assert _run(world.service.search_all("usr_a", "production"))["items"] == []
    with pytest.raises(MeetingHistoryError) as exc:
        _run(world.service.access("rm_m1", "usr_a"))
    assert exc.value.status_code == 410
    # After cleanup every piece of content (and the membership) is gone for real.
    _run(world.archives.cleanup_expired())
    for collection in ("room_messages", "meeting_summaries", "room_participants", "room_memberships", "rooms"):
        assert _run(world.db[collection].count_documents({"room_id": "rm_m1"})) == 0
    with pytest.raises(MeetingHistoryError) as exc:
        _run(world.service.access("rm_m1", "usr_a"))
    assert exc.value.status_code == 410 and exc.value.code == "meeting_archive_deleted"


# ── Persistence & migration ────────────────────────────────────────────────


def test_creator_membership_is_host_and_legacy_backfill_never_guesses():
    w = World()
    room = RoomState(room_id="rm_new", state="created", created_at=_iso(utcnow()), expires_at=_iso(utcnow()), title="Kickoff")
    _run(w.history.persist_room_created(room, created_by_user_id="usr_a"))
    membership = _run(w.db["room_memberships"].find_one({"room_id": "rm_new", "user_id": "usr_a"}))
    assert membership["role"] == "host" and membership["is_creator"] is True
    doc = _run(w.db["rooms"].find_one({"room_id": "rm_new"}))
    assert doc["created_by_user_id"] == "usr_a" and doc["member_user_ids"] == ["usr_a"] and doc["title"] == "Kickoff"

    # Old meeting: one signed-in participant, one guest with only a display name.
    _run(w.db["rooms"].insert_one({"room_id": "rm_old", "created_at": "2026-01-01T00:00:00Z", "ended_at_dt": utcnow() - timedelta(days=1)}))
    _run(w.db["room_participants"].insert_one({"room_id": "rm_old", "participant_id": "p1", "display_name": "Huy", "user_id": "usr_a", "first_joined_at": "2026-01-01T00:01:00Z"}))
    _run(w.db["room_participants"].insert_one({"room_id": "rm_old", "participant_id": "p2", "display_name": "Huy"}))
    _run(w.history.migrate_membership_history())
    old = _run(w.db["rooms"].find_one({"room_id": "rm_old"}))
    assert old["member_user_ids"] == ["usr_a"] and old["history_sort_at_dt"]
    assert "created_by_user_id" not in old  # nobody is made host of an old room
    memberships = _run(w.db["room_memberships"].find({"room_id": "rm_old"}).to_list(length=10))
    assert [(m["user_id"], m["role"]) for m in memberships] == [("usr_a", "participant")]
    assert _run(w.history.migrate_membership_history()) == 0  # runs once


# ── HTTP wiring ────────────────────────────────────────────────────────────


@pytest.fixture
def http(gateway_app, fake_settings, fake_redis, world):
    fake_settings.user_auth_required = True
    app_state.archive_repo = world.repo
    app_state.room_history = None

    def sign_in(user_id):
        token, _ = _run(SessionStore(fake_redis).create(USER_REALM, {"user": {"id": user_id, "name": user_id}}, 3600))
        gateway_app.cookies.set(USER_COOKIE, token)

    yield gateway_app, sign_in
    gateway_app.cookies.clear()
    app_state.archive_repo = None
    fake_settings.user_auth_required = False


def test_history_endpoints_are_user_scoped(http):
    client, sign_in = http
    assert client.get("/api/meetings").status_code == 401
    sign_in("usr_a")
    listing = client.get("/api/meetings?filter=created").json()
    assert [m["room_id"] for m in listing["items"]] == ["rm_m1"]
    assert client.get("/api/meetings?filter=bogus").status_code == 422
    assert client.get("/api/meetings/rm_m3").status_code == 404
    assert client.get("/api/meetings/rm_m3/transcript").status_code == 404
    assert client.get("/api/meetings/rm_m3/search?q=production").status_code == 404
    transcript = client.get("/api/meetings/rm_m1/transcript").json()
    assert transcript["items"][0]["translations"][0]["language"] == "ja"
    found = client.get("/api/meetings/search?q=production").json()
    assert found["total"] > 0 and {i["meeting_id"] for i in found["items"]} == {"rm_m1"}
    assert client.get("/api/meetings/rm_m1/search?q=a").status_code == 422
    participants = client.get("/api/meetings/rm_m1/participants").json()["items"]
    assert {p["display_name"] for p in participants} == {"Huy", "Kenji"}
    assert client.get("/api/meetings/rm_m1/summary").json()["summary"]["status"] == "completed"
    assert client.get("/api/meetings/rm_m1/recordings").json()["items"] == []
