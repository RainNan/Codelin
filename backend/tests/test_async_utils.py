import asyncio
import threading
import anyio

import pytest

from app.async_utils import run_blocking


@pytest.mark.asyncio
async def test_cancelled_file_worker_finishes_before_caller_releases_lease():
    started, finish = threading.Event(), threading.Event()
    order = []
    def worker():
        started.set()
        finish.wait(2)
        order.append("file mutation completed")
    async def caller():
        try:
            await run_blocking(worker)
        finally:
            order.append("lease released")
    task = asyncio.create_task(caller())
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done() and order == []
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["file mutation completed", "lease released"]


@pytest.mark.asyncio
async def test_request_cancel_scope_drains_mutation_before_release():
    started, finish = threading.Event(), threading.Event()
    order = []
    def worker():
        started.set()
        finish.wait(2)
        order.append("checkpoint completed")
    async def caller():
        try:
            await run_blocking(worker)
        finally:
            order.append("lease released")
    async with anyio.create_task_group() as group:
        group.start_soon(caller)
        await asyncio.to_thread(started.wait, 2)
        group.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.sleep(.01)
            assert order == []
            finish.set()
    assert order == ["checkpoint completed", "lease released"]
