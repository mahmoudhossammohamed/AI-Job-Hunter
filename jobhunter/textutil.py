"""Small text helpers: HTML to text, normalisation for duplicate detection."""
import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

_BLOCK_TAGS = {"p", "br", "li", "div", "tr", "h1", "h2", "h3", "h4", "ul", "ol"}


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw):
    """Convert (possibly entity-escaped) HTML into plain text with line breaks."""
    if not raw:
        return ""
    raw = html.unescape(raw)  # Greenhouse sends escaped HTML
    stripper = _Stripper()
    stripper.feed(raw)
    text = "".join(stripper.parts)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


_COMPANY_NOISE = {"ltd", "llc", "inc", "co", "company", "corp", "corporation", "limited", "egypt", "eg", "the"}


def norm_company(name):
    words = re.sub(r"[^a-z0-9؀-ۿ ]", " ", (name or "").lower()).split()
    return " ".join(w for w in words if w not in _COMPANY_NOISE)


def norm_title(title):
    t = re.sub(r"\([^)]*\)", " ", (title or "").lower())  # drop "(Remote)" style tags
    t = re.sub(r"[^a-z0-9؀-ۿ+#. ]", " ", t)
    return " ".join(t.split())


def canonical_url(url):
    """Lower-case host, drop query, fragment and trailing slash."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def dedupe_key(company, title, url):
    """Same company + same title = same job, across sources. Without a company, fall back to the URL."""
    nc, nt = norm_company(company), norm_title(title)
    if nc and nt:
        raw = f"ct|{nc}|{nt}"
    else:
        raw = f"url|{canonical_url(url)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
