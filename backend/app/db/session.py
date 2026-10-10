from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)  # 断线自动重连
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """每一个请求都生成一个sqlalchemy数据库会话，用完自动释放"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()