"""Read job-alert emails you saved into storage/inbox (.eml or .txt). No scraping, no logins.

How to use: in Gmail or Outlook, open a LinkedIn / Wuzzuf / Indeed / Bayt alert email and
download it (.eml) or copy its text into a .txt file, then drop it into storage/inbox.

Alert emails only carry a title and a link, not the full description. Those jobs are stored
with needs_description=1; paste the description in the dashboard to get a real score.
"""
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from ..config import INBOX_DIR
from .common import make_job

JOB_URL_RE = re.compile(
    r"https?://[^\s\"'<>)]*?(?:linkedin\.com/(?:comm/)?jobs/view|wuzzuf\.net/jobs/p/|indeed\.com/(?:viewjob|rc/clk|pagead)|bayt\.com/[a-z]{2}/[^\s\"'<>]*job)[^\s\"'<>)]*",
    re.I)
GENERIC_TEXT = {"view job", "apply", "see job", "view", "apply now", "see more", "view jobs", "click here"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._buf).split())))
            self._href = None


def _clean_url(url):
    parts = urlsplit(url)
    if "linkedin.com" in parts.netloc:  # drop tracking query
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    return url


def _site(url):
    host = urlsplit(url).netloc.lower()
    for name in ("linkedin", "wuzzuf", "indeed", "bayt"):
        if name in host:
            return name
    return host


def _title_from_url(url):
    slug = urlsplit(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]?\d{6,}.*$", "", slug)
    return slug.replace("-", " ").replace("_", " ").strip().title()


def parse_email_file(path):
    """Return (title, url) pairs found in one saved email or text file."""
    path = Path(path)
    pairs = []
    if path.suffix.lower() == ".eml":
        msg = BytesParser(policy=policy.default).parse(open(path, "rb"))
        html_body = msg.get_body(preferencelist=("html",))
        plain_body = msg.get_body(preferencelist=("plain",))
        if html_body:
            parser = _Links()
            parser.feed(html_body.get_content())
            for href, text in parser.links:
                if JOB_URL_RE.match(href):
                    pairs.append((text, href))
        if not pairs and plain_body:
            pairs += _pairs_from_text(plain_body.get_content())
    else:
        pairs += _pairs_from_text(path.read_text(encoding="utf-8", errors="ignore"))
    return pairs


def _pairs_from_text(text):
    lines = text.splitlines()
    pairs = []
    for i, line in enumerate(lines):
        m = JOB_URL_RE.search(line)
        if m:
            before = line[:m.start()].strip(" :-\t")
            prev = next((l.strip() for l in reversed(lines[:i]) if l.strip()), "")
            pairs.append((before or prev, m.group(0)))
    return pairs


def fetch(source_cfg, settings, inbox=None, move_processed=True):
    inbox = Path(inbox) if inbox else INBOX_DIR
    out, errors, seen = [], [], set()
    if not inbox.exists():
        return out, errors
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".eml", ".txt"):
            continue
        try:
            for text, url in parse_email_file(path):
                url = _clean_url(url)
                if url in seen:
                    continue
                seen.add(url)
                title = text if text and text.lower() not in GENERIC_TEXT and len(text) > 3 else _title_from_url(url)
                site = _site(url)
                out.append(make_job(url=url, title=title, company="", source=f"email:{site}",
                                    platform=site, location=""))
            if move_processed:
                dest = inbox / "processed"
                dest.mkdir(exist_ok=True)
                path.replace(dest / path.name)
        except Exception as exc:
            errors.append(f"email:{path.name} {exc}")
    return out, errors
