"""Greenhouse public Job Board API (GET, no login). Add board tokens in config/sources.json.

A token is the last part of a company's board URL: boards.greenhouse.io/<token>
"""
from ..textutil import html_to_text
from .common import make_job, polite_get

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def parse(token, payload):
    jobs = []
    for item in payload.get("jobs", []):
        loc = (item.get("location") or {}).get("name") or ""
        jobs.append(make_job(
            url=item.get("absolute_url"),
            title=item.get("title"),
            company=item.get("company_name") or token,
            location=loc,
            work_mode="remote" if "remote" in loc.lower() else None,
            description=html_to_text(item.get("content", "")),
            source=f"greenhouse:{token}",
            platform="greenhouse",
            published_at=item.get("updated_at") or item.get("first_published"),
        ))
    return jobs


def fetch(source_cfg, settings):
    out, errors = [], []
    for token in source_cfg.get("boards", []):
        try:
            resp = polite_get(API.format(token=token), settings, params={"content": "true"})
            if resp.status_code != 200:
                errors.append(f"greenhouse:{token} HTTP {resp.status_code}")
                continue
            out += parse(token, resp.json())
        except Exception as exc:  # network or JSON problems must not stop other sources
            errors.append(f"greenhouse:{token} {exc}")
    return out, errors
