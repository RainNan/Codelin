"""Do not release resource leases while a cancelled worker still mutates files."""
import asyncio
from anyio import CancelScope


async def run_blocking(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if task.done() and not task.cancelled():
            task.exception()
        raise
