from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.api.workspaces import owned_workspace
from app.db.models import User
from app.db.session import get_db
from app.files import service

router = APIRouter(prefix="/api/workspaces/{wid}", tags=["files"])


class SaveIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str
    version: str = Field(pattern=r"^[0-9a-f]{64}$")


class EntryIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    type: Literal["file", "directory"]
    content: str = ""


def root_for(db, user, wid):
    return Path(owned_workspace(db, user.id, wid).root_path)


@router.get("/files")
def list_files(wid: str, response: Response, path: str = Query(default=".", max_length=1024),
               offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return service.list_directory(root_for(db, user, wid), path, offset, limit)


@router.get("/file")
def get_file(wid: str, response: Response, path: str = Query(min_length=1, max_length=1024),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = service.read_text(root_for(db, user, wid), path)
    response.headers["ETag"] = f'"{data["version"]}"'
    response.headers["Cache-Control"] = "no-store"
    return data


@router.put("/file")
def save_file(wid: str, body: SaveIn, response: Response,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = service.write_text(root_for(db, user, wid), body.path, body.content, expected_version=body.version)
    response.headers["ETag"] = f'"{data["version"]}"'
    response.headers["Cache-Control"] = "no-store"
    return data


@router.post("/entries", status_code=201)
def create_entry(wid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    root = root_for(db, user, wid)
    if body.type == "directory":
        return service.create_directory(root, body.path)
    return service.write_text(root, body.path, body.content, create_only=True)
