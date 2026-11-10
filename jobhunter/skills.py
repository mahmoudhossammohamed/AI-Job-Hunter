"""Skill extraction: find known skills in text using config/skills.json (no AI)."""
import re
from functools import lru_cache

from .config import CONFIG_DIR, load_json


@lru_cache(maxsize=1)
def _compiled():
    table = load_json(CONFIG_DIR / "skills.json")
    out = {}
    for canonical, aliases in table.items():
        pats = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", re.I) for a in aliases]
        out[canonical] = pats
    return out


def extract_skills(text):
    """Return the set of canonical skills mentioned in text."""
    found = set()
    if not text:
        return found
    for canonical, pats in _compiled().items():
        if any(p.search(text) for p in pats):
            found.add(canonical)
    return found


def profile_skill_set(profile):
    """Canonical skills the user really has, taken from profile.json skills only."""
    table = load_json(CONFIG_DIR / "skills.json")
    mine = set()
    for group in profile["skills"].values():
        for skill in group:
            mine |= extract_skills(skill)
            low = skill.lower()
            if low in table:  # e.g. "Express" is a canonical key itself
                mine.add(low)
    mine |= {k for k in profile.get("extra_skill_keys", []) if k in table}
    return mine
