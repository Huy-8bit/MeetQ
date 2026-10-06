"""Meeting history for signed-in users ("My meetings"), full content and search.

Access is always decided on the server from the caller's stable user ID:

  * a room is in a user's history when the user created it or joined it as a signed-in
    participant (`rooms.member_user_ids`, `room_memberships`; older meetings via the
    user ID recorded at join time) — never by display name;
  * a user removed by the host loses access to that meeting;
  * nothing is returned once the meeting's retention period has ended, even before the
    cleanup worker has deleted it, so search never shows a result that can't be opened.

Every list, content and search query is scoped by `room_id` (indexed) before any text
is matched, and paginated on the server.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from server.service.archive.archive_service import recording_summary
from server.service.archive.repository import ARCHIVE_DELETED, ArchiveRepository
from server.service.archive.retention import as_utc, effective_retention_days, iso, utcnow
from server.service.meetings.search import compile_query, mongo_regex, snippet

ROOMS = "rooms"
PARTICIPANTS = "room_participants"
MESSAGES = "room_messages"
SUMMARIES = "meeting_summaries"
MEMBERSHIPS = "room_memberships"

LIST_PAGE_SIZE_MAX = 50
CONTENT_PAGE_SIZE = 50
CONTENT_PAGE_SIZE_MAX = 200
SEARCH_PAGE_SIZE = 20
GLOBAL_SEARCH_MEETING_SCOPE = 200

TRANSCRIPT_KINDS = ["source"]
LEGACY_TRANSCRIPT_KINDS = ["source", "translated"]
SOURCE_TYPE_BY_KIND = {"source": "transcript", "translated": "transcript", "relay": "relay", "chat": "chat"}
SEARCH_TEXT_FIELDS = ["text", "source_text", "translated_text", "brse_text", "translations.text"]
SUMMARY_SECTIONS = [
    ("summary_text", "Overview"),
    ("key_points", "Key points"),
    ("decisions", "Decisions"),
    ("action_items", "Action items"),
    ("risks_blockers", "Risks and blockers"),
    ("open_questions", "Open questions"),
    ("next_steps", "Next steps"),
]
LIST_FILTERS = ("all", "created", "recorded", "summary")
LIST_RANGES = {"all": None, "today": 0, "7d": 7, "30d": 30}
LANGUAGE_NAMES = {
    "vi": ("vietnamese", "tiếng việt"),
    "en": ("english",),
    "ja": ("japanese", "日本語"),
    "zh": ("chinese", "中文"),
    "ko": ("korean", "한국어"),
    "fr": ("french", "français"),
    "es": ("spanish", "español"),
}


class MeetingHistoryError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


NOT_FOUND = MeetingHistoryError(404, "meeting_not_found", "Meeting not found.")


@dataclass
class MeetingAccess:
    room_id: str
    user_id: str
    room: Dict[str, Any]
    archive: Optional[Dict[str, Any]]
    membership: Optional[Dict[str, Any]]


def encode_cursor(created_at: Optional[str], message_id: Optional[str]) -> str:
    raw = json.dumps([created_at or "", message_id or ""], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Optional[Tuple[str, str]]:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, message_id = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return str(created_at), str(message_id)
    except (ValueError, TypeError):
        raise MeetingHistoryError(422, "invalid_cursor", "Invalid page cursor.")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _not_expired(now: datetime) -> Dict[str, Any]:
    return {"$or": [{"archive_expires_at_dt": None}, {"archive_expires_at_dt": {"$gt": now}}]}


class MeetingHistoryService:
    def __init__(self, db: Any, archive_repo: Optional[ArchiveRepository]) -> None:
        self.db = db
        self.repo = archive_repo

    @property
    def enabled(self) -> bool:
        return self.db is not None

    # ── Access ──────────────────────────────────────────────────────────────

    async def access(self, room_id: str, user_id: Optional[str]) -> MeetingAccess:
        if not user_id:
            raise NOT_FOUND
        archive = await self.repo.get_archive_by_room(room_id) if self.repo is not None and self.repo.enabled else None
        if archive and archive.get("status") == ARCHIVE_DELETED:
            raise MeetingHistoryError(410, "meeting_archive_deleted", "This meeting's recording and content have been deleted.")
        membership = await self.db[MEMBERSHIPS].find_one({"room_id": room_id, "user_id": user_id})
        if membership and membership.get("removed_at"):
            raise NOT_FOUND  # removed by the host: no history access
        allowed = bool(membership) or bool(archive and user_id in (archive.get("participant_user_ids") or []))
        if not allowed:
            allowed = bool(await self.db[PARTICIPANTS].find_one({"room_id": room_id, "user_id": user_id}))
        if not allowed:
            raise NOT_FOUND  # 404, not 403: never confirm that someone else's meeting exists
        expires_at = as_utc((archive or {}).get("expires_at"))
        if expires_at and expires_at <= utcnow():
            raise MeetingHistoryError(410, "meeting_archive_expired", "This meeting's retention period has ended.")
        room = await self.db[ROOMS].find_one({"room_id": room_id}) or {"room_id": room_id}
        return MeetingAccess(room_id=room_id, user_id=user_id, room=room, archive=archive, membership=membership)

    # ── List ────────────────────────────────────────────────────────────────

    async def list_meetings(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        query: Optional[str] = None,
        filter: str = "all",
        range: str = "all",
    ) -> Dict[str, Any]:
        page_size = max(1, min(page_size, LIST_PAGE_SIZE_MAX))
        now = utcnow()
        clauses: List[Dict[str, Any]] = [{"member_user_ids": user_id}, _not_expired(now)]
        if filter == "created":
            clauses.append({"created_by_user_id": user_id})
        elif filter == "recorded":
            clauses.append({"has_recording": True})
        elif filter == "summary":
            clauses.append({"meeting_summary.status": "completed"})
        days = LIST_RANGES.get(range)
        if days is not None:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
            clauses.append({"history_sort_at_dt": {"$gte": start}})
        if query:
            regex = mongo_regex(query)
            lowered = query.lower()
            codes = [code for code, names in LANGUAGE_NAMES.items() if lowered == code or any(lowered in n for n in names)]
            options: List[Dict[str, Any]] = [
                {"title": regex},
                {"room_id": regex},
                {"participant_summaries.display_name": regex},
            ]
            if codes:
                options.append({"room_languages": {"$in": codes}})
            clauses.append({"$or": options})
        mongo_query = {"$and": clauses}
        total = await self.db[ROOMS].count_documents(mongo_query)
        rooms = (
            await self.db[ROOMS]
            .find(mongo_query)
            .sort([("history_sort_at_dt", -1), ("room_id", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .to_list(length=page_size)
        )
        # Two batched lookups for the whole page (no per-row queries).
        room_ids = [room["room_id"] for room in rooms]
        archives = {}
        if self.repo is not None and self.repo.enabled and room_ids:
            archives = {a["room_id"]: a for a in await self.repo.list_archives({"room_id": {"$in": room_ids}}, limit=len(room_ids))}
        memberships = {
            m["room_id"]: m
            for m in await self.db[MEMBERSHIPS].find({"user_id": user_id, "room_id": {"$in": room_ids}}).to_list(length=len(room_ids) or 1)
        }
        items = [self._meeting_row(room, archives.get(room["room_id"]), memberships.get(room["room_id"]), user_id) for room in rooms]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def _meeting_row(
        self,
        room: Dict[str, Any],
        archive: Optional[Dict[str, Any]],
        membership: Optional[Dict[str, Any]],
        user_id: str,
    ) -> Dict[str, Any]:
        archive = archive or {}
        terminal = bool((room.get("status_summary") or {}).get("terminal")) or bool(archive.get("ended_at"))
        started = as_utc(archive.get("meeting_started_at") or room.get("activated_at_dt") or room.get("activated_at") or room.get("created_at"))
        ended = as_utc(archive.get("ended_at") or room.get("ended_at_dt") or room.get("ended_at")) if terminal else None
        if archive.get("recording_summary"):
            recording = archive["recording_summary"]
        elif room.get("has_recording"):
            recording = {**recording_summary([]), "status": "processing" if terminal else "recording"}
        else:
            recording = recording_summary([])
        joined = room.get("joined_user_ids")
        summary_status = ((room.get("meeting_summary") or {}).get("status")) or None
        return {
            "room_id": room["room_id"],
            "archive_id": archive.get("_id"),
            "status": archive.get("status"),
            "meeting_state": "ended" if terminal else "live",
            "title": room.get("title"),
            "room_languages": room.get("room_languages") or archive.get("room_languages") or [],
            "created_at": iso(as_utc(room.get("created_at"))),
            "meeting_started_at": iso(started),
            "ended_at": iso(ended),
            "duration_seconds": round((ended - started).total_seconds()) if started and ended else None,
            "participant_count": len(joined) if joined else archive.get("participant_count") or room.get("participant_count_total"),
            "recording": recording,
            "summary_status": summary_status,
            "expires_at": iso(archive.get("expires_at")),
            "retention_days": effective_retention_days(archive) if archive.get("_id") else None,
            "my_role": (membership or {}).get("role") or "participant",
            "created_by_me": room.get("created_by_user_id") == user_id,
        }

    # ── Detail ──────────────────────────────────────────────────────────────

    async def detail(self, access: MeetingAccess) -> Dict[str, Any]:
        room_id = access.room_id
        room = access.room
        recordings = await self.repo.list_recordings(room_id) if self.repo is not None and self.repo.enabled else []
        participants = await self.participants(access)
        counts = {
            "transcript": await self.db[MESSAGES].count_documents({"room_id": room_id, "kind": {"$in": LEGACY_TRANSCRIPT_KINDS}}),
            "relay": await self.db[MESSAGES].count_documents({"room_id": room_id, "kind": "relay"}),
            "chat": await self.db[MESSAGES].count_documents({"room_id": room_id, "kind": "chat"}),
        }
        summary = await self.db[SUMMARIES].find_one({"room_id": room_id, "summary_type": "final"})
        memberships = await self.db[MEMBERSHIPS].find(
            {"room_id": room_id, "role": {"$in": ["host", "co_host"]}}
        ).to_list(length=50)
        row = self._meeting_row(room, access.archive, access.membership, access.user_id)
        overview = {
            **row,
            "brse_enabled": room.get("brse_enabled"),
            "relay_mode": room.get("brse_output_mode"),
            "password_protected": bool(room.get("password_required")),
            "host": next((m.get("display_name") for m in memberships if m.get("role") == "host"), None),
            "co_hosts": [m.get("display_name") for m in memberships if m.get("role") == "co_host" and not m.get("removed_at")],
            "summary_status": (summary or {}).get("status") or row["summary_status"],
        }
        return {
            "meeting": overview,
            "recordings": recordings,
            "participants": participants,
            "counts": counts,
            "summary": summary,
        }

    async def participants(self, access: MeetingAccess) -> List[Dict[str, Any]]:
        """One row per person (user ID; sessions without an account stay separate)."""
        room_id = access.room_id
        docs = await self.db[PARTICIPANTS].find({"room_id": room_id, "is_virtual": {"$ne": True}}).to_list(length=2000)
        memberships = {m["user_id"]: m for m in await self.db[MEMBERSHIPS].find({"room_id": room_id}).to_list(length=2000)}
        people: Dict[str, Dict[str, Any]] = {}
        for doc in sorted(docs, key=lambda d: str(d.get("first_joined_at") or d.get("last_joined_at") or "")):
            if doc.get("kind", "human") != "human":
                continue
            user_id = doc.get("user_id")
            key = user_id or doc.get("participant_id") or ""
            joined = doc.get("first_joined_at") or doc.get("last_joined_at") or doc.get("joined_at")
            left = doc.get("last_left_at") or doc.get("left_at")
            person = people.get(key)
            if person is None:
                membership = memberships.get(user_id) if user_id else None
                person = people[key] = {
                    "participant_id": doc.get("participant_id"),
                    "display_name": doc.get("display_name"),
                    "language": doc.get("language"),
                    "kind": "human",
                    # Historical role from the persisted membership; unknown for old meetings.
                    "role": (membership or {}).get("role") if membership else None,
                    "removed": bool((membership or {}).get("removed_at")),
                    "joined_at": joined,
                    "left_at": left,
                    "is_you": bool(user_id and user_id == access.user_id),
                }
            else:
                person["display_name"] = doc.get("display_name") or person["display_name"]
                person["language"] = doc.get("language") or person["language"]
                if joined and (not person["joined_at"] or str(joined) < str(person["joined_at"])):
                    person["joined_at"] = joined
                if left and (not person["left_at"] or str(left) > str(person["left_at"])):
                    person["left_at"] = left
        return list(people.values())

    # ── Content (cursor pagination, oldest first) ───────────────────────────

    async def _page(
        self,
        room_id: str,
        kinds: List[str],
        *,
        cursor: Optional[str],
        before: Optional[str],
        start: Optional[str],
        limit: int,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
        """Stable order: created_at, then message_id. `start` is inclusive (jump to a result)."""
        limit = max(1, min(limit, CONTENT_PAGE_SIZE_MAX))
        base: Dict[str, Any] = {"room_id": room_id, "kind": {"$in": kinds}}
        if before:
            created_at, message_id = decode_cursor(before)
            query = {**base, "$or": [{"created_at": {"$lt": created_at}}, {"created_at": created_at, "message_id": {"$lt": message_id}}]}
            docs = await self.db[MESSAGES].find(query).sort([("created_at", -1), ("message_id", -1)]).limit(limit + 1).to_list(length=limit + 1)
            has_more = len(docs) > limit
            docs = list(reversed(docs[:limit]))
            next_cursor = self._cursor(docs[-1]) if docs else None
            prev_cursor = self._cursor(docs[0]) if docs and has_more else None
            return docs, next_cursor, prev_cursor
        query = dict(base)
        anchor = decode_cursor(start) if start else decode_cursor(cursor)
        if anchor:
            created_at, message_id = anchor
            op = "$gte" if start else "$gt"
            query["$or"] = [{"created_at": {"$gt": created_at}}, {"created_at": created_at, "message_id": {op: message_id}}]
        docs = await self.db[MESSAGES].find(query).sort([("created_at", 1), ("message_id", 1)]).limit(limit + 1).to_list(length=limit + 1)
        has_more = len(docs) > limit
        docs = docs[:limit]
        next_cursor = self._cursor(docs[-1]) if docs and has_more else None
        prev_cursor = self._cursor(docs[0]) if docs and start else None
        return docs, next_cursor, prev_cursor

    @staticmethod
    def _cursor(doc: Dict[str, Any]) -> str:
        return encode_cursor(doc.get("created_at"), doc.get("message_id"))

    async def transcript(self, access: MeetingAccess, *, cursor=None, before=None, start=None, limit=CONTENT_PAGE_SIZE) -> Dict[str, Any]:
        room_id = access.room_id
        kinds = TRANSCRIPT_KINDS
        if not await self.db[MESSAGES].find_one({"room_id": room_id, "kind": "source"}):
            kinds = LEGACY_TRANSCRIPT_KINDS  # older meetings stored per-listener translations only
        docs, next_cursor, prev_cursor = await self._page(room_id, kinds, cursor=cursor, before=before, start=start, limit=limit)
        # Translations that were actually produced for these utterances (never generated now).
        utterance_ids = [d["utterance_id"] for d in docs if d.get("utterance_id")]
        translations: Dict[str, List[Dict[str, Any]]] = {}
        if utterance_ids and kinds == TRANSCRIPT_KINDS:
            related = await self.db[MESSAGES].find(
                {"room_id": room_id, "utterance_id": {"$in": utterance_ids}, "kind": {"$in": ["translated", "relay"]}}
            ).to_list(length=len(utterance_ids) * 8)
            for item in related:
                language = item.get("target_lang")
                text = _text(item.get("translated_text")) or _text(item.get("brse_text")) or _text(item.get("text"))
                bucket = translations.setdefault(item["utterance_id"], [])
                if text and not any(t["language"] == language and t["text"] == text for t in bucket):
                    bucket.append({"language": language, "text": text})
        items = [
            {
                "message_id": d.get("message_id"),
                "cursor": self._cursor(d),
                "kind": d.get("kind"),
                "created_at": d.get("created_at"),
                "speaker_name": d.get("display_name"),
                "language": d.get("language") or d.get("src_lang"),
                "text": _text(d.get("source_text")) or _text(d.get("text")),
                "translations": translations.get(d.get("utterance_id") or "", []),
            }
            for d in docs
        ]
        return {"items": items, "next_cursor": next_cursor, "prev_cursor": prev_cursor}

    async def relay(self, access: MeetingAccess, *, cursor=None, before=None, start=None, limit=CONTENT_PAGE_SIZE) -> Dict[str, Any]:
        docs, next_cursor, prev_cursor = await self._page(access.room_id, ["relay"], cursor=cursor, before=before, start=start, limit=limit)
        items = [
            {
                "message_id": d.get("message_id"),
                "cursor": self._cursor(d),
                "created_at": d.get("created_at"),
                "speaker_name": d.get("display_name"),
                "source_language": d.get("src_lang") or d.get("language"),
                "target_language": d.get("target_lang"),
                "source_text": _text(d.get("source_text")) or None,
                "translated_text": _text(d.get("brse_text")) or _text(d.get("translated_text")) or _text(d.get("text")),
            }
            for d in docs
        ]
        return {"items": items, "next_cursor": next_cursor, "prev_cursor": prev_cursor}

    async def chat(self, access: MeetingAccess, *, cursor=None, before=None, start=None, limit=CONTENT_PAGE_SIZE) -> Dict[str, Any]:
        docs, next_cursor, prev_cursor = await self._page(access.room_id, ["chat"], cursor=cursor, before=before, start=start, limit=limit)
        items = [
            {
                "message_id": d.get("message_id"),
                "cursor": self._cursor(d),
                "created_at": d.get("created_at"),
                "sender_name": d.get("display_name"),
                "language": d.get("language"),
                "text": _text(d.get("text")),
                # Stored with the message when it was sent; never re-translated here.
                "translations": [t for t in (d.get("translations") or []) if isinstance(t, dict) and t.get("text")],
            }
            for d in docs
        ]
        return {"items": items, "next_cursor": next_cursor, "prev_cursor": prev_cursor}

    # ── Search ──────────────────────────────────────────────────────────────

    async def search_meeting(self, access: MeetingAccess, query: str, *, page: int = 1, page_size: int = SEARCH_PAGE_SIZE) -> Dict[str, Any]:
        titles = {access.room_id: access.room.get("title")}
        return await self._search([access.room_id], titles, query, page=page, page_size=page_size)

    async def search_all(self, user_id: str, query: str, *, page: int = 1, page_size: int = SEARCH_PAGE_SIZE) -> Dict[str, Any]:
        """Content search across the user's own meetings only (most recent first)."""
        now = utcnow()
        rooms = (
            await self.db[ROOMS]
            .find({"$and": [{"member_user_ids": user_id}, _not_expired(now)]}, {"room_id": 1, "title": 1})
            .sort([("history_sort_at_dt", -1), ("room_id", 1)])
            .limit(GLOBAL_SEARCH_MEETING_SCOPE)
            .to_list(length=GLOBAL_SEARCH_MEETING_SCOPE)
        )
        # Removed users are pulled from member_user_ids; double-check against memberships.
        removed = {
            m["room_id"]
            for m in await self.db[MEMBERSHIPS].find({"user_id": user_id, "removed_at": {"$ne": None}}).to_list(length=500)
        }
        titles = {room["room_id"]: room.get("title") for room in rooms if room["room_id"] not in removed}
        if not titles:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "query": query}
        return await self._search(list(titles), titles, query, page=page, page_size=page_size)

    async def _search(
        self,
        room_ids: List[str],
        titles: Dict[str, Optional[str]],
        query: str,
        *,
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        page_size = max(1, min(page_size, 50))
        pattern = compile_query(query)
        regex = mongo_regex(query)

        summary_hits: List[Dict[str, Any]] = []
        summary_or = [{field: regex} for field, _label in SUMMARY_SECTIONS] + [{"participant_summary.summary": regex}]
        for summary in await self.db[SUMMARIES].find(
            {"room_id": {"$in": room_ids}, "summary_type": "final", "status": "completed", "$or": summary_or}
        ).to_list(length=len(room_ids)):
            summary_hits.extend(self._summary_hits(summary, pattern, titles))

        message_query = {
            "room_id": {"$in": room_ids},
            "kind": {"$in": ["source", "translated", "relay", "chat"]},
            "$or": [{field: regex} for field in SEARCH_TEXT_FIELDS],
        }
        message_total = await self.db[MESSAGES].count_documents(message_query)
        total = len(summary_hits) + message_total
        offset = (page - 1) * page_size
        items = summary_hits[offset : offset + page_size]
        remaining = page_size - len(items)
        if remaining > 0:
            skip = max(0, offset - len(summary_hits))
            docs = (
                await self.db[MESSAGES]
                .find(message_query)
                .sort([("created_at", 1), ("message_id", 1)])
                .skip(skip)
                .limit(remaining)
                .to_list(length=remaining)
            )
            items.extend(await self._message_hits(docs, pattern, titles))
        return {"items": items, "total": total, "page": page, "page_size": page_size, "query": query}

    def _summary_hits(self, summary: Dict[str, Any], pattern, titles: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
        hits = []
        sections: List[Tuple[str, Any]] = [(label, summary.get(field)) for field, label in SUMMARY_SECTIONS]
        sections.append(("Participants", [p.get("summary") for p in summary.get("participant_summary") or [] if isinstance(p, dict)]))
        for label, value in sections:
            texts = value if isinstance(value, list) else [value]
            for text in texts:
                if isinstance(text, dict):
                    text = text.get("text")
                if not isinstance(text, str) or not pattern.search(text):
                    continue
                snip, highlights = snippet(text, pattern)
                hits.append(
                    {
                        "meeting_id": summary["room_id"],
                        "meeting_title": titles.get(summary["room_id"]),
                        "source_type": "summary",
                        "section": label,
                        "timestamp": iso(as_utc(summary.get("generated_at"))) or summary.get("generated_at"),
                        "speaker": None,
                        "language": summary.get("summary_language"),
                        "text": snip,
                        "highlights": highlights,
                        "source_item_id": summary.get("summary_id"),
                        "cursor": None,
                    }
                )
                break  # one hit per section is enough
        return hits

    async def _message_hits(self, docs: List[Dict[str, Any]], pattern, titles: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
        # A match in a per-listener translation jumps to its spoken utterance in Transcript.
        utterances = {d["utterance_id"] for d in docs if d.get("kind") == "translated" and d.get("utterance_id")}
        sources: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if utterances:
            for source in await self.db[MESSAGES].find(
                {"room_id": {"$in": list({d["room_id"] for d in docs})}, "kind": "source", "utterance_id": {"$in": list(utterances)}}
            ).to_list(length=len(utterances) * 2):
                sources[(source["room_id"], source["utterance_id"])] = source
        hits = []
        for doc in docs:
            matched = ""
            for field in ("text", "source_text", "translated_text", "brse_text"):
                if isinstance(doc.get(field), str) and pattern.search(doc[field]):
                    matched = doc[field]
                    break
            if not matched:
                matched = next(
                    (t.get("text") for t in doc.get("translations") or [] if isinstance(t, dict) and pattern.search(t.get("text") or "")),
                    "",
                )
            snip, highlights = snippet(matched, pattern)
            anchor = doc
            if doc.get("kind") == "translated":
                anchor = sources.get((doc["room_id"], doc.get("utterance_id") or ""), doc)
            hits.append(
                {
                    "meeting_id": doc["room_id"],
                    "meeting_title": titles.get(doc["room_id"]),
                    "source_type": SOURCE_TYPE_BY_KIND.get(doc.get("kind"), "transcript"),
                    "section": None,
                    "timestamp": doc.get("created_at"),
                    "speaker": doc.get("display_name"),
                    "language": doc.get("language") or doc.get("src_lang"),
                    "text": snip,
                    "highlights": highlights,
                    "source_item_id": anchor.get("message_id"),
                    "cursor": self._cursor(anchor),
                }
            )
        return hits


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if k != "_id" and not k.endswith("_dt")}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return iso(value)
    return value
