"""Sequential monitoring loop with cycle isolation and no overlapping runs."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class MonitorRunner:
    def __init__(self, cycle: Callable[[], Awaitable[None]], interval_seconds: float, max_cycles: int | None = None) -> None:
        self._cycle = cycle
        self._interval_seconds = interval_seconds
        self._max_cycles = max_cycles
        self._lock = asyncio.Lock()

    async def run(self) -> None:
        completed = 0
        while self._max_cycles is None or completed < self._max_cycles:
            try:
                async with self._lock:
                    await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Monitoring cycle failed: %s", exc)
            completed += 1
            if self._max_cycles is not None and completed >= self._max_cycles:
                break
            logger.info("Cycle finished; next run in %.0f seconds", self._interval_seconds)
            await asyncio.sleep(self._interval_seconds)
