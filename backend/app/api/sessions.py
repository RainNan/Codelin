from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.models import ChatSession, User
from app.db.session import get_db

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(ChatSession)
        .filter_by(user_id=user.id)
        .order_by(ChatSession.created_at.desc())
        .all()
    )
    return [{"id": r.id, "title": r.title, "created_at": str(r.created_at)} for r in rows]


@router.post("")
def create_session(user: User = Depends(current_user), db: Session = Depends(get_db)):
    import uuid
    from pathlib import Path
    from app.config import settings  # noqa: F811
    sid = uuid.uuid4().hex
    ws = Path("workspaces") / sid
    ws.mkdir(parents=True, exist_ok=True)
    s = ChatSession(id=sid, user_id=user.id, workspace_path=str(ws.resolve()))
    db.add(s)
    db.commit()
    return {"id": s.id, "title": s.title}


@router.delete("/{sid}")
def delete_session(sid: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    return {"ok": True}