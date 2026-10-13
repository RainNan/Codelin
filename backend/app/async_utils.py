"""就算上层请求取消任务，只要后台线程还在修改文件，就不能释放资源租约 / 文件锁；必须等磁盘操作完成，再响应取消。防止文件损坏"""
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
