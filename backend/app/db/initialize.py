"""Initialize the current schema; never upgrade or erase an existing database."""
from sqlalchemy import inspect, text

from app.db.models import Base
from app.db.session import engine

BUSINESS_TABLES = frozenset(Base.metadata.tables)
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations")


def initialize_database(db_engine=engine):
    with db_engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(724036192)"))
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        present = existing & BUSINESS_TABLES
        if present:
            valid = present == BUSINESS_TABLES and "alembic_version" not in existing
            if valid:
                for table in Base.metadata.sorted_tables:
                    columns = {c["name"]: c for c in inspector.get_columns(table.name)}
                    if set(columns) != set(table.columns.keys()) or any(
                        columns[c.name]["nullable"] != c.nullable for c in table.columns
                    ):
                        valid = False
                        break
                    expected_fks = {
                        (tuple(c.name for c in fk.columns), tuple(element.column.name for element in fk.elements),
                         fk.referred_table.name, fk.ondelete)
                        for fk in table.foreign_key_constraints
                    }
                    actual_fks = {
                        (tuple(fk["constrained_columns"]), tuple(fk["referred_columns"]),
                         fk["referred_table"], fk["options"].get("ondelete"))
                        for fk in inspector.get_foreign_keys(table.name)
                    }
                    if expected_fks != actual_fks:
                        valid = False
                        break
            if not valid:
                raise RuntimeError("数据库结构与新版不符，请先运行 python scripts/reset_database.py --execute；该命令会清空旧数据和工作区文件")
            return
        if connection.dialect.name == "postgresql":
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(connection)


def drop_application_tables(db_engine):
    """Only named Codelin objects, including tables from the old schema."""
    with db_engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(724036192)"))
        existing = set(inspect(connection).get_table_names())
        names = [*CHECKPOINT_TABLES, "alembic_version", "tool_invocations", "messages", "code_chunks", "chat_sessions", "workspaces", "users"]
        for name in names:
            if name in existing:
                connection.execute(text(f'DROP TABLE "{name}"'))
