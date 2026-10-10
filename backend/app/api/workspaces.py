from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import settings
from app.db.models import Workspace, User, new_id
from app.db.session import get_db
from app.files.service import safe_path, io_errors

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def owned_workspace(db: Session, user_id: str, wid: str) -> Workspace:
    workspace = db.query(Workspace).filter_by(id=wid, user_id=user_id).first()
    if not workspace:
        raise HTTPException(404, "工作区不存在")
    return workspace


def workspace_view(workspace: Workspace) -> dict:
    return {"id": workspace.id, "name": workspace.name, "created_at": str(workspace.created_at)}


class WorkspaceIn(BaseModel):
    name: str = Field(default="新工作空间", min_length=1, max_length=128)


@io_errors
def create_owned_workspace(db: Session, user_id: str, name: str) -> Workspace:
    name = name.strip()
    if not name:
        raise HTTPException(422, "工作区名称不能为空")
    wid = new_id()
    root = safe_path(Path(settings.workspace_root), f"{user_id}/{wid}")
    root.mkdir(parents=True, exist_ok=False)
    workspace = Workspace(id=wid, user_id=user_id, name=name, root_path=str(root))
    db.add(workspace)
    db.flush()
    return workspace


@router.get("")
def list_workspaces(user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    rows = db.query(Workspace).filter_by(user_id=user.id).order_by(Workspace.created_at.desc(), Workspace.id).all()
    return [workspace_view(workspace) for workspace in rows]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn,
                     user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    workspace = create_owned_workspace(db, user.id, body.name)
    db.commit()
    return workspace_view(workspace)


@router.get("/{wid}")
def get_workspace(wid: str,
                  user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    return workspace_view(owned_workspace(db, user.id, wid))
