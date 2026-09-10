import asyncio
import pytest
from app.services.monitor import MonitorRunner


@pytest.mark.asyncio
async def test_monitor_runs_bounded_cycles_sequentially():
    active = 0; maximum = 0; calls = 0
    async def cycle():
        nonlocal active, maximum, calls
        active += 1; maximum = max(maximum, active); calls += 1
        await asyncio.sleep(0)
        active -= 1
    await MonitorRunner(cycle, 0, max_cycles=3).run()
    assert (calls, maximum) == (3, 1)


@pytest.mark.asyncio
async def test_monitor_isolates_cycle_errors():
    calls = 0
    async def cycle():
        nonlocal calls
        calls += 1
        if calls == 1: raise RuntimeError("one failure")
    await MonitorRunner(cycle, 0, max_cycles=2).run()
    assert calls == 2
