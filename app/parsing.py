"""Pure HTML/URL parsing helpers — no network, no LLM, fully unit-testable.

These encode the *deterministic* half of the hybrid strategy: link scoring,
known-ATS detection, and job-posting extraction. The LLM is only consulted by
the stage modules when these heuristics are ambiguous.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# ── Careers-link signals ─────────────────────────────────────────────────────
CAREERS_KEYWORDS = [
    "careers", "career", "jobs", "job openings", "open roles", "open positions",
    "join us", "join our team", "work with us", "work for us", "we're hiring",
    "we are hiring", "opportunities", "vacancies", "life at", "our team",
]
# Strong signals (URL path tokens) worth more than fuzzy text.
CAREERS_URL_TOKENS = ["career", "careers", "jobs", "join", "hiring", "vacanc", "openings"]

COMMON_CAREERS_PATHS = [
    "/careers", "/careers/", "/career", "/jobs", "/jobs/", "/join-us",
    "/company/careers", "/about/careers", "/en/careers", "/work-with-us",
    "/about/jobs", "/company/jobs",
]

# ── Known ATS hosts → (provider, regex to confirm a *posting* URL) ───────────
ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday",
    "breezy.hr": "breezy",
    "workable.com": "workable",
    "smartrecruiters.com": "smartrecruiters",
    "bamboohr.com": "bamboohr",
    "jobvite.com": "jobvite",
    "icims.com": "icims",
    "recruitee.com": "recruitee",
    "teamtailor.com": "teamtailor",
    "applytojob.com": "jazzhr",
    "personio.com": "personio",
    "rippling.com": "rippling",
}

# URL shapes that look like an individual job posting.
JOB_URL_PATTERNS = [
    re.compile(r"/jobs?/[\w-]+", re.I),
    re.compile(r"/careers?/[\w-]{3,}", re.I),  # /careers/<slug> (not the bare /careers root)
    re.compile(r"/position[s]?/", re.I),
    re.compile(r"/opening[s]?/", re.I),
    re.compile(r"/vacanc(y|ies)/", re.I),
    re.compile(r"lever\.co/[^/]+/[0-9a-f-]{8,}", re.I),
    re.compile(r"greenhouse\.io/[^/]+/jobs/\d+", re.I),
    re.compile(r"ashbyhq\.com/[^/]+/[0-9a-f-]{8,}", re.I),
    re.compile(r"myworkdayjobs\.com/.+/job/", re.I),
]


@dataclass
class Link:
    text: str
    href: str          # absolute
    area: str = "body"  # nav | footer | body


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def registrable_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:
        return ""


def same_site(a: str, b: str) -> bool:
    ha, hb = registrable_host(a), registrable_host(b)
    if not ha or not hb:
        return False
    # compare last two labels (acme.com == www.acme.com == blog.acme.com)
    return ha.split(".")[-2:] == hb.split(".")[-2:]


def extract_links(html: str, base_url: str) -> list[Link]:
    """All anchors as absolute Links, tagged by page area (nav/footer/body)."""
    soup = BeautifulSoup(html or "", "html.parser")
    nav_hrefs, footer_hrefs = set(), set()
    for nav in soup.find_all(["nav", "header"]):
        for a in nav.find_all("a", href=True):
            nav_hrefs.add(a["href"])
    for foot in soup.find_all("footer"):
        for a in foot.find_all("a", href=True):
            footer_hrefs.add(a["href"])

    links: list[Link] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        area = "nav" if href in nav_hrefs else "footer" if href in footer_hrefs else "body"
        links.append(Link(text=_clean_text(a.get_text()), href=absolute, area=area))
    return links


def score_careers_link(link: Link) -> float:
    """Heuristic 0..~5 score that a link points to a careers page."""
    href = link.href.lower()
    text = link.text.lower()
    score = 0.0

    for token in CAREERS_URL_TOKENS:
        if token in href:
            score += 2.0
            break
    for kw in CAREERS_KEYWORDS:
        if kw in text:
            score += 1.5
            break

    # ATS host is a very strong signal.
    host = registrable_host(href)
    if any(host.endswith(h) or h in host for h in ATS_HOSTS):
        score += 3.0

    # Footer/nav links are likelier to be the canonical careers entry.
    if link.area in ("nav", "footer"):
        score += 0.5

    # Penalise obvious noise (blog posts about careers, news, etc.).
    if any(bad in href for bad in ["/blog/", "/news/", "/press/", "/article"]):
        score -= 1.5
    return score


def rank_careers_links(links: list[Link]) -> list[tuple[Link, float]]:
    scored = [(lk, score_careers_link(lk)) for lk in links]
    scored = [(lk, s) for lk, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def detect_ats(url: str) -> str | None:
    host = registrable_host(url)
    for h, provider in ATS_HOSTS.items():
        if host.endswith(h) or h in host:
            return provider
    return None


def looks_like_job_url(url: str) -> bool:
    return any(p.search(url) for p in JOB_URL_PATTERNS)


def extract_job_links(html: str, base_url: str) -> list[Link]:
    """Anchors that look like individual job postings, de-duplicated."""
    out: list[Link] = []
    seen: set[str] = set()
    for lk in extract_links(html, base_url):
        if looks_like_job_url(lk.href) and lk.href not in seen:
            # Skip the listing root itself (e.g. just "/jobs").
            path = urlparse(lk.href).path.rstrip("/")
            if path.count("/") >= 2 or detect_ats(lk.href):
                seen.add(lk.href)
                out.append(lk)
    return out
