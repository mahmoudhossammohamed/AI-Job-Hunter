"""SQLite storage (standard library). One table of jobs, one audit log."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from .config import DB_PATH, ensure_dirs
from .textutil import canonical_url, dedupe_key

STATUSES = ["Discovered", "Shortlisted", "CV Generated", "Awaiting Approval", "Submitted",
            "Interview", "Offer", "Rejected", "Withdrawn"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    canon_url TEXT,
    url TEXT, title TEXT, company TEXT, location TEXT, country TEXT, work_mode TEXT,
    description TEXT, employment_type TEXT, salary TEXT, source TEXT, platform TEXT,
    published_at TEXT, discovered_at TEXT,
    status TEXT DEFAULT 'Discovered',
    score INTEGER, band TEXT, category TEXT, variant TEXT,
    eligibility TEXT, needs_description INTEGER DEFAULT 0, explanation_json TEXT,
    cv_docx TEXT, cv_pdf TEXT, ats_report TEXT, letter_path TEXT,
    notes TEXT DEFAULT '', applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(canon_url);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    ensure_dirs()
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=None):
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def log(action, detail="", actor="system", path=None):
    with closing(connect(path)) as conn:
        conn.execute("INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
                     (now_iso(), actor, action, str(detail)[:2000]))
        conn.commit()


def find_duplicate(job, path=None):
    """Return the id of an existing job with the same key or the same URL, else None."""
    key = dedupe_key(job.get("company"), job.get("title"), job.get("url"))
    curl = canonical_url(job.get("url"))
    with closing(connect(path)) as conn:
        row = conn.execute("SELECT id FROM jobs WHERE dedupe_key=?", (key,)).fetchone()
        if row:
            return row["id"]
        if curl:
            row = conn.execute("SELECT id FROM jobs WHERE canon_url=?", (curl,)).fetchone()
            if row:
                return row["id"]
    return None


def insert_job(job, path=None):
    """Insert a job unless it is a duplicate. Returns (job_id, is_new)."""
    dup = find_duplicate(job, path)
    if dup:
        return dup, False
    key = dedupe_key(job.get("company"), job.get("title"), job.get("url"))
    cols = ["url", "title", "company", "location", "country", "work_mode", "description",
            "employment_type", "salary", "source", "platform", "published_at", "needs_description"]
    values = [job.get(c) for c in cols]
    with closing(connect(path)) as conn:
        cur = conn.execute(
            f"INSERT INTO jobs (dedupe_key, canon_url, discovered_at, {', '.join(cols)}) "
            f"VALUES (?,?,?,{', '.join('?' for _ in cols)})",
            [key, canonical_url(job.get("url")), now_iso()] + values)
        conn.commit()
        return cur.lastrowid, True


def get_job(job_id, path=None):
    with closing(connect(path)) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job(job_id, path=None, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with closing(connect(path)) as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", list(fields.values()) + [job_id])
        conn.commit()


def save_score(job_id, result, path=None):
    update_job(job_id, path, score=result["score"], band=result["band"], category=result["category"],
               variant=result["variant"], eligibility=result["eligibility"],
               needs_description=1 if result["needs_description"] else 0,
               explanation_json=json.dumps(result["explanation"], ensure_ascii=False))


def list_jobs(path=None, status=None, min_score=None, band=None, search=None, limit=500):
    q, args = "SELECT * FROM jobs WHERE 1=1", []
    if status:
        q += " AND status=?"; args.append(status)
    if min_score is not None:
        q += " AND COALESCE(score,0)>=?"; args.append(min_score)
    if band:
        q += " AND band=?"; args.append(band)
    if search:
        q += " AND (title LIKE ? OR company LIKE ?)"; args += [f"%{search}%"] * 2
    q += " ORDER BY COALESCE(score,0) DESC, discovered_at DESC LIMIT ?"
    args.append(limit)
    with closing(connect(path)) as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


def counts(path=None):
    with closing(connect(path)) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        today = conn.execute("SELECT COUNT(*) c FROM jobs WHERE substr(discovered_at,1,10)=?",
                             (now_iso()[:10],)).fetchone()["c"]
        bands = {r["band"] or "unscored": r["c"] for r in
                 conn.execute("SELECT band, COUNT(*) c FROM jobs GROUP BY band")}
        statuses = {r["status"]: r["c"] for r in
                    conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
    return {"total": total, "today": today, "bands": bands, "statuses": statuses}


def recent_logs(limit=200, path=None):
    with closing(connect(path)) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
