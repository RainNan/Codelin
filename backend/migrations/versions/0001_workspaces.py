"""Adopt existing session directories without moving or deleting files."""
from datetime import datetime, timezone
from pathlib import Path
import uuid
import os

from alembic import op
import sqlalchemy as sa

revision = "0001_workspaces"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("chat_sessions"):
        raise RuntimeError("Initialize an empty database with: python scripts/migrate.py")
    if not inspector.has_table("workspaces"):
        op.create_table("workspaces",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("root_path", sa.String(512), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
    if "workspace_id" not in {column["name"] for column in inspector.get_columns("chat_sessions")}:
        op.add_column("chat_sessions", sa.Column("workspace_id", sa.String(32), nullable=True))
    rows = bind.execute(sa.text("SELECT id, user_id, title, workspace_path, created_at, workspace_id FROM chat_sessions ORDER BY created_at, id")).mappings().all()
    roots = {}
    for row in rows:
        if row["workspace_id"]:
            continue
        root = str(Path(row["workspace_path"]).resolve())
        identity = os.path.normcase(root)
        if identity in roots and roots[identity] != row["user_id"]:
            raise RuntimeError("Existing users share a workspace directory; resolve ownership before migration.")
        roots[identity] = row["user_id"]
        wid = uuid.uuid5(uuid.NAMESPACE_URL, f"codelin:{row['user_id']}:{identity}").hex
        exists = bind.execute(sa.text("SELECT id FROM workspaces WHERE id = :id"), {"id": wid}).first()
        if not exists:
            bind.execute(sa.text("INSERT INTO workspaces (id,user_id,name,root_path,created_at) VALUES (:id,:user_id,:name,:root_path,:created_at)"), {
                "id": wid, "user_id": row["user_id"], "name": row["title"] or "原有工作空间",
                "root_path": root, "created_at": row["created_at"] or datetime.now(timezone.utc),
            })
        bind.execute(sa.text("UPDATE chat_sessions SET workspace_id = :wid WHERE id = :sid"), {"wid": wid, "sid": row["id"]})
    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys("chat_sessions")
    indexes = inspector.get_indexes("chat_sessions")
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("workspace_id", existing_type=sa.String(32), nullable=False)
        if not any(fk["constrained_columns"] == ["workspace_id"] for fk in foreign_keys):
            batch.create_foreign_key("fk_chat_sessions_workspace_id", "workspaces", ["workspace_id"], ["id"])
        if not any(index["column_names"] == ["workspace_id"] for index in indexes):
            batch.create_index("ix_chat_sessions_workspace_id", ["workspace_id"])


def downgrade():
    raise RuntimeError("Automatic downgrade is disabled to preserve workspace associations and files.")
