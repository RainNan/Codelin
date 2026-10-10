from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.initialize import initialize_database
from app.db.models import Base
from app.files.service import FileError
from app.lifecycle import clear_managed_workspaces
from scripts.reset_database import reset_database


def test_initialize_is_repeatable_and_preserves_data():
    engine = create_engine("sqlite://")
    initialize_database(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,username,password_hash,created_at) VALUES ('u','user','hash',CURRENT_TIMESTAMP)"))
    initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)


def test_old_or_partial_schema_is_rejected_without_changes():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users VALUES ('keep')"))
    with pytest.raises(RuntimeError, match="reset_database"):
        initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users")).scalar() == "keep"
    assert inspect(engine).get_table_names() == ["users"]


def test_reset_clears_only_application_tables_and_managed_files(tmp_path):
    engine = create_engine("sqlite://")
    initialize_database(engine)
    with engine.begin() as connection:
        for name in ("unrelated", "alembic_version", "checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"):
            connection.execute(text(f'CREATE TABLE "{name}" (value TEXT)'))
            connection.execute(text(f"INSERT INTO \"{name}\" VALUES ('old')"))
    root = tmp_path / "workspaces"
    root.mkdir()
    (root / "old").mkdir()
    (root / "old" / "file.py").write_text("old")
    outside = tmp_path / "source.py"
    outside.write_text("keep")
    reset_database(engine, workspace_root=root)
    assert list(root.iterdir()) == [] and outside.read_text() == "keep"
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"unrelated"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM unrelated")).scalar() == "old"
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0


def test_reset_refuses_source_or_drive_roots():
    backend = Path(__file__).resolve().parents[1]
    for root in (backend, backend.parent, Path(backend.anchor)):
        with pytest.raises(FileError):
            clear_managed_workspaces(root)
