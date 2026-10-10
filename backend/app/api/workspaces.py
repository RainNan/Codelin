from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.async_utils import run_blocking
from app.db.models import ChatSession, Workspace, User
from app.db.session import get_db
from app.lifecycle import clean_name, delete_checkpoint, owned_workspace, remove_workspace_files, workspace_creation, workspace_view
from app.operations import operation
from app.rag.retrieval import bm25_store

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(default="新工作区", min_length=1, max_length=128)


@router.get("")
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Workspace).filter_by(user_id=user.id).order_by(Workspace.created_at.desc(), Workspace.id).all()
    return [workspace_view(workspace) for workspace in rows]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with workspace_creation(db, user.id, body.name) as workspace:
        db.commit()
        return workspace_view(workspace)


@router.get("/{wid}")
def get_workspace(wid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workspace_view(owned_workspace(db, user.id, wid, allow_deleting=True))


@router.patch("/{wid}")
def rename_workspace(wid: str, body: WorkspaceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_workspace(db, user.id, wid)
    with operation(f"workspace:{wid}", "shared") as guard:
        db.expire_all()
        workspace = owned_workspace(db, user.id, wid)
        workspace.name = clean_name(body.name, "工作区名称")
        guard.check()
        db.commit()
        return workspace_view(workspace)


@router.delete("/{wid}")
async def delete_workspace(wid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_workspace(db, user.id, wid, allow_deleting=True)
    with operation(f"workspace:{wid}") as guard:
        db.expire_all()
        workspace = owned_workspace(db, user.id, wid, allow_deleting=True)
        sessions = db.query(ChatSession).filter_by(workspace_id=wid, user_id=user.id).all()
        for session in sessions:
            guard.acquire(f"session:{session.id}")
        workspace.deleting = True
        db.commit()
        try:
            await run_blocking(remove_workspace_files, workspace)
            for session in sessions:
                await delete_checkpoint(session.id)
            guard.check()
            for session in sessions:
                db.delete(session)
            db.flush()
            db.delete(workspace)
            db.commit()
            bm25_store.drop(wid)
        except Exception as error:
            db.rollback()
            raise HTTPException(500, "工作区清理未完成，请重试删除；其对话和文件已暂停使用") from error
    return {"ok": True}
