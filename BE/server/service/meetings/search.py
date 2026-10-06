"""Keyword search helpers for meeting history.

This is plain keyword search: a case-insensitive substring match on the stored text
(Unicode NFC), not semantic search and not language-aware stemming. Substring matching
is deliberate: Japanese, Chinese and Korean have no spaces between words, so word-based
full-text indexes (MongoDB `$text`) would miss most of their matches, and English
stemming would mangle Vietnamese. Every query is scoped by `room_id` first (indexed),
so only meetings the user may read are ever scanned.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

SEARCH_MIN_LENGTH = 2
SEARCH_MAX_LENGTH = 100
SNIPPET_CONTEXT = 70


class SearchQueryError(ValueError):
    pass


def _is_wide(text: str) -> bool:
    # CJK ideographs, kana, hangul: one character is already a meaningful word.
    return any(ord(ch) >= 0x2E80 for ch in text)


def normalize_query(raw: Optional[str]) -> str:
    query = unicodedata.normalize("NFC", " ".join((raw or "").split()))
    if len(query) > SEARCH_MAX_LENGTH:
        raise SearchQueryError(f"Search terms must be at most {SEARCH_MAX_LENGTH} characters.")
    if len(query) < SEARCH_MIN_LENGTH and not (query and _is_wide(query)):
        raise SearchQueryError(f"Enter at least {SEARCH_MIN_LENGTH} characters to search.")
    return query


def mongo_regex(query: str) -> dict:
    return {"$regex": re.escape(query), "$options": "i"}


def compile_query(query: str) -> "re.Pattern[str]":
    return re.compile(re.escape(query), re.IGNORECASE)


def snippet(text: str, pattern: "re.Pattern[str]") -> Tuple[str, List[List[int]]]:
    """A short window around the first match plus [start, end] offsets of every match in it.

    Offsets are for the returned snippet, so clients render highlights as plain text
    segments (no HTML).
    """
    text = unicodedata.normalize("NFC", text or "")
    first = pattern.search(text)
    if first is None:
        cut = text[: SNIPPET_CONTEXT * 2]
        return (cut + ("…" if len(text) > len(cut) else "")), []
    start = max(0, first.start() - SNIPPET_CONTEXT)
    end = min(len(text), first.end() + SNIPPET_CONTEXT)
    if start > 0:
        space = text.find(" ", start, first.start())
        start = space + 1 if 0 <= space < first.start() else start
    window = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    offset = len(prefix)
    highlights = [[m.start() + offset, m.end() + offset] for m in pattern.finditer(window)]
    return prefix + window + suffix, highlights
