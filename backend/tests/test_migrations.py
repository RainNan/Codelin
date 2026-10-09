from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from app.db.migrate import upgrade_database


def test_existing_directories_are_adopted_and_migration_is_repeatable(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    (root / "important.txt").write_text("keep me")
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY)"))
        db.execute(text("CREATE TABLE chat_sessions (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32) NOT NULL REFERENCES users(id), title VARCHAR(128) NOT NULL, workspace_path VARCHAR(512) NOT NULL, created_at DATETIME NOT NULL)"))
        db.execute(text("INSERT INTO users VALUES ('u')"))
        for sid in ("s1", "s2"):
            db.execute(text("INSERT INTO chat_sessions VALUES (:sid,'u','old',:root,'2026-10-09 00:00:00')"), {"sid": sid, "root": str(root)})
    upgrade_database(engine)
    upgrade_database(engine)
    with engine.connect() as db:
        rows = db.execute(text("SELECT workspace_id,workspace_path FROM chat_sessions")).all()
        assert rows[0].workspace_id == rows[1].workspace_id
        assert all(row.workspace_path == str(root) for row in rows)
        assert db.execute(text("SELECT COUNT(*) FROM workspaces")).scalar() == 1
        assert db.execute(text("SELECT root_path FROM workspaces")).scalar() == str(root)
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001_workspaces"
    assert (root / "important.txt").read_text() == "keep me"
    assert not inspect(engine).get_columns("chat_sessions")[-1]["nullable"]
    engine.dispose()


def test_empty_database_bootstrap_can_be_repeated():
    engine = create_engine("sqlite://")
    upgrade_database(engine)
    upgrade_database(engine)
    assert inspect(engine).has_table("workspaces")
    assert "workspace_id" in {column["name"] for column in inspect(engine).get_columns("chat_sessions")}
    engine.dispose()
