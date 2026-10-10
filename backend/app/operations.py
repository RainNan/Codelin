"""Redis leases: shared workspace access and exclusive session/delete operations."""
import threading
import uuid
from contextlib import contextmanager

import redis
from fastapi import HTTPException

from app.config import settings

client = redis.Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=5)
_ACQUIRE = """
local now = redis.call('TIME')
local ms = now[1]*1000 + math.floor(now[2]/1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ms)
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
if ARGV[2] == 'exclusive' then
  if redis.call('ZCARD', KEYS[2]) > 0 then return 0 end
  redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[3])
else
  redis.call('ZADD', KEYS[2], ms+ARGV[3], ARGV[1])
  redis.call('PEXPIRE', KEYS[2], ARGV[3])
end
return 1
"""
_RENEW = """
if ARGV[2] == 'exclusive' then
  if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
  return redis.call('PEXPIRE', KEYS[1], ARGV[3])
else
  local now = redis.call('TIME')
  local ms = now[1]*1000 + math.floor(now[2]/1000)
  local expiry = redis.call('ZSCORE', KEYS[2], ARGV[1])
  if not expiry or tonumber(expiry) <= ms then return 0 end
  redis.call('ZADD', KEYS[2], ms+ARGV[3], ARGV[1])
  redis.call('PEXPIRE', KEYS[2], ARGV[3])
  return 1
end
"""
_RELEASE = """
if ARGV[2] == 'exclusive' then
  if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('DEL', KEYS[1]) end
else redis.call('ZREM', KEYS[2], ARGV[1]) end
return 1
"""


class Lease:
    ttl_ms = 60000

    def __init__(self, resource, mode="exclusive"):
        self.mode, self.token = mode, uuid.uuid4().hex
        self.keys = [f"codelin:operation:{resource}:writer", f"codelin:operation:{resource}:readers"]
        self.stopped = threading.Event()
        self.lost = False

    def call(self, script):
        return client.eval(script, 2, *self.keys, self.token, self.mode, self.ttl_ms)

    def acquire(self):
        try:
            acquired = self.call(_ACQUIRE)
        except redis.RedisError as error:
            raise HTTPException(503, "操作保护服务暂时不可用，请稍后重试") from error
        if not acquired:
            raise HTTPException(409, "对话或工作区正在处理其他操作，请稍后重试")
        self.worker = threading.Thread(target=self.renew, daemon=True)
        self.worker.start()
        return self

    def renew(self):
        while not self.stopped.wait(15):
            try:
                if not self.call(_RENEW):
                    self.lost = True
                    return
            except redis.RedisError:
                self.lost = True
                return

    def check(self):
        if self.lost:
            raise HTTPException(503, "操作保护已失效，请重新载入后重试")

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=6)
        try:
            self.call(_RELEASE)
        except redis.RedisError:
            pass  # Expiration releases abandoned leases; never delete another owner's lease.


class Operation:
    def __init__(self):
        self.leases = {}

    def acquire(self, resource, mode="exclusive"):
        if resource not in self.leases:
            self.leases[resource] = Lease(resource, mode).acquire()
        self.check()

    def check(self):
        for lease in self.leases.values():
            lease.check()

    def close(self):
        for lease in reversed(list(self.leases.values())):
            lease.close()
        self.leases.clear()


@contextmanager
def operation(resource, mode="exclusive"):
    guard = Operation()
    try:
        guard.acquire(resource, mode)
        yield guard
    finally:
        guard.close()
