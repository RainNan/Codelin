"""第一次对话触发，命名对话标题"""
from fastapi import APIRouter, Depends, Query, Response

router = APIRouter(prefix="/api/workspaces/{wid}", tags=["files"])

@router.get("/file")
def get_title(wid: str, response: Response, path: str = Query(min_length=1, max_length=1024),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = service.read_text(root_for(db, user, wid), path)
    response.headers["ETag"] = f'"{data["version"]}"'
    response.headers["Cache-Control"] = "no-store"
    return data