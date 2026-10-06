import pytest

from app.tools import ops
from app.tools.security import ToolError


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("hello world", encoding="utf-8")
    return tmp_path


def test_list_dir(ws):
    out = ops.list_dir(ws)
    assert "[目录] sub" in out and "[文件] a.py" in out


def test_read_file_with_lineno(ws):
    assert "1 | print('hi')" in ops.read_file(ws, "a.py")


def test_write_file_creates_parents(ws):
    ops.write_file(ws, "src/deep/c.py", "x = 1")
    assert (ws / "src" / "deep" / "c.py").read_text() == "x = 1"


def test_path_escape_blocked(ws):
    with pytest.raises(ToolError):
        ops.read_file(ws, "../outside.txt")


def test_grep(ws):
    out = ops.grep(ws, r"print", "*.py")
    assert "a.py:1" in out


def test_is_dangerous():
    assert ops.is_dangerous("rm -rf /")
    assert ops.is_dangerous("pip install requests")
    assert not ops.is_dangerous("python -m pytest")