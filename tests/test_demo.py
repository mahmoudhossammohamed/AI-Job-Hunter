"""Demo mode (Streamlit Cloud): no profile.json, contact details hidden, nothing editable."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jobhunter import config, cv_engine, db

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")


def test_example_profile_has_no_real_contact_details():
    if not config.PROFILE_PATH.exists():
        pytest.skip("real profile.json not on this machine")
    real = config.load_json(config.PROFILE_PATH)["contact"]
    example_text = config.EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8")
    for key in ("phone", "email", "linkedin", "github"):
        assert real[key] not in example_text, key


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROFILE_PATH", tmp_path / "missing-profile.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(cv_engine, "CV_DIR", tmp_path / "cvs")
    (tmp_path / "cvs").mkdir()
    db.init_db()
    return tmp_path


def test_demo_loads_example_and_blocks_saving(demo):
    assert config.is_demo()
    profile = config.load_profile()
    assert profile["contact"]["email"] == "(hidden in demo)"
    with pytest.raises(PermissionError):
        config.save_profile(profile)
    assert not config.PROFILE_PATH.exists()


@pytest.mark.parametrize("page", ["Overview", "Search", "Jobs", "Add job", "Profile", "Settings", "Logs"])
def test_demo_pages_render_read_only(demo, page):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, (page, at.exception)
    assert "Demo version" in at.info[0].value
    labels = [b.label for b in at.button]
    assert "Save settings" not in labels and "Save profile.json" not in labels
