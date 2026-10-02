from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterable, Callable, Dict, Optional

from server.service.livekit_lines.config import LineIsolationConfig
from server.service.livekit_lines.crosstalk import CrosstalkArbiter
from server.service.livekit_lines.speaker_line import SpeakerLine, SpeakerLineStream

logger = logging.getLogger(__name__)


class SpeakerLineHub:
    """Owns every isolated speaker line of one LiveKit room.

    Lines live as long as the participant's LiveKit mic subscription, not as
    long as an interpreter session, so the arbiter keeps hearing a speaker even
    while that speaker has no active realtime session (e.g. unsupported route).
    """

    def __init__(
        self,
        room_id: str,
        config: Optional[LineIsolationConfig] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.room_id = room_id
        self.config = config or LineIsolationConfig()
        self.arbiter = CrosstalkArbiter(self.config)
        self._clock = clock
        self._lines: Dict[str, SpeakerLine] = {}

    @property
    def line_ids(self) -> list[str]:
        return list(self._lines)

    def get(self, line_id: str) -> Optional[SpeakerLine]:
        return self._lines.get(line_id)

    def open_line(self, line_id: str, source: AsyncIterable[Any]) -> SpeakerLineStream:
        previous = self._lines.pop(line_id, None)
        if previous is not None:
            asyncio.get_running_loop().create_task(previous.aclose())

        line = SpeakerLine(
            line_id,
            source,
            self.arbiter,
            self.config,
            room_id=self.room_id,
            clock=self._clock,
            on_closed=self._forget,
        )
        self._lines[line_id] = line
        line.start()
        logger.info(
            "Speaker line opened room=%s line=%s active_lines=%d",
            self.room_id,
            line_id,
            len(self._lines),
        )
        return line.open_stream()

    async def close_line(self, line_id: str) -> None:
        line = self._lines.pop(line_id, None)
        if line is None:
            return
        await line.aclose()
        logger.info(
            "Speaker line closed room=%s line=%s stats=%s",
            self.room_id,
            line_id,
            line.stats_snapshot(),
        )

    async def close_all(self) -> None:
        for line_id in list(self._lines):
            await self.close_line(line_id)

    def stats_snapshot(self) -> list[dict[str, Any]]:
        return [line.stats_snapshot() for line in self._lines.values()]

    def _forget(self, line: SpeakerLine) -> None:
        if self._lines.get(line.line_id) is line:
            self._lines.pop(line.line_id, None)
