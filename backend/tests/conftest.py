"""Service-free operation leases for HTTP tests; real Redis is tested separately."""
import threading

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def local_operation_leases(monkeypatch, request):
    if request.node.get_closest_marker("infra"):
        return
    from app import operations
    mutex = threading.Lock()
    active = {}

    class LocalLease:
        def __init__(self, resource, mode="exclusive"):
            self.resource, self.mode = resource, mode

        def acquire(self):
            with mutex:
                holders = active.setdefault(self.resource, [])
                if holders and (self.mode == "exclusive" or "exclusive" in holders):
                    raise HTTPException(409, "资源正在使用")
                holders.append(self.mode)
            return self

        def check(self):
            pass

        def close(self):
            with mutex:
                active[self.resource].remove(self.mode)

    monkeypatch.setattr(operations, "Lease", LocalLease)
