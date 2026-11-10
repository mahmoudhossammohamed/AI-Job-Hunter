"""Paths, settings and .env loading. Only standard library, so it is easy to read."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STORAGE = ROOT / "storage"
CV_DIR = STORAGE / "cvs"
INBOX_DIR = STORAGE / "inbox"
BACKUP_DIR = STORAGE / "backups"
LOG_DIR = ROOT / "logs"
DB_PATH = STORAGE / "jobhunter.db"
PROFILE_PATH = ROOT / "profile.json"
# Same profile with phone, email and links removed. Used when profile.json is missing,
# for example on Streamlit Cloud, where the real profile is never uploaded.
EXAMPLE_PROFILE_PATH = ROOT / "profile.example.json"


def ensure_dirs():
    for d in (STORAGE, CV_DIR, INBOX_DIR, INBOX_DIR / "processed", BACKUP_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    return load_json(CONFIG_DIR / "settings.json")


def save_settings(settings):
    with open(CONFIG_DIR / "settings.json", "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def load_sources():
    return load_json(CONFIG_DIR / "sources.json")


def is_demo():
    """Demo mode = no real profile.json on this machine."""
    return not PROFILE_PATH.exists()


def load_profile():
    return load_json(EXAMPLE_PROFILE_PATH if is_demo() else PROFILE_PATH)


def save_profile(profile):
    if is_demo():
        # Saving would create profile.json and silently switch demo mode off.
        raise PermissionError("The profile cannot be edited in the demo.")
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def load_env():
    """Read KEY=VALUE lines from .env into os.environ (existing variables win)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
