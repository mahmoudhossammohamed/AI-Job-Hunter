import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunter import cv_engine, db  # noqa: E402
from jobhunter.config import load_profile, load_settings  # noqa: E402


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway database and CV folder."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cv_engine, "CV_DIR", tmp_path / "cvs")
    (tmp_path / "cvs").mkdir()
    db.init_db()
    return tmp_path


def job(**kw):
    base = {"url": "https://example.com/jobs/1", "title": "Junior Software Engineer", "company": "Acme Egypt",
            "location": "Cairo, Egypt", "country": None, "work_mode": None, "description": "",
            "employment_type": None, "salary": None, "source": "test", "platform": "test",
            "published_at": None, "needs_description": 0}
    base.update(kw)
    return base
