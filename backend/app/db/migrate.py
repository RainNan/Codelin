"""Bootstrap new databases and upgrade existing installations transactionally."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from app.db.models import Base
from app.db.session import engine


def upgrade_database(db_engine=engine):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with db_engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(724036192)"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        config.attributes["connection"] = connection
        if not inspect(connection).has_table("users"):
            Base.metadata.create_all(connection)
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")
