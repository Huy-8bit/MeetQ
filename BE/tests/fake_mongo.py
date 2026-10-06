"""Minimal in-memory Motor stand-in covering the query operators the admin services use."""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

_MISSING = object()


def _resolve(doc: Any, path: str) -> Any:
    current = doc
    parts = path.split(".")
    for position, part in enumerate(parts):
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else _MISSING
        elif isinstance(current, list):
            # Like MongoDB: "items.text" reaches into every element of an array.
            rest = ".".join(parts[position:])
            values = [_resolve(item, rest) for item in current if isinstance(item, dict)]
            values = [v for v in values if v is not _MISSING]
            return values if values else _MISSING
        else:
            return _MISSING
        if current is _MISSING:
            return _MISSING
    return current


def _compare(value: Any, op: str, operand: Any) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, datetime) and isinstance(operand, datetime):
        pass
    try:
        if op == "$gte":
            return value >= operand
        if op == "$gt":
            return value > operand
        if op == "$lte":
            return value <= operand
        if op == "$lt":
            return value < operand
    except TypeError:
        return False
    raise ValueError(op)


def _match_condition(value: Any, condition: Any) -> bool:
    if isinstance(condition, dict) and any(key.startswith("$") for key in condition):
        options = condition.get("$options", "")
        for op, operand in condition.items():
            if op == "$options":
                continue
            if op == "$nin":
                candidates = value if isinstance(value, list) else [value]
                if any(candidate in operand for candidate in candidates if candidate is not _MISSING):
                    return False
            elif op in ("$gte", "$gt", "$lte", "$lt"):
                if not _compare(value, op, operand):
                    return False
            elif op == "$in":
                candidates = value if isinstance(value, list) else [value]
                if not any(candidate in operand for candidate in candidates if candidate is not _MISSING):
                    return False
            elif op == "$ne":
                if isinstance(value, list):
                    if operand in value:
                        return False
                elif (None if value is _MISSING else value) == operand:
                    return False
            elif op == "$exists":
                if (value is not _MISSING) != bool(operand):
                    return False
            elif op == "$size":
                if not isinstance(value, list) or len(value) != operand:
                    return False
            elif op == "$regex":
                flags = re.IGNORECASE if "i" in options else 0
                candidates = value if isinstance(value, list) else [value]
                if not any(isinstance(c, str) and re.search(operand, c, flags) for c in candidates):
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if isinstance(value, list) and not isinstance(condition, list):
        return condition in value
    return (None if value is _MISSING else value) == condition


def matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, condition in query.items():
        if key == "$and":
            if not all(matches(doc, sub) for sub in condition):
                return False
        elif key == "$or":
            if not any(matches(doc, sub) for sub in condition):
                return False
        elif not _match_condition(_resolve(doc, key), condition):
            return False
    return True


def _project(doc: Dict[str, Any], projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
    result = copy.deepcopy(doc)
    if not projection:
        return result
    includes = {key for key, value in projection.items() if value and key != "_id"}
    excludes = {key for key, value in projection.items() if not value}
    if includes:
        result = {key: value for key, value in result.items() if key in includes}
    for key in excludes:
        result.pop(key, None)
    return result


class FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]], projection: Optional[Dict[str, int]]) -> None:
        self._docs = docs
        self._projection = projection
        self._skip = 0
        self._limit: Optional[int] = None

    def sort(self, key: Any, direction: int = 1) -> "FakeCursor":
        keys = key if isinstance(key, list) else [(key, direction)]
        # Stable sorts applied from the last key to the first == multi-key sort.
        for field, field_direction in reversed(keys):
            def sort_key(doc: Dict[str, Any], field: str = field) -> Any:
                value = _resolve(doc, field)
                return (value is _MISSING or value is None, value if value not in (_MISSING, None) else 0)

            self._docs = sorted(self._docs, key=sort_key, reverse=field_direction < 0)
        return self

    def skip(self, count: int) -> "FakeCursor":
        self._skip = count
        return self

    def limit(self, count: int) -> "FakeCursor":
        self._limit = count
        return self

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        docs = self._docs[self._skip :]
        cap = self._limit if self._limit else length
        if cap:
            docs = docs[:cap]
        return [_project(doc, self._projection) for doc in docs]


class _UpdateResult:
    def __init__(self, matched: int, modified: int, upserted: bool = False) -> None:
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = True if upserted else None


class _DeleteResult:
    def __init__(self, deleted: int) -> None:
        self.deleted_count = deleted


class FakeCollection:
    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Dict[str, Any]] = []

    async def insert_one(self, doc: Dict[str, Any]) -> None:
        self.docs.append(copy.deepcopy(doc))

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if matches(doc, query or {})], projection)

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        for doc in self.docs:
            if matches(doc, query):
                return _project(doc, projection)
        return None

    @staticmethod
    def _apply_update(doc: Dict[str, Any], update: Dict[str, Any]) -> None:
        for key, value in copy.deepcopy(update.get("$set", {})).items():
            doc[key] = value
        for key, value in update.get("$inc", {}).items():
            doc[key] = (doc.get(key) or 0) + value
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        for key, value in update.get("$push", {}).items():
            doc.setdefault(key, []).append(copy.deepcopy(value))
        for key, value in update.get("$addToSet", {}).items():
            items = value["$each"] if isinstance(value, dict) and "$each" in value else [value]
            current = doc.setdefault(key, [])
            for item in items:
                if item not in current:
                    current.append(copy.deepcopy(item))
        for key, value in update.get("$pull", {}).items():
            if isinstance(doc.get(key), list):
                doc[key] = [item for item in doc[key] if item != value]

    async def find_one_and_update(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any) -> Any:
        await self.update_one(query, update, upsert=upsert)
        return await self.find_one({key: value for key, value in query.items() if not key.startswith("$")})

    async def index_information(self) -> Dict[str, Any]:
        return {index.get("name", "index"): index for index in self.indexes}

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any) -> Any:
        for doc in self.docs:
            if matches(doc, query):
                self._apply_update(doc, update)
                return _UpdateResult(1, 1)
        if upsert:
            doc = {key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
            doc.update(copy.deepcopy(update.get("$setOnInsert", {})))
            self._apply_update(doc, update)
            self.docs.append(doc)
            return _UpdateResult(0, 0, upserted=True)
        return _UpdateResult(0, 0)

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any]) -> Any:
        count = 0
        for doc in self.docs:
            if matches(doc, query):
                self._apply_update(doc, update)
                count += 1
        return _UpdateResult(count, count)

    async def delete_many(self, query: Dict[str, Any]) -> Any:
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not matches(doc, query)]
        return _DeleteResult(before - len(self.docs))

    async def delete_one(self, query: Dict[str, Any]) -> Any:
        for index, doc in enumerate(self.docs):
            if matches(doc, query):
                del self.docs[index]
                return _DeleteResult(1)
        return _DeleteResult(0)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for doc in self.docs if matches(doc, query))

    async def create_index(self, keys: Any, **kwargs: Any) -> str:
        self.indexes.append({"keys": keys, **kwargs})
        return kwargs.get("name", "index")


class FakeMongoDatabase:
    def __init__(self) -> None:
        self.collections: Dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())

    async def command(self, name: str) -> Dict[str, Any]:
        return {"ok": 1.0}
