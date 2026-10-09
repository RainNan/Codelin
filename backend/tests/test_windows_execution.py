import asyncio
import shlex
import subprocess
import sys

import pytest

from app.event_loop import loop_factory
from app.tools import ops
from app.tools.security import ToolError


def python_command(code):
    args = [sys.executable, "-c", code]
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def test_commands_work_in_database_compatible_loop(tmp_path):
    async def probe():
        result = await ops.run_command(
            tmp_path, python_command("import os; print(os.getcwd())")
        )
        assert result.startswith("[exit code 0]")
        assert str(tmp_path) in result
        result = await ops.run_command(
            tmp_path,
            python_command("import sys; print('stderr-marker', file=sys.stderr); sys.exit(7)"),
        )
        assert result.startswith("[exit code 7]")
        assert "stderr-marker" in result

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(probe())


def test_timeout_is_reported_as_tool_error(tmp_path, monkeypatch):
    def timed_out(*args, **kwargs):
        assert kwargs["timeout"] == ops.CMD_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(ops.subprocess, "run", timed_out)
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        with pytest.raises(ToolError, match="命令超时"):
            runner.run(ops.run_command(tmp_path, "unused-test-command"))
