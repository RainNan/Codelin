"""Bounded UTF-8 reads, cross-process write locks and optimistic concurrency."""
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

from filelock import FileLock, Timeout

from app.config import settings
from app.tools.security import ToolError, resolve_safe_path


class FileError(ToolError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def io_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except FileError:
            raise
        except FileNotFoundError as error:
            raise FileError(404, "文件或目录不存在") from error
        except (FileExistsError, NotADirectoryError, IsADirectoryError) as error:
            raise FileError(409, "目标已存在或路径类型不匹配") from error
        except PermissionError as error:
            raise FileError(403, "没有权限访问该文件或目录") from error
        except OSError as error:
            raise FileError(500, "文件系统暂时无法完成操作") from error

    return wrapped


def safe_path(root: Path, path: str) -> Path:
    try:
        return resolve_safe_path(root, path)
    except (ToolError, ValueError, OSError, RuntimeError) as error:
        raise FileError(403, "路径无效或超出工作区范围") from error


@contextmanager
def file_lock(root: Path, path: str):
    target = safe_path(root, path)
    identity = os.path.normcase(str(target))
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lock_root = Path(settings.file_lock_root)
    lock_root.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(lock_root / f"{key}.lock"), timeout=settings.file_lock_timeout):
            # Recheck after waiting for another writer.
            if safe_path(root, path) != target:
                raise FileError(409, "文件路径已变化，请重新载入")
            yield target
    except Timeout as error:
        raise FileError(423, "文件正在写入，请稍后重试") from error


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(target: Path) -> bytes:
    if not target.exists():
        raise FileError(404, "文件不存在")
    if not target.is_file():
        raise FileError(409, "指定路径不是普通文件")
    with target.open("rb") as stream:
        data = stream.read(settings.max_file_bytes + 1)
    if len(data) > settings.max_file_bytes:
        raise FileError(413, f"文件超过编辑上限（{settings.max_file_bytes} 字节）")
    return data


def _decode(data: bytes) -> str:
    if b"\0" in data:
        raise FileError(415, "二进制文件不支持文本编辑")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FileError(415, "目前只支持 UTF-8 文本文件") from error


def _info(root: Path, target: Path) -> dict:
    stat = target.stat()
    return {
        "name": target.name, "path": target.relative_to(root.resolve()).as_posix(),
        "type": "directory" if target.is_dir() else "file",
        "size": None if target.is_dir() else stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


@io_errors
def read_text(root: Path, path: str) -> dict:
    with file_lock(root, path) as target:
        data = _bytes(target)
        return {
            **_info(root, target),
            "content": _decode(data),
            "version": version(data)
        }


def _natural(name: str):
    return [(1, int(part)) if part.isdigit() else (0, part.casefold()) for part in re.split(r"(\d+)", name)]


@io_errors
def list_directory(root: Path, path: str = ".", offset: int = 0, limit: int = 200) -> dict:
    directory = safe_path(root, path)
    if not directory.exists():
        raise FileError(404, "目录不存在")
    if not directory.is_dir():
        raise FileError(409, "指定路径不是目录")
    entries = []
    for child in directory.iterdir():
        # Do not advertise links leading outside the authorized root or special files.
        try:
            target = safe_path(root, child.relative_to(root.resolve()).as_posix())
            if target.is_file() or target.is_dir():
                info = _info(root, target)
                info.update(name=child.name, path=child.relative_to(root.resolve()).as_posix())
                entries.append(info)
        except (FileError, FileNotFoundError, PermissionError):
            continue
    entries.sort(key=lambda entry: (entry["type"] != "directory", _natural(entry["name"])))
    return {
        "path": directory.relative_to(root.resolve()).as_posix(),
        "entries": entries[offset:offset + limit], "total": len(entries),
        "next_offset": offset + limit if offset + limit < len(entries) else None,
    }


@io_errors
def write_text(root: Path, path: str, content: str, *, expected_version: str | None = None,
               create_only: bool = False, create_parents: bool = False) -> dict:
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise FileError(422, "内容包含无效的 Unicode 字符") from error
    if len(data) > settings.max_file_bytes:
        raise FileError(413, f"内容超过编辑上限（{settings.max_file_bytes} 字节）")
    _decode(data)
    with file_lock(root, path) as target:
        existed = target.exists()
        if existed and (create_only or not target.is_file()):
            raise FileError(409, "目标已存在或不是普通文件")
        if expected_version is not None:
            current = _bytes(target)
            _decode(current)
            if version(current) != expected_version:
                raise FileError(409, "文件已被修改，请重新载入或比较差异后保存")
        if not target.parent.exists():
            if not create_parents:
                raise FileError(404, "父目录不存在")
            target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.is_dir():
            raise FileError(409, "父路径不是目录")
        # The temporary file is on the same filesystem, so replace is atomic.
        fd, name = tempfile.mkstemp(prefix=".codelin-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if existed:
                temporary.chmod(target.stat().st_mode & 0o777)
            if safe_path(root, path) != target:
                raise FileError(409, "文件路径已变化，请重新载入")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {**_info(root, target), "version": version(data), "operation": "updated" if existed else "created"}


@io_errors
def create_directory(root: Path, path: str) -> dict:
    with file_lock(root, path) as target:
        if target.exists():
            raise FileError(409, "目标已存在")
        if not target.parent.is_dir():
            raise FileError(404, "父目录不存在")
        target.mkdir()
        return {**_info(root, target), "operation": "created"}
