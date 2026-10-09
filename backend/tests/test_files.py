from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import os
import subprocess

import pytest

from app.config import settings
from app.files import service
from app.tools import ops


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "file_lock_root", str(tmp_path / "locks"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_raw_content_roundtrip_preserves_crlf_and_is_not_ai_output(root):
    data = "第一行\r\n第二行\r\n" + "x" * 31000
    (root / "example.txt").write_bytes(data.encode("utf-8"))
    result = service.read_text(root, "example.txt")
    assert result["content"] == data
    assert "1 |" not in result["content"]
    assert "截断" in ops.read_file(root, "example.txt")
    saved = service.write_text(root, "example.txt", "new\r\n", expected_version=result["version"])
    assert (root / "example.txt").read_bytes() == b"new\r\n"
    assert saved["version"] != result["version"]


def test_ai_write_invalidates_editor_version(root):
    service.write_text(root, "main.py", "original", create_only=True)
    original = service.read_text(root, "main.py")
    ops.write_file(root, "main.py", "AI change")
    with pytest.raises(service.FileError) as error:
        service.write_text(root, "main.py", "editor change", expected_version=original["version"])
    assert error.value.status == 409
    assert service.read_text(root, "main.py")["content"] == "AI change"


def test_failed_save_preserves_original_and_cleans_temporary_file(root, monkeypatch):
    result = service.write_text(root, "main.py", "original", create_only=True)
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(service.os, "replace", denied)
    with pytest.raises(service.FileError) as error:
        service.write_text(root, "main.py", "modified", expected_version=result["version"])
    assert error.value.status == 403
    assert (root / "main.py").read_text() == "original"
    assert not list(root.glob(".codelin-*"))


@pytest.mark.parametrize("path", ["../secret", "sub/../../secret", r"..\secret", "/etc/passwd", r"C:\Windows\file", r"C:secret", r"\\server\share\file", "file:stream", "CON.txt", "NUL", "trailing.", "control\x01.txt", "line\nname"])
def test_invalid_paths_cannot_read_or_write(root, path):
    with pytest.raises(service.FileError) as error:
        service.write_text(root, path, "bad", create_parents=True)
    assert error.value.status == 403


def test_natural_directory_sort_and_pagination(root):
    (root / "folder").mkdir()
    for name in ["file10.py", "file2.py", "file1.py"]:
        (root / name).write_text("x")
    first = service.list_directory(root, limit=2)
    assert [item["name"] for item in first["entries"]] == ["folder", "file1.py"]
    assert first["next_offset"] == 2 and first["total"] == 4
    assert [item["name"] for item in service.list_directory(root, offset=2)["entries"]] == ["file2.py", "file10.py"]


def test_binary_large_missing_and_duplicate_entries(root, monkeypatch):
    (root / "binary").write_bytes(b"hello\0world")
    (root / "encoded").write_bytes(b"\xff\xfe")
    (root / "large").write_bytes(b"x" * 101)
    monkeypatch.setattr(settings, "max_file_bytes", 100)
    for path, status in [("binary", 415), ("encoded", 415), ("large", 413), ("missing", 404)]:
        with pytest.raises(service.FileError) as error:
            service.read_text(root, path)
        assert error.value.status == status
    with pytest.raises(service.FileError) as error:
        service.write_text(root, "large", "", create_only=True)
    assert error.value.status == 409
    assert service.create_directory(root, "src")["type"] == "directory"
    with pytest.raises(service.FileError) as error:
        service.create_directory(root, "src")
    assert error.value.status == 409


def test_external_directory_link_is_not_followed(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = root / "escape"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        assert result.returncode == 0
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert service.list_directory(root)["entries"] == []
    with pytest.raises(service.FileError) as error:
        service.read_text(root, "escape/secret.txt")
    assert error.value.status == 403
    with pytest.raises(service.FileError):
        service.write_text(root, "escape/secret.txt", "changed")
    assert (outside / "secret.txt").read_text() == "secret"


def test_utf8_bom_and_special_filename_roundtrip(root):
    path = "file #1 中文.txt"
    original = "\ufeff原文\r\n"
    service.write_text(root, path, original, create_only=True)
    content = service.read_text(root, path)
    assert content["content"] == original
    service.write_text(root, path, original + "更新\r\n", expected_version=content["version"])
    assert (root / path).read_bytes().startswith(b"\xef\xbb\xbf")
    assert service.list_directory(root)["entries"][0]["path"] == path


def _concurrent_save(root, locks, version, content):
    settings.file_lock_root = locks
    try:
        service.write_text(Path(root), "shared.txt", content, expected_version=version)
        return 200
    except service.FileError as error:
        return error.status


def test_two_processes_cannot_both_save_the_same_version(root):
    result = service.write_text(root, "shared.txt", "original", create_only=True)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(_concurrent_save, str(root), settings.file_lock_root, result["version"], text) for text in ("one", "two")]
        assert sorted(future.result(timeout=30) for future in futures) == [200, 409]
    assert not list(root.glob(".codelin-*"))
