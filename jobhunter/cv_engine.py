"""Template-based CV tailoring. Deterministic: it can only reorder and select what is in profile.json.

Pipeline for one job:  pick variant -> build a structured CV -> render DOCX and PDF from the
same structure -> write an ATS-alignment report -> write a cover letter.
"""
import json
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

from . import db
from .config import CV_DIR, ensure_dirs, load_profile, load_settings
from .skills import extract_skills, profile_skill_set


# ---------- 1. Build the structured CV ----------

def order_skills(profile, variant):
    """Reorder skill groups and put the variant's priority skills first inside each group."""
    priority = profile["variant_skill_priority"].get(variant, [])
    groups = {}
    for group in profile["variant_skill_group_order"][variant]:
        items = profile["skills"][group]
        first = [s for s in priority if s in items]
        rest = [s for s in items if s not in first]
        groups[group] = first + rest
    return groups


def build_cv(profile, variant):
    """Return a plain dict describing the CV. Every string comes from profile.json."""
    proj_by_id = {p["id"]: p for p in profile["projects"]}
    order = profile["variant_project_order"][variant][: profile["variant_max_projects"]]
    c = profile["contact"]
    return {
        "name": profile["name"],
        "headline": profile["headline"],
        "contact_line": " | ".join([c["location"], c["phone"], c["email"]]),
        "links_line": " | ".join([f"LinkedIn: {c['linkedin']}", f"GitHub: {c['github']}"]),
        "summary": profile["summaries"][variant],
        "skills": order_skills(profile, variant),
        "experience": profile["experience"],
        "projects": [proj_by_id[i] for i in order],
        "education": profile["education"],
        "scholarships": profile["scholarships"],
    }


def cv_plain_text(cv):
    parts = [cv["name"], cv["headline"], cv["summary"]]
    for group, items in cv["skills"].items():
        parts.append(f"{group}: {', '.join(items)}")
    for e in cv["experience"]:
        parts += [e["title"], e["org"]] + e["bullets"]
    for p in cv["projects"]:
        parts += [p["name"], p["tech"]] + p["bullets"]
    return "\n".join(parts)


# ---------- 2. Render DOCX (single column, no tables, no graphics) ----------

def render_docx(cv, path):
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = Pt(54)
        s.top_margin = s.bottom_margin = Pt(46)

    def para(text, bold=False, size=None, align=None, space_after=2):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        if align:
            p.alignment = align
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.space_before = Pt(0)
        return p

    def heading(text):
        p = para(text.upper(), bold=True, size=11, space_after=3)
        p.paragraph_format.space_before = Pt(8)

    def bullet(text):
        p = doc.add_paragraph(text, style="List Bullet")
        p.paragraph_format.space_after = Pt(1)

    para(cv["name"], bold=True, size=18, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(cv["headline"], size=11, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(cv["contact_line"], align=WD_ALIGN_PARAGRAPH.CENTER)
    para(cv["links_line"], align=WD_ALIGN_PARAGRAPH.CENTER)

    heading("Professional Summary")
    para(cv["summary"])

    heading("Technical Skills")
    for group, items in cv["skills"].items():
        p = doc.add_paragraph()
        p.add_run(f"{group}: ").bold = True
        p.add_run(", ".join(items))
        p.paragraph_format.space_after = Pt(1)

    heading("Professional Experience")
    for e in cv["experience"]:
        para(f"{e['title']} | {e['start']} - {e['end']}", bold=True, space_after=0)
        para(e["org"], space_after=1)
        for b in e["bullets"]:
            bullet(b)

    heading("Projects")
    for p in cv["projects"]:
        para(f"{p['name']} | {p['tech']}", bold=True, space_after=1)
        for b in p["bullets"]:
            bullet(b)

    heading("Education")
    for e in cv["education"]:
        detail = f" | {e['detail']}" if e["detail"] else ""
        para(f"{e['title']} | {e['start']} - {e['end']}", bold=True, space_after=0)
        para(f"{e['org']}{detail}", space_after=2)

    heading("Scholarships and Training")
    for s in cv["scholarships"]:
        para(s["title"], bold=True, space_after=1)
        for b in s["bullets"]:
            bullet(b)

    doc.save(str(path))


# ---------- 3. Render PDF (reportlab: pure Python, works on any Windows PC, no Word needed) ----------

def render_pdf(cv, path):
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.6, leading=12.2)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    center = ParagraphStyle("center", parent=base, alignment=1)
    name = ParagraphStyle("name", parent=center, fontName="Helvetica-Bold", fontSize=18, leading=22)
    head = ParagraphStyle("head", parent=bold, fontSize=10.5, spaceBefore=8, spaceAfter=3)
    bul = ParagraphStyle("bul", parent=base, leftIndent=12, bulletIndent=2, spaceAfter=1)

    story = [Paragraph(escape(cv["name"]), name), Paragraph(escape(cv["headline"]), center),
             Paragraph(escape(cv["contact_line"]), center), Paragraph(escape(cv["links_line"]), center)]

    def h(text):
        story.append(Paragraph(escape(text.upper()), head))

    h("Professional Summary")
    story.append(Paragraph(escape(cv["summary"]), base))
    h("Technical Skills")
    for group, items in cv["skills"].items():
        story.append(Paragraph(f"<b>{escape(group)}:</b> {escape(', '.join(items))}", base))
    h("Professional Experience")
    for e in cv["experience"]:
        story.append(Paragraph(escape(f"{e['title']} | {e['start']} - {e['end']}"), bold))
        story.append(Paragraph(escape(e["org"]), base))
        for b in e["bullets"]:
            story.append(Paragraph(escape(b), bul, bulletText="•"))
        story.append(Spacer(1, 2))
    h("Projects")
    for p in cv["projects"]:
        story.append(Paragraph(escape(f"{p['name']} | {p['tech']}"), bold))
        for b in p["bullets"]:
            story.append(Paragraph(escape(b), bul, bulletText="•"))
        story.append(Spacer(1, 2))
    h("Education")
    for e in cv["education"]:
        detail = f" | {e['detail']}" if e["detail"] else ""
        story.append(Paragraph(escape(f"{e['title']} | {e['start']} - {e['end']}"), bold))
        story.append(Paragraph(escape(f"{e['org']}{detail}"), base))
    h("Scholarships and Training")
    for s in cv["scholarships"]:
        story.append(Paragraph(escape(s["title"]), bold))
        for b in s["bullets"]:
            story.append(Paragraph(escape(b), bul, bulletText="•"))

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm,
                      title=f"{cv['name']} CV", author=cv["name"]).build(story)


# ---------- 4. ATS-alignment report (an estimate, not the employer's real ATS) ----------

def ats_report(job, explanation, profile, variant, cv):
    mine = profile_skill_set(profile)
    cv_skills = extract_skills(cv_plain_text(cv))
    req = set(explanation["matched_required"]) | set(explanation["missing_required"])
    pref = set(explanation["matched_preferred"]) | set(explanation["missing_preferred"])
    found_req = sorted(req & cv_skills)
    missing_req = sorted(req - mine)
    found_pref = sorted(pref & cv_skills)
    match_pct = round(100 * len(found_req) / len(req)) if req else None
    lines = [
        f"# ATS alignment report: {job['title']} at {job.get('company') or 'unknown company'}",
        "",
        f"CV variant used: {profile['variant_names'][variant]}",
        "",
        "**This is an estimate of keyword overlap. It is not the employer's ATS score and guarantees nothing.**",
        "",
        f"- Required skills in posting: {', '.join(sorted(req)) or 'none detected'}",
        f"- Required skills found in this CV: {', '.join(found_req) or 'none'}"
        + (f" ({match_pct}% of required)" if match_pct is not None else ""),
        f"- Required skills you do NOT have (honest gaps, not added to the CV): {', '.join(missing_req) or 'none'}",
        f"- Preferred skills found: {', '.join(found_pref) or 'none'}",
        f"- Years of experience asked: {explanation['years_required'] if explanation['years_required'] is not None else 'not stated'}",
        f"- Eligibility: {explanation['eligibility']}",
        "",
        "## Format checks",
        "- Single column, no tables, no images, standard section headings: OK",
        "- Dates and employers copied unchanged from your verified profile: OK",
        "",
        "## Notes",
    ] + [f"- {n}" for n in explanation["notes"]] + [
        "- Read the job text yourself before applying. Nothing here checks the posting is real."]
    return "\n".join(lines)


# ---------- 5. Cover letter (fill-in template, optional Gemini draft lives in gemini.py) ----------

def cover_letter(job, explanation, profile, variant, cv):
    top_skills = [s for s in explanation["matched_required"]][:4]
    project = cv["projects"][0]
    bullet = project["bullets"][0].rstrip(".")
    bullet = bullet[0].lower() + bullet[1:]
    focus = profile["cover_letter_focus"][variant]
    company = job.get("company") or "your company"
    p2 = ""
    if top_skills:
        p2 = f"The role asks for {', '.join(top_skills[:-1]) + ' and ' + top_skills[-1] if len(top_skills) > 1 else top_skills[0]}, which are part of my hands-on experience. "
    p2 += f"For example, in the {project['name']} project I {bullet}."
    return (
        f"Dear Hiring Team at {company},\n\n"
        f"I am applying for the {job['title']} position. I am a junior software engineer with {focus}.\n\n"
        f"{p2}\n\n"
        "I hold a B.Sc. in Computer Science from Alexandria University and completed an exchange semester at "
        "the University of Nebraska-Lincoln. I would welcome the chance to discuss how I can contribute to your team.\n\n"
        f"Sincerely,\n{profile['name']}\n"
    )


# ---------- 6. Orchestration ----------

def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "x"


def prepare_application(job_id, require_verified=True):
    """Generate CV (DOCX + PDF), ATS report and cover letter for one stored job."""
    ensure_dirs()
    settings, profile = load_settings(), load_profile()
    if require_verified and not settings.get("profile_verified"):
        raise PermissionError("Profile not verified yet. Open the Profile page and confirm it first.")
    job = db.get_job(job_id)
    explanation = json.loads(job["explanation_json"])
    variant = job["variant"] or "software"
    cv = build_cv(profile, variant)

    stem = f"{job_id:04d}_{_slug(job.get('company'))}_{_slug(job['title'])}_{variant}"
    docx_path, pdf_path = CV_DIR / f"{stem}.docx", CV_DIR / f"{stem}.pdf"
    ats_path, letter_path = CV_DIR / f"{stem}_ats.md", CV_DIR / f"{stem}_letter.txt"

    render_docx(cv, docx_path)
    render_pdf(cv, pdf_path)
    ats_path.write_text(ats_report(job, explanation, profile, variant, cv), encoding="utf-8")
    letter_path.write_text(cover_letter(job, explanation, profile, variant, cv), encoding="utf-8")

    status = job["status"] if job["status"] not in ("Discovered", "Shortlisted") else "CV Generated"
    db.update_job(job_id, cv_docx=str(docx_path), cv_pdf=str(pdf_path), ats_report=str(ats_path),
                  letter_path=str(letter_path), status=status)
    db.log("cv_generated", f"job {job_id} variant {variant}", actor="cv_engine")
    return {"docx": docx_path, "pdf": pdf_path, "ats": ats_path, "letter": letter_path, "variant": variant}
