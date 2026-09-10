"""Lifecycle controller for the local admin monitor task."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class MonitorStatus(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class MonitorController:
    """Run one cancellable sequential monitor loop inside the admin process."""

    def __init__(self, cycle: Callable[[], Awaitable[None]], interval_seconds: Callable[[], float]) -> None:
        self._cycle = cycle
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self.status = MonitorStatus.STOPPED
        self.started_at: datetime | None = None
        self.last_cycle_started: datetime | None = None
        self.last_cycle_finished: datetime | None = None
        self.last_cycle_duration: float | None = None
        self.next_cycle_at: datetime | None = None
        self.cycles_completed = 0
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def snapshot(self) -> dict[str, object | None]:
        iso = lambda value: value.isoformat() if value else None
        return {"status": self.status, "started_at": iso(self.started_at), "last_cycle_started": iso(self.last_cycle_started), "last_cycle_finished": iso(self.last_cycle_finished), "last_cycle_duration": self.last_cycle_duration, "next_cycle_at": iso(self.next_cycle_at), "cycles_completed": self.cycles_completed, "last_error": self.last_error}

    async def start(self) -> bool:
        if self.running:
            return False
        self.status = MonitorStatus.STARTING
        self.started_at = datetime.now(timezone.utc)
        self.last_error = None
        self._task = asyncio.create_task(self._run(), name="flip-finder-monitor")
        return True

    async def stop(self) -> bool:
        if not self.running:
            self.status = MonitorStatus.STOPPED
            return False
        self.status = MonitorStatus.STOPPING
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self.next_cycle_at = None
        self.status = MonitorStatus.STOPPED
        return True

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _run(self) -> None:
        self.status = MonitorStatus.RUNNING
        try:
            while True:
                self.last_cycle_started = datetime.now(timezone.utc)
                self.next_cycle_at = None
                try:
                    await self._cycle()
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = str(exc)[:500]
                    self.status = MonitorStatus.ERROR
                finally:
                    self.last_cycle_finished = datetime.now(timezone.utc)
                    self.last_cycle_duration = (self.last_cycle_finished - self.last_cycle_started).total_seconds()
                    self.cycles_completed += 1
                if self.status == MonitorStatus.ERROR:
                    self.status = MonitorStatus.RUNNING
                delay = max(1.0, self._interval_seconds())
                self.next_cycle_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
