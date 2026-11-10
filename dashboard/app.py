"""Local dashboard. Start with start.bat (or: python -m streamlit run dashboard/app.py)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # installed with streamlit
import streamlit as st

from jobhunter import cv_engine, db, gemini, url_import
from jobhunter.config import (ensure_dirs, load_env, load_profile, load_settings, load_sources,
                              save_profile, save_settings, CONFIG_DIR)
from jobhunter.scoring import score_job
from jobhunter.search import keyword_search, parse_keywords, process_job, run_search
from jobhunter.sources.common import make_job

st.set_page_config(page_title="Job Hunter", page_icon=None, layout="wide")
ensure_dirs()
load_env()
db.init_db()
settings, profile = load_settings(), load_profile()

BAND_LABEL = {"excellent": "Excellent", "good": "Good", "possible": "Possible", "archive": "Archive"}

st.sidebar.title("Job Hunter")
page = st.sidebar.radio("Page", ["Overview", "Search", "Jobs", "Add job", "Profile", "Settings", "Logs"], label_visibility="collapsed")
st.sidebar.caption("Applications are never sent automatically in this version. You apply yourself using the prepared files.")
if not settings.get("profile_verified"):
    st.sidebar.warning("Profile not verified yet. CVs cannot be generated until you confirm it on the Profile page.")


def download_buttons(job):
    cols = st.columns(4)
    for col, (label, key, mime) in zip(cols, [
            ("CV (PDF)", "cv_pdf", "application/pdf"),
            ("CV (DOCX)", "cv_docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("ATS report", "ats_report", "text/markdown"),
            ("Cover letter", "letter_path", "text/plain")]):
        path = job.get(key)
        if path and Path(path).exists():
            col.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, mime=mime, key=f"dl_{key}_{job['id']}")


# ---------------------------------------------------------------- Overview
if page == "Overview":
    st.header("Overview")
    c = db.counts()
    m = st.columns(5)
    m[0].metric("Jobs found", c["total"])
    m[1].metric("New today", c["today"])
    m[2].metric("Excellent", c["bands"].get("excellent", 0))
    m[3].metric("Good", c["bands"].get("good", 0))
    m[4].metric("Submitted", c["statuses"].get("Submitted", 0))
    st.write("")
    if st.button("Run search now", type="primary"):
        with st.spinner("Searching your configured sources. This can take a few minutes."):
            summary = run_search()
        st.success(f"Found {summary['new']} new jobs, {summary['duplicates']} duplicates, "
                   f"{summary['filtered']} filtered out, {summary['prepared']} CVs prepared.")
        for err in summary["errors"]:
            st.warning(err)
    src = load_sources()
    if not src["greenhouse"]["boards"] and not src["lever"]["companies"]:
        st.info("No Greenhouse boards or Lever companies are configured yet (Settings page). "
                "You can still drop alert emails into storage/inbox, or add jobs by hand on the Add job page.")
    left, right = st.columns(2)
    left.subheader("By match band")
    left.bar_chart(pd.Series(c["bands"], name="jobs"))
    right.subheader("By status")
    right.bar_chart(pd.Series(c["statuses"], name="jobs"))

# ---------------------------------------------------------------- Search
elif page == "Search":
    st.header("Search jobs")
    st.caption("Searches your Greenhouse and Lever companies (Settings page), alert emails in storage/inbox, "
               "and every job already saved. LinkedIn is never scraped: create LinkedIn job alerts by email "
               "and drop the emails into storage/inbox instead.")
    with st.form("kw_search"):
        kw_text = st.text_input("Job titles or skills (comma separated)", placeholder="IBM BPM BAW, Java Developer")
        c = st.columns([3, 1])
        location = c[0].text_input("Location (empty = everywhere)", "Egypt")
        include_remote = c[1].checkbox("Include remote jobs", True)
        go = st.form_submit_button("Search", type="primary")
    if go:
        keywords = parse_keywords(kw_text)
        if not keywords:
            st.error("Type at least one job title or skill.")
        else:
            with st.spinner("Refreshing sources and searching. This can take a minute."):
                st.session_state["kw_rows"], st.session_state["kw_errors"] = keyword_search(keywords, location, include_remote)

    rows = st.session_state.get("kw_rows")
    if rows is not None:
        for err in st.session_state.get("kw_errors", []):
            st.warning(err)
        st.success(f"Found {len(rows)} jobs ({sum(r['is_new'] for r in rows)} new in this search).")
        if rows:
            table = pd.DataFrame([{
                "Job ID": r["id"], "Keyword": r["keyword"], "Title": r["title"], "Company": r["company"],
                "Location": r["location"], "Score": r["score"], "Band": r["band"], "Status": r["status"],
                "Source": r["source"], "Posted": (r["published_at"] or "")[:10],
                "New": "yes" if r["is_new"] else "", "Link": r["url"]} for r in rows])
            st.dataframe(table, hide_index=True, width="stretch",
                         column_config={"Link": st.column_config.LinkColumn("Link")})
            # utf-8-sig so Excel shows Arabic text correctly
            st.download_button("Download CSV", table.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"jobs-{db.now_iso()[:10]}.csv", mime="text/csv")
            st.caption("Open a job on the Jobs page to see its score breakdown and prepare a CV.")

# ---------------------------------------------------------------- Jobs
elif page == "Jobs":
    st.header("Jobs")
    f = st.columns(4)
    band = f[0].selectbox("Band", ["All", "excellent", "good", "possible", "archive"])
    status = f[1].selectbox("Status", ["All"] + db.STATUSES)
    min_score = f[2].slider("Min score", 0, 100, 0)
    text = f[3].text_input("Search title or company")
    jobs = db.list_jobs(status=None if status == "All" else status, band=None if band == "All" else band,
                        min_score=min_score, search=text or None)
    if not jobs:
        st.info("No jobs yet. Run a search on the Overview page, or add one on the Add job page.")
        st.stop()
    table = pd.DataFrame([{"id": j["id"], "score": j["score"], "band": j["band"], "title": j["title"],
                           "company": j["company"], "location": j["location"], "status": j["status"],
                           "source": j["source"], "discovered": (j["discovered_at"] or "")[:10]} for j in jobs])
    st.dataframe(table, hide_index=True, width="stretch")

    pick = st.selectbox("Open a job", [j["id"] for j in jobs],
                        format_func=lambda i: next(f"#{j['id']}  {j['score']}  {j['title']}  ({j['company'] or 'unknown'})" for j in jobs if j["id"] == i))
    job = db.get_job(pick)
    expl = json.loads(job["explanation_json"]) if job["explanation_json"] else None

    st.subheader(f"{job['title']}  |  {job['company'] or 'unknown company'}")
    st.write(f"Score **{job['score']}** ({BAND_LABEL.get(job['band'], '-')}) | category {job['category']} | "
             f"CV variant {profile['variant_names'].get(job['variant'], '-')} | eligibility **{job['eligibility']}** | status **{job['status']}**")
    if job["url"]:
        st.link_button("Open original posting", job["url"])

    if expl:
        a, b = st.columns(2)
        a.markdown("**Score breakdown**")
        a.dataframe(pd.DataFrame([{"part": k, "points": v[0], "max": v[1]} for k, v in expl["components"].items()]),
                    hide_index=True, width="stretch")
        b.markdown(f"**Matched required:** {', '.join(expl['matched_required']) or 'none'}")
        b.markdown(f"**Missing required:** {', '.join(expl['missing_required']) or 'none'}")
        b.markdown(f"**Matched preferred:** {', '.join(expl['matched_preferred']) or 'none'}")
        b.markdown(f"**Missing preferred:** {', '.join(expl['missing_preferred']) or 'none'}")
        b.markdown(f"**Years asked:** {expl['years_required'] if expl['years_required'] is not None else 'not stated'}")
        for n in expl["notes"]:
            st.warning(n)

    if job["needs_description"]:
        st.info("This job has no real description (alert emails only carry a title and link). "
                "Paste the full text from the posting to get an accurate score.")
        pasted = st.text_area("Job description", height=200, key=f"desc_{pick}")
        if st.button("Save description and rescore") and pasted.strip():
            db.update_job(pick, description=pasted.strip())
            fresh = db.get_job(pick)
            db.save_score(pick, score_job(fresh, profile, settings))
            db.log("description_added", f"job {pick}", actor="user")
            st.rerun()
    with st.expander("Job description"):
        st.text(job["description"] or "(none)")

    st.markdown("---")
    act = st.columns(4)
    if act[0].button("Prepare CV and letter", type="primary", key=f"prep_{pick}"):
        try:
            cv_engine.prepare_application(pick)
            st.rerun()
        except PermissionError as exc:
            st.error(str(exc))
    if act[1].button("Shortlist", key=f"sl_{pick}"):
        db.update_job(pick, status="Shortlisted"); db.log("shortlisted", f"job {pick}", actor="user"); st.rerun()
    if act[2].button("Reject", key=f"rj_{pick}"):
        db.update_job(pick, status="Rejected"); db.log("rejected", f"job {pick}", actor="user"); st.rerun()
    if act[3].button("I applied (manually)", key=f"ap_{pick}"):
        db.update_job(pick, status="Submitted", applied_at=db.now_iso()); db.log("marked_submitted", f"job {pick}", actor="user"); st.rerun()

    new_status = st.selectbox("Change status", db.STATUSES, index=db.STATUSES.index(job["status"]) if job["status"] in db.STATUSES else 0, key=f"st_{pick}")
    if new_status != job["status"]:
        db.update_job(pick, status=new_status); db.log("status_changed", f"job {pick} -> {new_status}", actor="user"); st.rerun()
    notes = st.text_area("Notes", job["notes"] or "", key=f"notes_{pick}")
    if notes != (job["notes"] or ""):
        db.update_job(pick, notes=notes)

    download_buttons(job)
    if job["letter_path"] and Path(job["letter_path"]).exists():
        with st.expander("Cover letter (template)"):
            st.text(Path(job["letter_path"]).read_text(encoding="utf-8"))
        if settings["gemini"]["enabled"] and st.button("Draft a letter with Gemini (free tier)", key=f"gem_{pick}"):
            text, msg = gemini.generate_letter(job, profile, job["variant"] or "software", settings)
            (st.text_area("Gemini draft (edit before use)", text, height=260) if text else st.warning(msg))
            if text:
                st.caption(msg)
    if job["ats_report"] and Path(job["ats_report"]).exists():
        with st.expander("ATS alignment report"):
            st.markdown(Path(job["ats_report"]).read_text(encoding="utf-8"))

# ---------------------------------------------------------------- Add job
elif page == "Add job":
    st.header("Add a job")
    st.subheader("1. Paste a link (optional)")
    st.caption("Works for Greenhouse, Lever and most company career pages. LinkedIn links are not read. "
               "If a site blocks us we stop and you fill the form by hand.")
    link = st.text_input("Job link", placeholder="https://...")
    if st.button("Fetch details"):
        with st.spinner("Reading the job..."):
            fetched, message = url_import.import_from_url(link, settings)
        st.session_state["imp_msg"] = (fetched is not None, message)
        st.session_state["imp_job"] = fetched
        if fetched:
            db.log("url_imported", fetched.get("url"), actor="user")
            # Fill the form below. This runs before the form is drawn, so Streamlit allows it.
            for field in ("title", "company", "url", "location", "description"):
                st.session_state[f"add_{field}"] = fetched.get(field) or ""
    if "imp_msg" in st.session_state:
        ok, message = st.session_state["imp_msg"]
        (st.success if ok else st.warning)(message)
        imp = st.session_state.get("imp_job")
        if imp:
            extra = {"Job type": imp.get("employment_type"), "Salary": imp.get("salary"),
                     "Posted": (imp.get("published_at") or "")[:10]}
            st.caption(" | ".join(f"{k}: {v}" for k, v in extra.items() if v) or "No job type, salary or date on the page.")

    st.subheader("2. Check the details and save")
    for field in ("title", "company", "url", "location", "description"):
        st.session_state.setdefault(f"add_{field}", "")
    with st.form("add_job"):
        title = st.text_input("Job title", key="add_title")
        company = st.text_input("Company", key="add_company")
        url = st.text_input("Link to the posting", key="add_url")
        location = st.text_input("Location (for example: Cairo, Egypt, or Remote)", key="add_location")
        description = st.text_area("Full job description", height=260, key="add_description")
        submitted = st.form_submit_button("Add and score")
    if submitted:
        if not title.strip():
            st.error("A title is required.")
        else:
            # Keep the extra fields from the fetched job (salary, date...) if the link was not changed.
            imp = st.session_state.get("imp_job")
            base = imp if imp and imp.get("url") == url.strip() else {"source": "manual", "platform": "manual"}
            job_id, is_new = process_job(make_job(**{**base, "title": title.strip(), "company": company.strip(),
                                                     "url": url.strip(), "location": location.strip(),
                                                     "description": description.strip()}), profile, settings)
            if is_new:
                db.log("job_added", f"job {job_id}", actor="user")
                st.success(f"Added as job #{job_id}. Open it on the Jobs page.")
            else:
                st.warning(f"This job already exists (job #{job_id}).")

# ---------------------------------------------------------------- Profile
elif page == "Profile":
    st.header("Profile")
    st.caption("This is the single source of truth. Every CV is built only from this data.")
    for flag in profile["meta"]["flags_to_confirm"]:
        st.warning(flag)
    st.write(f"**{profile['name']}** | {profile['headline']}")
    st.write("**Experience**")
    st.dataframe(pd.DataFrame([{"title": e["title"], "organisation": e["org"], "from": e["start"], "to": e["end"]}
                               for e in profile["experience"]]), hide_index=True, width="stretch")
    st.write("**Skills**")
    for g, items in profile["skills"].items():
        st.write(f"{g}: {', '.join(items)}")
    st.write("**Projects:** " + "; ".join(p["name"] for p in profile["projects"]))

    with st.expander("Edit profile.json (advanced)"):
        raw = st.text_area("profile.json", json.dumps(profile, indent=2, ensure_ascii=False), height=400)
        if st.button("Save profile.json"):
            try:
                new = json.loads(raw)
                for v in new["variant_names"]:
                    cv_engine.build_cv(new, v)  # fails loudly if the structure is broken
                save_profile(new)
                settings["profile_verified"] = False  # any edit needs a fresh confirmation
                save_settings(settings)
                db.log("profile_edited", "verification reset", actor="user")
                st.success("Saved. Please re-confirm below.")
            except Exception as exc:
                st.error(f"Not saved: {exc}")

    st.markdown("---")
    ok = st.checkbox("I checked every date, employer, skill and project above against my real CV.", value=bool(settings.get("profile_verified")))
    if ok != bool(settings.get("profile_verified")):
        settings["profile_verified"] = ok
        save_settings(settings)
        db.log("profile_verified" if ok else "profile_unverified", "", actor="user")
        st.rerun()

# ---------------------------------------------------------------- Settings
elif page == "Settings":
    st.header("Settings")
    st.subheader("Sources")
    src = load_sources()
    gh = st.text_area("Greenhouse board tokens (one per line). Token = boards.greenhouse.io/<token>",
                      "\n".join(src["greenhouse"]["boards"]))
    lv = st.text_area("Lever company slugs (one per line). Slug = jobs.lever.co/<slug>",
                      "\n".join(src["lever"]["companies"]))
    st.caption("Wuzzuf, LinkedIn, Indeed and Bayt are covered through alert emails in storage/inbox and the Add job page. "
               "They are not scraped. Company career pages (IBM, Vodafone, PwC...) can be added one link at a time on the Add job page.")
    st.subheader("Scoring and preparation")
    t = settings["thresholds"]
    c = st.columns(3)
    t["excellent"] = c[0].number_input("Excellent from", 50, 100, t["excellent"])
    t["good"] = c[1].number_input("Good from", 40, 100, t["good"])
    t["possible"] = c[2].number_input("Possible from", 20, 100, t["possible"])
    settings["auto_prepare_min_score"] = st.number_input("Auto-prepare CVs for new jobs scoring at least", 0, 100, settings["auto_prepare_min_score"])
    settings["max_job_age_days"] = st.number_input("Ignore jobs older than (days)", 1, 365, settings["max_job_age_days"])
    settings["keep_only_matching_locations"] = st.checkbox("Keep only Egypt or remote jobs when searching", settings["keep_only_matching_locations"])
    st.subheader("Gemini (optional, free tier)")
    settings["gemini"]["enabled"] = st.checkbox("Enable Gemini letter drafts (needs GEMINI_API_KEY in .env)", settings["gemini"]["enabled"])
    settings["gemini"]["model"] = st.text_input("Gemini model name", settings["gemini"]["model"])
    st.caption("Only the job text and your skills and project lines are sent. Never your phone, email or links.")
    if st.button("Save settings", type="primary"):
        save_settings(settings)
        src["greenhouse"]["boards"] = [x.strip() for x in gh.splitlines() if x.strip()]
        src["lever"]["companies"] = [x.strip() for x in lv.splitlines() if x.strip()]
        with open(CONFIG_DIR / "sources.json", "w", encoding="utf-8") as fh:
            json.dump(src, fh, indent=2)
        db.log("settings_saved", "", actor="user")
        st.success("Saved.")
    st.subheader("Daily automatic search")
    st.markdown("Use Windows Task Scheduler to run `run_search.bat` once a day. Steps are in README.md.")

# ---------------------------------------------------------------- Logs
elif page == "Logs":
    st.header("Audit log")
    logs = db.recent_logs()
    st.dataframe(pd.DataFrame(logs), hide_index=True, width="stretch") if logs else st.info("Nothing logged yet.")
