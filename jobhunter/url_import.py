"""Import one job from a link you paste. Standard library + requests only.

Order of attempts:
1. Refuse sites we must not touch (LinkedIn).
2. Greenhouse or Lever link: use their official public API (clean JSON, no page scraping).
3. Any other site: check robots.txt, fetch the page once, read its schema.org JobPosting block.
   Most job sites publish this block so Google can list their jobs.
4. No JobPosting block: take the page title and short description, you fill in the rest.

The page text is stored as data only. Nothing in it is ever treated as an instruction.
We never log in, never solve CAPTCHAs and never pretend to be a browser.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .sources import greenhouse, lever
from .sources.common import make_job, polite_get
from .textutil import html_to_text

BLOCKED_HOSTS = ("linkedin.com", "lnkd.in")  # owner's rule: never scrape LinkedIn
MAX_PAGE_CHARS = 2_000_000  # ignore anything after 2 MB, job pages are far smaller
MAX_DESCRIPTION_CHARS = 20_000

# boards.greenhouse.io/<token>/jobs/<id>  or  job-boards.greenhouse.io/<token>/jobs/<id>
GREENHOUSE_RE = re.compile(r"^(?:boards|job-boards)\.greenhouse\.io$")
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
# jobs.lever.co/<slug>/<posting id>
LEVER_API = "https://api.lever.co/v0/postings/{slug}/{posting_id}"


def _host(url):
    return urlsplit(url).netloc.lower().split(":")[0]


def is_blocked(url):
    host = _host(url)
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


# ---------------------------------------------------------------- official APIs

def _from_greenhouse(url, settings):
    parts = urlsplit(url).path.strip("/").split("/")  # [token, "jobs", id]
    if len(parts) < 3 or parts[1] != "jobs":
        return None, "This Greenhouse link is not a single job page."
    token, job_id = parts[0], parts[2]
    resp = polite_get(GREENHOUSE_API.format(token=token, job_id=job_id), settings, params={"content": "true"})
    if resp.status_code != 200:
        return None, f"Greenhouse API answered HTTP {resp.status_code}. The job may be closed."
    job = greenhouse.parse(token, {"jobs": [resp.json()]})[0]
    job["source"] = "url:greenhouse"
    return job, "Read from the official Greenhouse API."


def _from_lever(url, settings):
    parts = urlsplit(url).path.strip("/").split("/")  # [slug, posting id, maybe "apply"]
    if len(parts) < 2:
        return None, "This Lever link is not a single job page."
    slug, posting_id = parts[0], parts[1]
    resp = polite_get(LEVER_API.format(slug=slug, posting_id=posting_id), settings)
    if resp.status_code != 200:
        return None, f"Lever API answered HTTP {resp.status_code}. The job may be closed."
    job = lever.parse(slug, [resp.json()])[0]
    job["source"] = "url:lever"
    return job, "Read from the official Lever API."


# ---------------------------------------------------------------- robots.txt

def robots_allows(url, settings):
    """True if the site's robots.txt lets our User-Agent read this page."""
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    resp = polite_get(robots_url, settings, accept="text/plain")
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        return False  # site refuses or is broken: be careful and stop
    if resp.status_code >= 400:
        return True  # no robots.txt means no rules
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    agent = settings["http"]["user_agent"].split("/")[0]  # "PersonalJobHunter"
    return rp.can_fetch(agent, url)


# ---------------------------------------------------------------- page parsing

class _PageReader(HTMLParser):
    """Collect JSON-LD blocks, <title> and <meta> tags. Nothing else."""

    def __init__(self):
        super().__init__()
        self.ld_blocks, self.meta, self.title = [], {}, ""
        self._in_ld, self._in_title, self._buf = False, False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buf))
            self._in_ld = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title:
            self.title += data


def _walk(node):
    """Yield every dict inside a JSON-LD value (handles lists and @graph)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk(node[key])


def find_job_posting(ld_blocks):
    for raw in ld_blocks:
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue  # some sites ship broken JSON-LD, skip it
        for node in _walk(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return node
    return None


def _name(value):
    """schema.org values can be a plain string or {"name": ...}."""
    if isinstance(value, dict):
        return value.get("name") or ""
    return value or ""


def _location(posting):
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    out = []
    for place in places:
        addr = place.get("address") if isinstance(place, dict) else place
        if isinstance(addr, dict):
            bits = [addr.get("addressLocality"), addr.get("addressRegion"), _name(addr.get("addressCountry"))]
            text = ", ".join(b for b in bits if b)
        else:
            text = str(addr or "")
        if text and text not in out:
            out.append(text)
    if posting.get("jobLocationType") == "TELECOMMUTE":
        out.append("Remote")
    return "; ".join(out)


def _salary(posting):
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return None
    value, currency = base.get("value"), base.get("currency") or ""
    if isinstance(value, dict):
        low, high, unit = value.get("minValue"), value.get("maxValue"), value.get("unitText") or ""
        amount = f"{low}-{high}" if low and high else str(low or high or value.get("value") or "")
        return f"{amount} {currency} per {unit}".strip() if amount else None
    return f"{value} {currency}".strip() if value else None


def job_from_posting(posting, url):
    emp = posting.get("employmentType")
    location = _location(posting)
    return make_job(
        url=url,
        title=html_to_text(posting.get("title") or ""),
        company=_name(posting.get("hiringOrganization")),
        location=location,
        work_mode="remote" if "Remote" in location else None,
        description=html_to_text(posting.get("description") or "")[:MAX_DESCRIPTION_CHARS],
        employment_type=", ".join(emp) if isinstance(emp, list) else emp,
        salary=_salary(posting),
        source="url:" + _host(url),
        platform=_host(url),
        published_at=posting.get("datePosted"),
    )


def job_from_html(page_html, url):
    """Return (job, message) from a fetched page. Job is None if nothing useful was found."""
    reader = _PageReader()
    reader.feed(page_html[:MAX_PAGE_CHARS])
    posting = find_job_posting(reader.ld_blocks)
    if posting:
        return job_from_posting(posting, url), "Read from the page's JobPosting data. Please check it."
    title = reader.meta.get("og:title") or reader.title.strip()
    if "captcha" in page_html.lower() and not title:
        return None, "The site shows a CAPTCHA. We do not bypass it. Add this job by hand."
    if not title:
        return None, "No job data found on this page. Add this job by hand."
    desc = reader.meta.get("og:description") or reader.meta.get("description") or ""
    job = make_job(url=url, title=" ".join(title.split()), company=reader.meta.get("og:site_name") or "",
                   description=desc, source="url:" + _host(url), platform=_host(url))
    return job, "This page has no structured job data. Only the title was read: paste the full description."


# ---------------------------------------------------------------- entry point

def import_from_url(url, settings):
    """Return (job, message). Job is None when we stopped; message says why."""
    url = (url or "").strip()
    if urlsplit(url).scheme not in ("http", "https") or not _host(url):
        return None, "Please paste a full link starting with https://"
    if is_blocked(url):
        return None, "LinkedIn links are not read (LinkedIn forbids it). Copy the details by hand below."
    host = _host(url)
    try:
        if GREENHOUSE_RE.match(host):
            return _from_greenhouse(url, settings)
        if host == "jobs.lever.co":
            return _from_lever(url, settings)
        if not robots_allows(url, settings):
            return None, f"{host} asks robots not to read this page (robots.txt). Add this job by hand."
        resp = polite_get(url, settings, accept="text/html")
    except Exception as exc:  # network problems: show them, do not crash the dashboard
        return None, f"Could not reach {host}: {exc}"
    if is_blocked(resp.url):
        return None, "The link redirects to LinkedIn, which we do not read. Add this job by hand."
    if resp.status_code in (401, 403, 429):
        return None, f"{host} refused the request (HTTP {resp.status_code}). We respect that. Add this job by hand."
    if resp.status_code != 200:
        return None, f"{host} answered HTTP {resp.status_code}. The job may be closed."
    if re.search(r"/(login|signin|sign-in|auth)\b", urlsplit(resp.url).path, re.I):
        return None, f"{host} needs a login to show this job. We do not log in. Add this job by hand."
    return job_from_html(resp.text, url)
