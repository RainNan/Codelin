"""Explicit, destructive reset of Codelin data and managed workspace files."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.config import settings
from app.db.initialize import drop_application_tables, initialize_database
from app.db.session import engine
from app.lifecycle import clear_managed_workspaces


def reset_database(db_engine=engine, checkpoint_url=None, workspace_root=None):
    from sqlalchemy import text
    # Verify every database connection before removing any files or tables.
    with db_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    checkpoint_engine = None
    if checkpoint_url and make_url(checkpoint_url).set(drivername="postgresql+psycopg") != db_engine.url:
        checkpoint_engine = create_engine(make_url(checkpoint_url).set(drivername="postgresql+psycopg"))
        with checkpoint_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    try:
        clear_managed_workspaces(Path(workspace_root or settings.workspace_root))
        drop_application_tables(db_engine)
        if checkpoint_engine is not None:
            from app.db.initialize import CHECKPOINT_TABLES
            from sqlalchemy import inspect
            with checkpoint_engine.begin() as connection:
                tables = set(inspect(connection).get_table_names())
                for name in CHECKPOINT_TABLES:
                    if name in tables:
                        connection.execute(text(f'DROP TABLE "{name}"'))
        initialize_database(db_engine)
    finally:
        if checkpoint_engine is not None:
            checkpoint_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清空 Codelin 账号、对话、工作区、索引、agent 状态及工作区文件。执行前停止后端。")
    parser.add_argument("--execute", action="store_true", help="明确执行破坏性重建；不传只显示目标")
    args = parser.parse_args()
    print("数据库：", engine.url.render_as_string(hide_password=True))
    print("状态库：", make_url(settings.checkpoint_db_url).render_as_string(hide_password=True))
    print("工作区目录：", Path(settings.workspace_root).resolve())
    if args.execute:
        reset_database(checkpoint_url=settings.checkpoint_db_url)
        from app.agents.checkpoints import ThreadedPostgresSaver
        with ThreadedPostgresSaver.from_conn_string(settings.checkpoint_db_url) as saver:
            saver.setup()
        print("旧数据及工作区文件已清空，新版数据库已初始化。请重新注册。")
    else:
        print("未执行清空；传入 --execute 才会重建。")
