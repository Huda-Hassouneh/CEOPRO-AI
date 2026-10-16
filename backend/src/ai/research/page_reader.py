"""
Reads one public web page (HTML, PDF or plain text) for the assistant.

Only public pages, read the way a careful visitor would:
- every URL and every redirect hop must resolve to public internet
  addresses (market_scraper/network_security.py), so a page can never make
  the server reach its own network;
- robots.txt is honoured for the reader's user agent;
- no logins, cookies, CAPTCHAs or paywalls are attempted - a page that
  asks for any of them is reported as not readable;
- size and time limits keep one slow or huge page from stalling a question.

The result keeps what the page says about itself (title, publisher, the
published and updated dates when the page states them) next to its text,
so every passage cited from it carries its provenance. A failure is
returned as an explicit status - never as an empty page that would look
like "the source says nothing".
"""
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Dict, List, Optional, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from src.market_scraper.network_security import UnsafeTargetError, resolve_public_addresses

logger = logging.getLogger("KEEL_RESEARCH")

USER_AGENT = os.getenv("RESEARCH_USER_AGENT", "KEEL-Research/1.0 (+business research for KEEL customers)")
TIMEOUT_SECONDS = float(os.getenv("RESEARCH_PAGE_TIMEOUT_SECONDS", "10"))
MAX_BYTES = int(os.getenv("RESEARCH_PAGE_MAX_BYTES", str(3 * 1024 * 1024)))
MAX_TEXT_CHARS = 60_000
MAX_REDIRECTS = 4
MAX_PDF_PAGES = 40

OK = "ok"
BLOCKED_BY_ROBOTS = "blocked_by_robots"
UNSAFE_TARGET = "unsafe_target"
UNREACHABLE = "unreachable"
HTTP_ERROR = "http_error"
NEEDS_LOGIN = "needs_login"
UNSUPPORTED = "unsupported_type"
TOO_LARGE = "too_large"
EMPTY = "no_readable_text"

_DROP_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "template")
_DATE_META = {
    "published": ("article:published_time", "datepublished", "date", "dc.date", "dcterms.issued", "publication_date",
                  "pubdate", "og:published_time"),
    "modified": ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified", "last-modified",
                 "lastmod"),
}
_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class Page:
    url: str
    status: str
    final_url: Optional[str] = None
    title: Optional[str] = None
    site_name: Optional[str] = None
    published_at: Optional[str] = None
    modified_at: Optional[str] = None
    language: Optional[str] = None
    text: str = ""
    http_status: Optional[int] = None
    detail: Optional[str] = None
    tables: List[str] = field(default_factory=list)
    retrieved_at: Optional[str] = None

    @property
    def readable(self) -> bool:
        return self.status == OK and bool(self.text.strip())


_ROBOTS_CACHE: Dict[str, Tuple[float, Optional[robotparser.RobotFileParser]]] = {}
_ROBOTS_LOCK = Lock()
_ROBOTS_TTL_SECONDS = 6 * 3600

Fetch = Callable[..., httpx.Response]


def _default_fetch(url: str, **kwargs) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5",
                               "Accept-Language": "en,ar;q=0.9"}) as client:
        with client.stream("GET", url) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise _TooLarge()
                chunks.append(chunk)
            return httpx.Response(response.status_code, headers=response.headers, content=b"".join(chunks),
                                  request=response.request)


class _TooLarge(Exception):
    pass


def _robots_allows(url: str, fetch: Fetch) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.monotonic()
    with _ROBOTS_LOCK:
        cached = _ROBOTS_CACHE.get(origin)
    if cached is None or now - cached[0] > _ROBOTS_TTL_SECONDS:
        parser: Optional[robotparser.RobotFileParser] = None
        try:
            response = fetch(origin + "/robots.txt")
            if response.status_code < 400:
                parser = robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
            elif response.status_code in (401, 403):
                # A site that refuses its own robots.txt is treated as refusing readers.
                parser = robotparser.RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
        except (httpx.HTTPError, _TooLarge, UnsafeTargetError):
            parser = None  # no robots.txt reachable: the standard treats this as allowed
        with _ROBOTS_LOCK:
            _ROBOTS_CACHE[origin] = (now, parser)
        cached = (now, parser)
    parser = cached[1]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


def _first_date(values: List[str]) -> Optional[str]:
    for value in values:
        match = _ISO_DATE.search(value or "")
        if match:
            return match.group(1)
    return None


def _json_ld_dates(html: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    published = modified = publisher = None
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            for node in [item] + [n for n in item.get("@graph", []) if isinstance(n, dict)]:
                published = published or _first_date([str(node.get("datePublished") or "")])
                modified = modified or _first_date([str(node.get("dateModified") or "")])
                owner = node.get("publisher")
                if isinstance(owner, dict) and owner.get("name") and not publisher:
                    publisher = str(owner["name"])
    return published, modified, publisher


def parse_html(url: str, html: str) -> Page:
    from lxml import html as lxml_html

    try:
        document = lxml_html.fromstring(html)
    except (ValueError, TypeError) as exc:
        return Page(url=url, status=EMPTY, detail=type(exc).__name__)
    meta: Dict[str, str] = {}
    for element in document.iter("meta"):
        key = (element.get("property") or element.get("name") or element.get("itemprop") or "").strip().lower()
        if key and element.get("content"):
            meta.setdefault(key, element.get("content").strip())
    published, modified, publisher = _json_ld_dates(html)
    published = published or _first_date([meta.get(k, "") for k in _DATE_META["published"]])
    modified = modified or _first_date([meta.get(k, "") for k in _DATE_META["modified"]])
    for time_element in document.iter("time"):
        if not published and time_element.get("datetime"):
            published = _first_date([time_element.get("datetime")])
    title_element = document.find(".//title")
    title = meta.get("og:title") or (title_element.text_content().strip() if title_element is not None else None)
    language = document.get("lang") or meta.get("og:locale")

    for tag in _DROP_TAGS:
        for element in document.iter(tag):
            element.drop_tree()
    tables = []
    for table in document.iter("table"):
        rows = []
        for row in table.iter("tr"):
            cells = [re.sub(r"\s+", " ", cell.text_content()).strip() for cell in row if cell.tag in ("td", "th")]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            tables.append("\n".join(rows[:60]))
    root = next(iter(document.iter("article")), None)
    if root is None:
        root = next(iter(document.iter("main")), None)
    if root is None:
        root = document
    blocks = []
    for element in root.iter("h1", "h2", "h3", "h4", "p", "li", "td", "dd", "dt", "blockquote", "pre"):
        text = re.sub(r"\s+", " ", element.text_content()).strip()
        if len(text) >= 3 and (not blocks or blocks[-1] != text):
            blocks.append(text)
    text = "\n".join(blocks) or re.sub(r"\s+", " ", root.text_content()).strip()
    lowered = text.lower()[:4000]
    if len(text) < 400 and any(word in lowered for word in ("sign in", "log in", "login", "subscribe to read", "تسجيل الدخول")):
        return Page(url=url, status=NEEDS_LOGIN, title=title, detail="the page asks for a login or subscription")
    return Page(url=url, status=OK if text.strip() else EMPTY, title=title,
                site_name=meta.get("og:site_name") or publisher, published_at=published, modified_at=modified,
                language=language, text=text[:MAX_TEXT_CHARS], tables=tables[:10])


def parse_pdf(url: str, raw: bytes) -> Page:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = [f"[page {number}] {page.extract_text() or ''}" for number, page in
                     enumerate(pdf.pages[:MAX_PDF_PAGES], start=1)]
            info = pdf.metadata or {}
    except Exception as exc:  # noqa: BLE001 - a broken PDF is a status, not a crash
        return Page(url=url, status=EMPTY, detail=type(exc).__name__)
    text = "\n".join(pages)
    created = str(info.get("CreationDate") or "")
    published = f"{created[2:6]}-{created[6:8]}-{created[8:10]}" if re.match(r"D:\d{8}", created) else None
    return Page(url=url, status=OK if re.sub(r"\[page \d+\]", "", text).strip() else EMPTY,
                title=str(info.get("Title") or "") or None, published_at=published, text=text[:MAX_TEXT_CHARS])


def read(url: str, fetch: Optional[Fetch] = None, resolver=None) -> Page:
    """The page at `url`, or a Page with the reason it could not be read."""
    fetch = fetch or _default_fetch
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if resolver is not None:
                resolve_public_addresses(current, resolver=resolver)
            else:
                resolve_public_addresses(current)
            if not _robots_allows(current, fetch):
                return Page(url=url, status=BLOCKED_BY_ROBOTS, final_url=current,
                            detail="the site's robots.txt does not allow automated reading of this page")
            response = fetch(current)
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                current = urljoin(current, response.headers["location"])
                continue
            break
        else:
            return Page(url=url, status=HTTP_ERROR, detail="too many redirects")
    except UnsafeTargetError as exc:
        return Page(url=url, status=UNSAFE_TARGET, detail=str(exc))
    except _TooLarge:
        return Page(url=url, status=TOO_LARGE, detail=f"larger than {MAX_BYTES // 1024} KB")
    except httpx.HTTPError as exc:
        return Page(url=url, status=UNREACHABLE, detail=type(exc).__name__)

    if response.status_code in (401, 402, 403):
        return Page(url=url, status=NEEDS_LOGIN, final_url=current, http_status=response.status_code,
                    detail="the site refused access (login, subscription or blocking)")
    if response.status_code >= 400:
        return Page(url=url, status=HTTP_ERROR, final_url=current, http_status=response.status_code)
    content_type = (response.headers.get("content-type") or "").lower()
    if "pdf" in content_type or current.lower().endswith(".pdf"):
        page = parse_pdf(url, response.content)
    elif "html" in content_type or "xml" in content_type:
        page = parse_html(url, response.text)
    elif content_type.startswith("text/"):
        page = Page(url=url, status=OK, text=response.text[:MAX_TEXT_CHARS])
    else:
        return Page(url=url, status=UNSUPPORTED, final_url=current, detail=content_type or "unknown type")
    page.final_url = current
    page.http_status = response.status_code
    if not page.modified_at and response.headers.get("last-modified"):
        page.modified_at = _http_date(response.headers["last-modified"])
    return page


def _http_date(value: str) -> Optional[str]:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None
