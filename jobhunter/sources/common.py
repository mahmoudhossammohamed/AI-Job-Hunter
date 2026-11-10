"""Shared helpers for source adapters: polite HTTP and a common job shape."""
import time

import requests

JOB_FIELDS = ["url", "title", "company", "location", "country", "work_mode", "description",
              "employment_type", "salary", "source", "platform", "published_at", "needs_description"]


def make_job(**kw):
    job = {f: None for f in JOB_FIELDS}
    job.update(kw)
    job["needs_description"] = 1 if len((job.get("description") or "").strip()) < 80 else 0
    return job


def polite_get(url, settings, params=None, accept="application/json"):
    """GET with a clear User-Agent, a timeout and a delay after the call.

    We always send our real User-Agent. We never pretend to be a browser.
    """
    http = settings["http"]
    resp = requests.get(url, params=params, timeout=http["timeout"],
                        headers={"User-Agent": http["user_agent"], "Accept": accept})
    time.sleep(http["delay_seconds"])
    return resp
