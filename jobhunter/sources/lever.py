"""Lever public postings API (GET, no login). Add company slugs in config/sources.json.

A slug is the last part of a company's Lever URL: jobs.lever.co/<slug>
"""
from datetime import datetime, timezone

from .common import make_job, polite_get

API = "https://api.lever.co/v0/postings/{slug}"


def parse(slug, payload):
    jobs = []
    for item in payload if isinstance(payload, list) else []:
        cats = item.get("categories") or {}
        created = item.get("createdAt")
        published = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat(timespec="seconds")
                     if created else None)
        jobs.append(make_job(
            url=item.get("hostedUrl"),
            title=item.get("text"),
            company=slug,
            location=cats.get("location") or "",
            work_mode=(item.get("workplaceType") or None),
            description=item.get("descriptionPlain") or "",
            employment_type=cats.get("commitment"),
            source=f"lever:{slug}",
            platform="lever",
            published_at=published,
        ))
    return jobs


def fetch(source_cfg, settings):
    out, errors = [], []
    for slug in source_cfg.get("companies", []):
        try:
            resp = polite_get(API.format(slug=slug), settings, params={"mode": "json"})
            if resp.status_code != 200:
                errors.append(f"lever:{slug} HTTP {resp.status_code}")
                continue
            out += parse(slug, resp.json())
        except Exception as exc:
            errors.append(f"lever:{slug} {exc}")
    return out, errors
