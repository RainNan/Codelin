"""Ownership, workspace allocation and retryable resource cleanup."""
import shutil
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.db.models import ChatSession, Workspace, new_id
from app.files.service import FileError, io_errors, safe_path


def owned_session(db, uid, sid, *, allow_deleting=False):
    session = db.query(ChatSession).filter_by(id=sid, user_id=uid).first()
    if not session:
        raise HTTPException(404, "对话不存在")
    if session.deleting and not allow_deleting:
        raise HTTPException(409, "对话正在删除，请重试删除操作")
    return session


def owned_workspace(db, uid, wid, *, allow_deleting=False):
    workspace = db.query(Workspace).filter_by(id=wid, user_id=uid).first()
    if not workspace:
        raise HTTPException(404, "工作区不存在")
    if workspace.deleting and not allow_deleting:
        raise HTTPException(409, "工作区删除尚未完成，请重试删除操作")
    return workspace


def workspace_view(workspace):
    return {"id": workspace.id, "name": workspace.name, "created_at": str(workspace.created_at), "deleting": workspace.deleting}


def session_view(session):
    return {"id": session.id, "title": session.title, "workspace_id": session.workspace_id, "created_at": str(session.created_at), "deleting": session.deleting}


def clean_name(value, label):
    value = value.strip()
    if not value:
        raise HTTPException(422, f"{label}不能为空")
    return value


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def checked_root(root):
    raw = root.absolute()
    resolved = raw.resolve()
    backend = Path(__file__).resolve().parents[1]
    if resolved == Path(resolved.anchor) or resolved in (backend, backend.parent) or resolved in backend.parents:
        raise FileError(403, "拒绝清理源码目录或其上级目录")
    if any(_linked(p) for p in (raw, *raw.parents)):
        raise FileError(403, "拒绝清理符号链接或目录联接中的工作区")
    return resolved


@io_errors
def remove_workspace_files(workspace):
    root = checked_root(Path(settings.workspace_root))
    expected = root / workspace.user_id / workspace.id
    raw = Path(workspace.root_path).absolute()
    if raw != expected or any(_linked(p) for p in (raw, raw.parent)) or raw.resolve() != expected:
        raise FileError(403, "工作区目录不属于后端管理范围，拒绝删除")
    if raw.exists():
        shutil.rmtree(raw)


@io_errors
def clear_managed_workspaces(root):
    root = checked_root(root)
    if not root.exists():
        return
    children = list(root.iterdir())
    for child in children:
        if _linked(child) or child.resolve().parent != root:
            raise FileError(403, "工作区根目录含越界链接，拒绝清空")
    for child in children:
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


@contextmanager
def workspace_creation(db, uid, name):
    name = clean_name(name, "工作区名称")
    wid = new_id()
    root = safe_path(checked_root(Path(settings.workspace_root)), f"{uid}/{wid}")
    io_errors(lambda: root.mkdir(parents=True, exist_ok=False))()
    try:
        workspace = Workspace(id=wid, user_id=uid, name=name, root_path=str(root))
        db.add(workspace)
        db.flush()
        yield workspace
    except BaseException:
        db.rollback()
        if root.exists():
            shutil.rmtree(root)
        raise


def prepare_agent_workspace(factory, uid, sid, guard):
    with factory() as db:
        session = owned_session(db, uid, sid)
        if session.workspace_id:
            guard.acquire(f"workspace:{session.workspace_id}", "shared")
            workspace = owned_workspace(db, uid, session.workspace_id)
            return workspace.id, workspace.root_path, None
        with workspace_creation(db, uid, "新工作区") as workspace:
            guard.acquire(f"workspace:{workspace.id}", "shared")
            session.workspace_id = workspace.id
            guard.check()
            db.commit()
            return workspace.id, workspace.root_path, workspace_view(workspace)


async def delete_checkpoint(sid):
    from app.agents.graph import graph
    saver = getattr(graph, "checkpointer", None)
    if saver is not None:
        await saver.adelete_thread(sid)
