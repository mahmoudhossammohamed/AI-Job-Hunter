"""Smoke test: every dashboard page renders without an exception, against a throwaway database."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jobhunter import cv_engine, db

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
PAGES = ["Overview", "Search", "Jobs", "Add job", "Profile", "Settings", "Logs"]


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(cv_engine, "CV_DIR", tmp_path / "cvs")
    (tmp_path / "cvs").mkdir()
    db.init_db()
    from conftest import job
    from jobhunter.config import load_profile, load_settings
    from jobhunter.scoring import score_job
    j = job(title="Junior ECM Developer", description="Requirements:\n- IBM BAW, FileNet, BPMN, Java\n- Fresh graduate\n" * 2)
    jid, _ = db.insert_job(j)
    db.save_score(jid, score_job(j, load_profile(), load_settings()))
    stub = job(title="Junior Node Developer", url="https://wuzzuf.net/jobs/p/x", company="", description="", needs_description=1)
    sid, _ = db.insert_job(stub)
    db.save_score(sid, score_job(stub, load_profile(), load_settings()))
    return tmp_path


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(seeded, page):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, (page, at.exception)


def _open(page):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    return at


def test_search_page_shows_table_and_csv(seeded, monkeypatch):
    from jobhunter import search
    monkeypatch.setattr(search, "load_sources", lambda: {})  # no network, search saved jobs only
    at = _open("Search")
    at.text_input[0].set_value("ECM Developer")
    at.button[0].click().run()  # the form's Search button
    assert not at.exception, at.exception
    assert "Found 1 jobs" in at.success[0].value
    assert len(at.dataframe) == 1


def test_add_job_fetch_fills_form_and_saves(seeded, monkeypatch):
    from conftest import job
    from jobhunter import url_import
    fetched = job(title="Junior BPM Developer", company="Barq", url="https://barq.example/j/1",
                  description="IBM BAW and Java " * 10, salary="20000 EGP", source="url:barq.example")
    monkeypatch.setattr(url_import, "import_from_url", lambda link, s: (fetched, "Read from the page."))
    at = _open("Add job")
    at.text_input[0].set_value("https://barq.example/j/1")
    at.button[0].click().run()  # Fetch details
    assert not at.exception, at.exception
    assert at.text_input(key="add_title").value == "Junior BPM Developer"
    assert any("Salary: 20000 EGP" in c.value for c in at.caption)
    at.button[1].click().run()  # Add and score
    assert not at.exception, at.exception
    saved = [j for j in db.list_jobs() if j["title"] == "Junior BPM Developer"][0]
    assert saved["salary"] == "20000 EGP" and saved["source"] == "url:barq.example"
