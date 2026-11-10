"""Copy the database to storage/backups (keeps the newest 14). Run: python -m jobhunter.backup"""
import sqlite3
from datetime import datetime

from .config import BACKUP_DIR, DB_PATH, ensure_dirs


def backup(keep=14):
    ensure_dirs()
    if not DB_PATH.exists():
        return None
    dest = BACKUP_DIR / f"jobhunter-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(str(DB_PATH)), sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)  # safe even while the dashboard is open
    src.close()
    dst.close()
    for old in sorted(BACKUP_DIR.glob("jobhunter-*.db"))[:-keep]:
        old.unlink()
    return dest


if __name__ == "__main__":
    print(backup() or "No database yet.")
