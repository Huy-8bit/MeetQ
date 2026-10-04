"""Admin portal sign-in helpers.

Admin sessions are opaque server-side sessions behind the HttpOnly
``meetq_admin_session`` cookie (server/service/auth). This module keeps the
in-memory failed-login limiter shared by the sign-in endpoints.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

LOGIN_MAX_FAILURES = 10
LOGIN_FAILURE_WINDOW_SECONDS = 600


class LoginRateLimiter:
    """In-memory failed-login limiter per client address (single gateway process)."""

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        window_seconds: int = LOGIN_FAILURE_WINDOW_SECONDS,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> Deque[float]:
        bucket = self._failures[key]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        return bucket

    def is_blocked(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        return len(self._prune(key, now)) >= self.max_failures

    def record_failure(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()
