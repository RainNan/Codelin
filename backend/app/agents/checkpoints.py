"""PostgreSQL checkpoints with nonblocking access on any asyncio event loop."""
import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres import PostgresSaver


class ThreadedPostgresSaver(PostgresSaver):
    """Adapt the thread-safe synchronous saver to LangGraph's async interface."""

    @classmethod
    @asynccontextmanager
    async def open(cls, conn_string):
        manager = cls.from_conn_string(conn_string)
        saver = await asyncio.to_thread(manager.__enter__)
        try:
            yield saver
        finally:
            await asyncio.to_thread(manager.__exit__, None, None, None)

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        rows = self.list(config, filter=filter, before=before, limit=limit)
        try:
            while True:
                row = await asyncio.to_thread(next, rows, None)
                if row is None:
                    return
                yield row
        finally:
            await asyncio.to_thread(rows.close)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(
            self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        await asyncio.to_thread(self.delete_thread, thread_id)
