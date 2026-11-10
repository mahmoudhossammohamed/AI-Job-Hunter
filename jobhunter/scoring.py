"""Deterministic 0-100 job scoring. No AI, no network, no tokens.

Every point is explained in result["explanation"]. Weights and keyword lists live in
config/scoring.json and config/skills.json so you can tune them without touching code.
"""
import re

from .config import CONFIG_DIR, load_json, load_profile, load_settings
from .skills import extract_skills, profile_skill_set

SENIOR_RE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|head of|director|vp|vice president|team leader)\b", re.I)
JUNIOR_RE = re.compile(r"\b(junior|jr\.?|graduate|fresh(?:er)?|entry[- ]level|intern(?:ship)?|trainee|early[- ]career)\b", re.I)
PREF_MARKER_RE = re.compile(r"(nice to have|preferred|bonus|a plus|is a plus|good to have|desirable|advantageous|optional)", re.I)
HEADING_RE = re.compile(r"^(requirements?|responsibilities|qualifications?|what you('|’)ll (do|need)|about (you|the role)|skills?|experience|duties|who you are)\b", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)", re.I)
MASTERS_RE = re.compile(r"\b(master'?s|m\.?sc|ph\.?d|doctorate)\b", re.I)
DEGREE_RE = re.compile(r"\b(bachelor|b\.?sc|computer science|degree|engineering)\b", re.I)
RESTRICT_RE = re.compile(r"(authori[sz]ed to work|work authori[sz]ation|right to work|us citizen|u\.s\. citizen|security clearance|"
                         r"must (be|reside|live)( located| based)? (in|within)|no visa sponsorship|unable to sponsor|"
                         r"eligible to work in|(us|uk|eu|europe)[- ]only)", re.I)


def _cfg():
    return load_json(CONFIG_DIR / "scoring.json")


def band_for(score, thresholds):
    if score >= thresholds["excellent"]:
        return "excellent"
    if score >= thresholds["good"]:
        return "good"
    if score >= thresholds["possible"]:
        return "possible"
    return "archive"


def classify(job, cfg):
    """Pick a job category from the title, then fall back to the description for generic titles."""
    title = (job.get("title") or "").lower()
    category = "other"
    for cat, pattern in cfg["title_patterns"]:
        if re.search(pattern, title, re.I):
            category = cat
            break
    if category in ("software", "other"):
        body = extract_skills((job.get("title") or "") + "\n" + (job.get("description") or ""))
        if body & {"doxis", "opentext", "ibm baw", "filenet", "bpmn"}:
            category = "ecm_bpm"
        elif body & {"java", "spring boot", "java ee"} and not body & {"node.js", "express"}:
            category = "java"
        elif body & {"node.js", "express", "nestjs"} and not body & {"java", "spring boot"}:
            category = "node"
    return category, cfg["category_to_variant"][category]


def split_requirements(title, description):
    """Split skills into required and preferred, line by line (documented heuristic)."""
    required = set(extract_skills(title))
    preferred_only, in_pref = set(), False
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        is_heading = len(line) <= 60 and (line.endswith(":") or HEADING_RE.match(line))
        if is_heading:
            in_pref = bool(PREF_MARKER_RE.search(line))
            continue
        skills = extract_skills(line)
        if in_pref or PREF_MARKER_RE.search(line):
            preferred_only |= skills
        else:
            required |= skills
    return required, preferred_only - required


def years_required(description):
    """Highest 'N years ... experience' lower bound found, or None."""
    best = None
    for m in YEARS_RE.finditer(description or ""):
        window = (description or "")[m.start(): m.end() + 60].lower()
        if "experience" in window or "exp" in window:
            lo = int(m.group(1))
            if lo <= 25:
                best = lo if best is None else max(best, lo)
    return best


def location_info(job, settings):
    loc = (job.get("location") or "").lower()
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    mode = (job.get("work_mode") or "").lower()
    remote = "remote" in loc or "remote" in title or mode == "remote" or "work from home" in loc
    hybrid = "hybrid" in loc or "hybrid" in title or mode == "hybrid"
    country = None
    for name, terms in settings["locations"].items():
        if any(t in loc for t in terms):
            country = name
            break
    if not country and not loc:
        for name, terms in settings["locations"].items():
            if any(t in desc[:400] for t in terms):
                country = name
                break
    return {"remote": remote, "hybrid": hybrid, "country": country, "has_location": bool(loc)}


def score_job(job, profile=None, settings=None):
    profile = profile or load_profile()
    settings = settings or load_settings()
    cfg = _cfg()
    w = cfg["weights"]
    title = job.get("title") or ""
    desc = job.get("description") or ""
    notes, caps = [], []

    category, variant = classify(job, cfg)
    mine = profile_skill_set(profile)
    required, preferred = split_requirements(title, desc)
    needs_description = len(desc.strip()) < 80
    if needs_description:
        caps.append((69, "No job description available, so requirements could not be verified."))

    # 1. Skills (30)
    matched_req = sorted(required & mine)
    missing_req = sorted(required - mine)
    matched_pref = sorted(preferred & mine)
    missing_pref = sorted(preferred - mine)
    if required:
        req_frac = len(matched_req) / len(required)
        pref_frac = (len(matched_pref) / len(preferred)) if preferred else None
        frac = req_frac if pref_frac is None else 0.85 * req_frac + 0.15 * pref_frac
        # Excellent needs real coverage of the mandatory skills, whatever the other components say.
        if req_frac < 0.5:
            caps.append((69, f"Only {len(matched_req)} of {len(required)} required skills matched."))
        elif req_frac < 0.9:
            caps.append((84, f"Only {len(matched_req)} of {len(required)} required skills matched, so not rated excellent."))
    else:
        frac = 0.5
        notes.append("No known skills detected in the posting; skills score is neutral.")
    pts_skills = w["skills"] * frac

    # 2. Seniority and experience (20)
    senior = bool(SENIOR_RE.search(title))
    junior = bool(JUNIOR_RE.search(title + " " + desc[:600]))
    years = years_required(desc)
    if senior:
        pts_sen = 0
        caps.append((54, "Senior-level title."))
    elif years is not None and years >= 4:
        pts_sen = 0
        caps.append((54, f"Asks for {years}+ years of experience."))
    elif years == 3:
        pts_sen = 6
        caps.append((69, "Asks for 3 years of experience."))
    elif years == 2:
        pts_sen = 15
    elif years in (0, 1):
        pts_sen = w["seniority"]
    elif junior:
        pts_sen = w["seniority"]
    else:
        pts_sen = 14
        notes.append("No explicit seniority signal; assumed mid-fit.")

    # 3. Responsibilities (15)
    kws = cfg["responsibility_keywords"].get(category, cfg["responsibility_keywords"]["other"])
    low = desc.lower()
    hits = [k for k in kws if k in low]
    pts_resp = w["responsibilities"] * (min(len(hits), 5) / 5) if not needs_description else w["responsibilities"] * 0.5

    # 4. Education (10)
    if MASTERS_RE.search(desc):
        pts_edu = 3
        notes.append("Mentions a master's/PhD; verify whether it is required.")
    elif DEGREE_RE.search(desc):
        pts_edu = w["education"]
    else:
        pts_edu = 8

    # 5. Role relevance (10)
    pts_role = w["role_relevance"] * cfg["category_priority"].get(category, 0.2)

    # 6. Location and eligibility (10)
    li = location_info(job, settings)
    eligibility = "ok"
    restrict = bool(RESTRICT_RE.search(desc))
    if li["country"]:
        pts_loc = w["location"]
    elif li["remote"]:
        pts_loc = w["location"] * 0.5
        if restrict and "egypt" not in low:
            eligibility = "restricted"
            caps.append((54, "Remote role with residency or work-authorization limits that do not mention Egypt."))
        else:
            eligibility = "unknown"
            notes.append("Remote role: hiring from Egypt is not confirmed.")
    elif not li["has_location"]:
        pts_loc = w["location"] * 0.6
        eligibility = "unknown"
        notes.append("No location given.")
    else:
        pts_loc = w["location"] * 0.2
        eligibility = "unknown"
        notes.append("Location is outside the configured countries.")
    if eligibility == "unknown":
        caps.append((84, "Eligibility unknown, so this cannot rate as excellent."))

    # 7. Other (5): required foreign language
    pts_other = w["other"]
    langs = [l for l in cfg["foreign_languages"]
             if re.search(rf"\b{l}\b[^.\n]{{0,40}}(fluen|proficien|native|required)|(fluen|proficien|native)[^.\n]{{0,30}}\b{l}\b", low)]
    if langs:
        pts_other = 0
        notes.append("Asks for language(s) not in your profile: " + ", ".join(langs))

    total = pts_skills + pts_sen + pts_resp + pts_edu + pts_role + pts_loc + pts_other
    score = int(round(total))
    cap_notes = []
    for cap, why in caps:
        if score > cap:
            score = cap
            cap_notes.append(f"Score capped at {cap}: {why}")
        else:
            cap_notes.append(why)
    notes += cap_notes

    band = band_for(score, settings["thresholds"])
    explanation = {
        "category": category,
        "components": {
            "skills": [round(pts_skills, 1), w["skills"]],
            "seniority": [round(pts_sen, 1), w["seniority"]],
            "responsibilities": [round(pts_resp, 1), w["responsibilities"]],
            "education": [round(pts_edu, 1), w["education"]],
            "role_relevance": [round(pts_role, 1), w["role_relevance"]],
            "location": [round(pts_loc, 1), w["location"]],
            "other": [round(pts_other, 1), w["other"]],
        },
        "matched_required": matched_req,
        "missing_required": missing_req,
        "matched_preferred": matched_pref,
        "missing_preferred": missing_pref,
        "years_required": years,
        "senior_title": senior,
        "responsibility_hits": hits,
        "eligibility": eligibility,
        "notes": notes,
    }
    return {"score": score, "band": band, "category": category, "variant": variant,
            "eligibility": eligibility, "needs_description": needs_description,
            "explanation": explanation}
