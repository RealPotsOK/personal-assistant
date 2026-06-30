import asyncio

from app.core.scheduler import PriorityGate


async def test_realtime_waiter_runs_before_background_waiter():
    gate = PriorityGate()
    order = []
    release = asyncio.Event()

    async def holder():
        async with gate.slot("normal"):
            await release.wait()

    async def waiter(name, priority):
        async with gate.slot(priority):
            order.append(name)

    active = asyncio.create_task(holder())
    await asyncio.sleep(0)
    background = asyncio.create_task(waiter("background", "background"))
    realtime = asyncio.create_task(waiter("realtime", "realtime"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(active, background, realtime)
    assert order == ["realtime", "background"]


async def test_cancelled_waiter_does_not_block_queue():
    gate = PriorityGate()
    release = asyncio.Event()

    async def holder():
        async with gate.slot():
            await release.wait()

    async def waiter():
        async with gate.slot():
            return True

    active = asyncio.create_task(holder())
    await asyncio.sleep(0)
    cancelled = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.gather(cancelled, return_exceptions=True)
    release.set()
    await active
    assert await asyncio.wait_for(waiter(), 1)
