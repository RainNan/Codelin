from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.api.workspaces import create_owned_workspace, owned_workspace
from app.db.models import ChatSession, CodeChunk, Message, ToolInvocation, User, new_id
from app.db.session import get_db
from app.llm.titles import DEFAULT_TITLE

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionIn(BaseModel):
    workspace_id: str | None = Field(default=None, min_length=1, max_length=32)
    title: str = Field(default=DEFAULT_TITLE, min_length=1, max_length=128)


def session_view(session):
    return {"id": session.id, "title": session.title, "workspace_id": session.workspace_id, "created_at": str(session.created_at)}


@router.get("")
def list_sessions(workspace_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(ChatSession).filter_by(user_id=user.id)
    if workspace_id:
        owned_workspace(db, user.id, workspace_id)
        query = query.filter_by(workspace_id=workspace_id)
    return [session_view(session) for session in query.order_by(ChatSession.created_at.desc()).all()]


@router.post("")
def create_session(body: SessionIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    body = body or SessionIn()
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "会话标题不能为空")
    workspace = owned_workspace(db, user.id, body.workspace_id) if body.workspace_id else create_owned_workspace(db, user.id, "新工作空间")
    session = ChatSession(id=new_id(), user_id=user.id, title=title, workspace_id=workspace.id, workspace_path=workspace.root_path)
    db.add(session)
    db.commit()
    return session_view(session)


@router.get("/{sid}")
def get_session(sid: str, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter_by(id=sid, user_id=user.id).first()
    if not session:
        raise HTTPException(404, "会话不存在")
    response.headers["Cache-Control"] = "no-store"
    return session_view(session)


@router.delete("/{sid}")
def delete_session(sid: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter_by(id=sid, user_id=user.id).first()
    if not session:
        raise HTTPException(404, "会话不存在")
    for model in (Message, ToolInvocation, CodeChunk):
        db.query(model).filter_by(session_id=sid).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"ok": True}
