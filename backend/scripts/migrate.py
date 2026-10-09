"""Run from backend: python scripts/migrate.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.migrate import upgrade_database

if __name__ == "__main__":
    upgrade_database()
    print("Database migration complete; existing workspace files preserved.")
