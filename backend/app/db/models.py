"""业务数据模型。注意：checkpoint 相关表由 PostgresSaver.setup() 自建，不在此处。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (ForeignKeyConstraint(["workspace_id", "user_id"], ["workspaces.id", "workspaces.user_id"]),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    auto_title: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    deleting: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("id", "user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    root_path: Mapped[str] = mapped_column(String(512))
    deleting: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    """产品视角的消息（列表展示用）；权威副本在 Checkpoint 的 State.messages。"""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[Text] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolInvocation(Base):
    """工具调用审计：M4 的幂等第二道保险 + M10 的 Tool Failure Rate 数据源。"""
    __tablename__ = "tool_invocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str] = mapped_column(String(64), index=True)  # LLM 的 tool_call id
    tool: Mapped[str] = mapped_column(String(32))
    args: Mapped[dict] = mapped_column(JSON)
    ok: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodeChunk(Base):
    """代码块向量库：同一工作区的所有对话共享索引。"""
    __tablename__ = "code_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(1024))  # bge-m3 输出 1024 维
