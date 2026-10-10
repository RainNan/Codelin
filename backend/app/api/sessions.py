from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.models import ChatSession, User, new_id
from app.db.session import get_db
from app.lifecycle import clean_name, delete_checkpoint, owned_session, owned_workspace, session_view
from app.llm.titles import DEFAULT_TITLE
from app.operations import operation

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionIn(BaseModel):
    workspace_id: str | None = Field(default=None, min_length=1, max_length=32)
    title: str = Field(default=DEFAULT_TITLE, min_length=1, max_length=128)


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=32)


@router.get("")
def list_sessions(workspace_id: str | None = None, standalone: bool = False,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    if workspace_id and standalone:
        raise HTTPException(422, "不能同时按工作区和独立对话筛选")
    query = db.query(ChatSession).filter_by(user_id=user.id)
    if workspace_id:
        owned_workspace(db, user.id, workspace_id, allow_deleting=True)
        query = query.filter_by(workspace_id=workspace_id)
    elif standalone:
        query = query.filter(ChatSession.workspace_id.is_(None))
    return [session_view(row) for row in query.order_by(ChatSession.created_at.desc(), ChatSession.id).all()]


@router.post("")
def create_session(body: SessionIn | None = None,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    body = body or SessionIn()
    title = clean_name(body.title, "对话标题")
    if body.workspace_id:
        owned_workspace(db, user.id, body.workspace_id)
        with operation(f"workspace:{body.workspace_id}", "shared"):
            db.expire_all()
            owned_workspace(db, user.id, body.workspace_id)
            return _create(db, user.id, title, body.workspace_id)
    return _create(db, user.id, title, None)


def _create(db, uid, title, wid):
    session = ChatSession(id=new_id(), user_id=uid, title=title, workspace_id=wid)
    db.add(session)
    db.commit()
    return session_view(session)


@router.get("/{sid}")
def get_session(sid: str, response: Response,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return session_view(owned_session(db, user.id, sid, allow_deleting=True))


@router.patch("/{sid}")
def update_session(sid: str, body: SessionPatch,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_session(db, user.id, sid)
    if not body.model_fields_set or ("title" in body.model_fields_set and body.title is None):
        raise HTTPException(422, "请提供有效的修改内容")
    with operation(f"session:{sid}") as guard:
        db.expire_all()
        session = owned_session(db, user.id, sid)
        if "workspace_id" in body.model_fields_set:
            if session.workspace_id and body.workspace_id != session.workspace_id:
                raise HTTPException(409, "已加入工作区的对话不能移出或转入其他工作区")
            if body.workspace_id:
                owned_workspace(db, user.id, body.workspace_id)
                guard.acquire(f"workspace:{body.workspace_id}", "shared")
                db.expire_all()
                owned_workspace(db, user.id, body.workspace_id)
                session.workspace_id = body.workspace_id
        if body.title is not None:
            session.title = clean_name(body.title, "对话标题")
            session.auto_title = False
        guard.check()
        db.commit()
        return session_view(session)


@router.delete("/{sid}")
async def delete_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_session(db, user.id, sid, allow_deleting=True)
    with operation(f"session:{sid}") as guard:
        db.expire_all()
        session = owned_session(db, user.id, sid, allow_deleting=True)
        if session.workspace_id:
            guard.acquire(f"workspace:{session.workspace_id}", "shared")
        session.deleting = True
        db.commit()
        try:
            await delete_checkpoint(sid)
            guard.check()
            db.delete(session)
            db.commit()
        except Exception as error:
            db.rollback()
            raise HTTPException(500, "对话清理未完成，请重试删除") from error
    return {"ok": True}
