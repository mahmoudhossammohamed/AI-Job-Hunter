"""Run one discovery pass: fetch, filter, dedupe, score, and optionally prepare CVs.

Run from the command line:  python -m jobhunter.search
"""
import re
from datetime import datetime, timedelta, timezone

from . import db
from .config import ensure_dirs, load_env, load_profile, load_settings, load_sources
from .scoring import location_info, score_job
from .sources import email_alerts, greenhouse, lever

ADAPTERS = {"greenhouse": greenhouse, "lever": lever, "email_alerts": email_alerts}
TRUSTED_NO_FILTER = ("email", "manual")  # alert emails and pasted jobs are already hand-picked


def _title_ok(job, settings):
    t = (job.get("title") or "").lower() + " "
    return any(k in t for k in settings["title_keywords"])


def _fresh_enough(job, settings):
    pub = job.get("published_at")
    if not pub:
        return True
    try:
        dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(days=settings["max_job_age_days"])


def _location_ok(job, settings):
    if not settings.get("keep_only_matching_locations", True):
        return True
    li = location_info(job, settings)
    return bool(li["country"] or li["remote"] or not li["has_location"])


def process_job(job, profile, settings):
    """Insert and score one job. Returns (job_id, is_new)."""
    job_id, is_new = db.insert_job(job)
    if is_new:
        db.save_score(job_id, score_job(job, profile, settings))
    return job_id, is_new


def run_search(prepare_cvs=True):
    ensure_dirs()
    load_env()
    db.init_db()
    settings, sources, profile = load_settings(), load_sources(), load_profile()
    summary = {"fetched": 0, "filtered": 0, "duplicates": 0, "new": 0, "excellent": 0, "good": 0,
               "prepared": 0, "errors": []}
    db.log("search_start", "manual or scheduled run", actor="search")

    new_ids = []
    for name, adapter in ADAPTERS.items():
        cfg = sources.get(name, {})
        if not cfg.get("enabled", False):
            continue
        jobs, errors = adapter.fetch(cfg, settings)
        summary["errors"] += errors
        for err in errors:
            db.log("source_error", err, actor="search")
        for job in jobs:
            summary["fetched"] += 1
            hand_picked = (job.get("source") or "").startswith(TRUSTED_NO_FILTER)
            if not hand_picked and not (_title_ok(job, settings) and _fresh_enough(job, settings)
                                        and _location_ok(job, settings)):
                summary["filtered"] += 1
                continue
            job_id, is_new = process_job(job, profile, settings)
            if is_new:
                summary["new"] += 1
                new_ids.append(job_id)
            else:
                summary["duplicates"] += 1

    for job_id in new_ids:
        row = db.get_job(job_id)
        if row["band"] in ("excellent", "good"):
            summary[row["band"]] += 1

    if prepare_cvs and settings.get("profile_verified"):
        from .cv_engine import prepare_application
        for job_id in new_ids:
            row = db.get_job(job_id)
            if (row["score"] or 0) >= settings["auto_prepare_min_score"] and not row["needs_description"]:
                prepare_application(job_id)
                summary["prepared"] += 1
    elif prepare_cvs and new_ids:
        db.log("cv_skipped", "profile not verified yet, no CVs prepared", actor="search")

    db.log("search_done", {k: v for k, v in summary.items() if k != "errors"}, actor="search")
    return summary


# ---------------------------------------------------------------- keyword search (dashboard Search page)

def parse_keywords(text):
    """'Data Analyst, Python Developer' -> ['Data Analyst', 'Python Developer']"""
    return [k.strip() for k in (text or "").split(",") if k.strip()]


def _has_word(haystack, word):
    # Whole word only, so "ai" does not match "maintain". Works for "c#" and "node.js" too.
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", haystack) is not None


def matches_keyword(job, keyword):
    """Every word of the keyword appears in the title or the description."""
    hay = f"{job.get('title') or ''} {job.get('description') or ''}".lower()
    return all(_has_word(hay, w) for w in keyword.lower().split())


def matches_location(job, location, settings, include_remote=True):
    """Empty location box = everywhere. 'Egypt' also matches Cairo, Giza... from settings.json."""
    wanted = (location or "").strip().lower()
    if not wanted:
        return True
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # alert-email jobs have no location; the alert itself was already for your area
    if include_remote and "remote" in loc:
        return True
    aliases = next((v for k, v in settings["locations"].items() if k.lower() == wanted), [wanted])
    return any(a.lower() in loc for a in aliases)


def keyword_search(keywords, location="", include_remote=True):
    """Refresh all sources, save new matches, then return every saved job that matches.

    Returns (rows, errors). Each row is one job with the first keyword it matched.
    Unlike run_search this does not prepare CVs, so it stays fast. Use the Jobs page for that.
    """
    ensure_dirs()
    load_env()
    db.init_db()
    settings, sources, profile = load_settings(), load_sources(), load_profile()
    errors, new_ids = [], set()
    db.log("keyword_search", f"{keywords} in '{location}'", actor="user")

    for name, adapter in ADAPTERS.items():
        cfg = sources.get(name, {})
        if not cfg.get("enabled", False):
            continue
        jobs, errs = adapter.fetch(cfg, settings)
        errors += errs
        for job in jobs:
            hand_picked = (job.get("source") or "").startswith(TRUSTED_NO_FILTER)
            if not hand_picked and not (_fresh_enough(job, settings)
                                        and any(matches_keyword(job, k) for k in keywords)
                                        and matches_location(job, location, settings, include_remote)):
                continue
            job_id, is_new = process_job(job, profile, settings)
            if is_new:
                new_ids.add(job_id)

    # Search everything saved so far, so jobs from older alert emails and pasted links show up too.
    rows = []
    for job in db.list_jobs(limit=100_000):
        if not matches_location(job, location, settings, include_remote):
            continue
        keyword = next((k for k in keywords if matches_keyword(job, k)), None)
        if keyword:
            rows.append({**job, "keyword": keyword, "is_new": job["id"] in new_ids})
    return rows, errors


if __name__ == "__main__":
    print(run_search())
