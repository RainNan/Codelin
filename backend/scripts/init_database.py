"""Run from backend: python scripts/init_database.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.initialize import initialize_database

if __name__ == "__main__":
    initialize_database()
    print("业务数据库初始化完成；已有数据未清空。")
