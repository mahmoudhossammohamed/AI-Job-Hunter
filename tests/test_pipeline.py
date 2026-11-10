import json
import re
import zipfile

import pytest
from conftest import job
from docx import Document

from jobhunter import cv_engine, db, gemini
from jobhunter.config import save_settings
from jobhunter.scoring import score_job
from jobhunter.skills import extract_skills, profile_skill_set
from jobhunter.sources import email_alerts, greenhouse, lever
from jobhunter.textutil import dedupe_key, html_to_text


# ---------- duplicates ----------

def test_duplicate_detection_across_sources(tmp_db):
    a = job(company="Acme Egypt Ltd", title="Junior Developer (Remote)", url="https://a.com/1?utm=x")
    b = job(company="ACME", title="junior developer", url="https://b.com/zzz", source="other")
    c = job(company="Acme", title="Different Role", url="https://a.com/1")  # same URL as a
    id1, new1 = db.insert_job(a)
    id2, new2 = db.insert_job(b)
    id3, new3 = db.insert_job(c)
    assert new1 and not new2 and not new3
    assert id1 == id2 == id3
    assert db.counts()["total"] == 1


def test_company_less_stub_dedupes_by_url():
    assert dedupe_key("", "A", "https://x.com/jobs/1?a=1") == dedupe_key("", "B", "https://x.com/jobs/1")


# ---------- CV generation ----------

def _prepare(tmp_db, profile, settings, jd):
    settings["profile_verified"] = True
    j = job(title="Junior ECM Developer", description=jd)
    job_id, _ = db.insert_job(j)
    db.save_score(job_id, score_job(j, profile, settings))
    return job_id


def test_cv_files_created_and_valid(tmp_db, profile, settings, monkeypatch):
    monkeypatch.setattr(cv_engine, "load_settings", lambda: {**settings, "profile_verified": True})
    job_id = _prepare(tmp_db, profile, settings, "Requirements:\n- IBM BAW, FileNet, BPMN, Java\n- Fresh graduate")
    out = cv_engine.prepare_application(job_id)
    assert out["pdf"].read_bytes().startswith(b"%PDF")
    d = Document(str(out["docx"]))
    assert len(d.tables) == 0  # ATS friendly: no tables
    assert db.get_job(job_id)["status"] == "CV Generated"
    assert "not the employer's ATS score" in out["ats"].read_text(encoding="utf-8")
    assert "Dear Hiring Team" in out["letter"].read_text(encoding="utf-8")


def test_prepare_blocked_until_profile_verified(tmp_db, profile, settings, monkeypatch):
    monkeypatch.setattr(cv_engine, "load_settings", lambda: {**settings, "profile_verified": False})
    j = job(description="Java SQL " * 20)
    job_id, _ = db.insert_job(j)
    db.save_score(job_id, score_job(j, profile, settings))
    with pytest.raises(PermissionError):
        cv_engine.prepare_application(job_id)


@pytest.mark.parametrize("variant", ["ecm_bpm", "java", "node", "fullstack", "software", "it_support"])
def test_every_variant_only_contains_verified_facts(profile, variant):
    cv = cv_engine.build_cv(profile, variant)
    # every skill shown is a skill from profile.json
    all_skills = {s for g in profile["skills"].values() for s in g}
    shown = {s for items in cv["skills"].values() for s in items}
    assert shown == all_skills  # reordered, none added, none dropped
    # dates and employers are untouched
    assert [(e["org"], e["start"], e["end"]) for e in cv["experience"]] == \
           [(e["org"], e["start"], e["end"]) for e in profile["experience"]]
    # skills named in summary that are not in the profile would be a fabrication
    text = cv_engine.cv_plain_text(cv)
    mine = profile_skill_set(profile)
    claimed = extract_skills(cv["summary"])
    assert claimed <= mine, claimed - mine
    assert "React" not in text and "Groovy" not in text and "Kubernetes" not in text


def test_military_service_date_is_july_2024(profile):
    m = next(e for e in profile["experience"] if e["id"] == "military")
    assert (m["start"], m["end"]) == ("Jul 2024", "Dec 2025")


# ---------- Gemini privacy ----------

def test_gemini_prompt_has_no_contact_details(profile):
    prompt = gemini.build_prompt(job(title="Backend Dev", description="Java"), profile, "java")
    c = profile["contact"]
    for secret in (c["phone"], c["email"], c["linkedin"], c["github"]):
        assert secret not in prompt
    assert not gemini.CONTACT_RE.search(prompt)


def test_gemini_off_by_default_returns_none(profile, settings):
    text, msg = gemini.generate_letter(job(), profile, "java", settings)
    assert text is None and "off" in msg.lower()


# ---------- source parsers (mock data, no network) ----------

def test_greenhouse_parse():
    payload = {"jobs": [{"absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "title": "Junior Backend Engineer",
                         "location": {"name": "Cairo, Egypt"}, "updated_at": "2026-11-01T10:00:00Z",
                         "content": "&lt;p&gt;Build &lt;b&gt;Java&lt;/b&gt; services&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"}]}
    jobs = greenhouse.parse("acme", payload)
    assert jobs[0]["title"] == "Junior Backend Engineer" and "Java services" in jobs[0]["description"]
    assert "- SQL" in jobs[0]["description"] and "<" not in jobs[0]["description"]


def test_lever_parse():
    payload = [{"text": "Node.js Developer", "hostedUrl": "https://jobs.lever.co/acme/1", "createdAt": 1762000000000,
                "categories": {"location": "Remote", "commitment": "Full-time"}, "descriptionPlain": "Node.js and Express " * 10}]
    j = lever.parse("acme", payload)[0]
    assert j["employment_type"] == "Full-time" and j["published_at"].startswith("2025-")


def test_email_alert_parsing(tmp_path):
    (tmp_path / "alert.eml").write_text(
        "From: jobs@linkedin.com\nSubject: new jobs\nMIME-Version: 1.0\nContent-Type: text/html; charset=utf-8\n\n"
        '<html><body><a href="https://www.linkedin.com/comm/jobs/view/123456789?trk=abc">Junior Java Developer</a>'
        '<a href="https://www.linkedin.com/comm/jobs/view/123456789?trk=zzz">View job</a>'
        '<a href="https://wuzzuf.net/jobs/p/abc-Junior-Node-Developer-Cairo-Egypt">Junior Node Developer</a>'
        '<a href="https://example.com/unsubscribe">Unsubscribe</a></body></html>', encoding="utf-8")
    (tmp_path / "note.txt").write_text("Backend Engineer\nhttps://www.indeed.com/viewjob?jk=abc123\n", encoding="utf-8")
    jobs, errors = email_alerts.fetch({}, {}, inbox=tmp_path)
    assert not errors
    titles = sorted(j["title"] for j in jobs)
    assert titles == ["Backend Engineer", "Junior Java Developer", "Junior Node Developer"]
    assert all(j["needs_description"] == 1 for j in jobs)
    assert (tmp_path / "processed" / "alert.eml").exists()


def test_html_to_text_handles_escaped_html():
    assert html_to_text("&lt;p&gt;Hello&lt;br&gt;World&lt;/p&gt;") == "Hello\nWorld"


# ---------- end to end ----------

def test_search_run_with_mock_sources(tmp_db, profile, settings, monkeypatch):
    from jobhunter import search
    mock_jobs = [
        job(title="Junior ECM Developer", description="Requirements:\n- IBM BAW, FileNet, BPMN, Java\n- Fresh graduate\n" * 2),
        job(title="Junior ECM Developer", company="Acme Egypt Ltd", url="https://other.com/x", description="dup"),  # duplicate
        job(title="Chef de Cuisine", description="Cook food " * 20),  # filtered by title
        job(title="Junior Java Developer", company="Berlin GmbH", location="Berlin, Germany", url="https://x.com/9",
            description="Java " * 30),  # filtered by location
    ]
    monkeypatch.setattr(search, "load_settings", lambda: {**settings, "profile_verified": False})
    monkeypatch.setattr(search, "load_sources", lambda: {"greenhouse": {"enabled": True, "boards": []}})
    monkeypatch.setattr(search.greenhouse, "fetch", lambda cfg, s: (mock_jobs, ["greenhouse:broken HTTP 404"]))
    summary = search.run_search(prepare_cvs=True)
    assert summary["fetched"] == 4 and summary["new"] == 1 and summary["duplicates"] == 1 and summary["filtered"] == 2
    assert summary["errors"] == ["greenhouse:broken HTTP 404"]
    assert db.counts()["total"] == 1
    assert any(l["action"] == "source_error" for l in db.recent_logs())
