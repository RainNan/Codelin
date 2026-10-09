"""Use the application's configured engine; credentials never enter alembic.ini."""
from alembic import context
from app.db.models import Base
from app.db.session import engine

if context.is_offline_mode():
    raise RuntimeError("This adoption migration requires a live database to preserve existing workspaces.")


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


supplied = context.config.attributes.get("connection")
if supplied is not None:
    run(supplied)
else:
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            from sqlalchemy import text
            connection.execute(text("SELECT pg_advisory_xact_lock(724036192)"))
        run(connection)
