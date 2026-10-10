"""JWT 注册/登录"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")  # Swagger 调试友好


def hash_pw(p: str) -> str:
    return pwd_ctx.hash(p)


def verify_pw(p: str, h: str) -> bool:
    return pwd_ctx.verify(p, h)


def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    cred_exc = HTTPException(401, "无效凭证")
    try:
        user_id = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except (JWTError, KeyError):
        raise cred_exc
    user = db.get(User, user_id)
    if not user:
        raise cred_exc
    return user


class RegisterIn(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(409, "用户名已存在")
    user = User(username=body.username, password_hash=hash_pw(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id), "username": user.username}


@router.post("/login")
def login(body: RegisterIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user or not verify_pw(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    return {"token": create_token(user.id), "username": user.username}
