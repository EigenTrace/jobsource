"""Discovery layer: query → ranked candidates.

- `parse_query`            NL query → SearchFilters (LLM, heuristic fallback)
- `candidate_from_linkedin_url`  single LinkedIn URL → Candidate
- `discover`               filters → deduped, ranked list of Candidates
                           (LinkedIn via Apify primary, Tavily web fallback)
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .browser import fetch_one
from .llm import llm
from .schemas import Candidate, SearchFilters
from .search_sources import apify_linkedin_jobs, tavily_search

# ── NL query → filters ───────────────────────────────────────────────────────
_REMOTE_RE = re.compile(r"\bremote\b", re.I)
_LOCATION_RE = re.compile(r"\b(?:in|near|around)\s+([A-Z][\w.\- ]+?)(?:,|\.|$| for | who | that )", re.I)


def parse_query(query: str) -> SearchFilters:
    """Parse a natural-language query into structured, editable filters."""
    query = (query or "").strip()
    if not query:
        return SearchFilters()

    if llm.available:
        obj = llm.complete_json(
            system="You extract structured job-search filters. Return only JSON.",
            user=(
                "Extract filters from this job-search query. Respond as JSON with keys: "
                "role (string), keywords (array of strings), location (string), "
                "remote (true/false/null), industry (string), seniority (string).\n\n"
                f"QUERY: {query}"
            ),
        )
        if obj:
            return SearchFilters(
                role=str(obj.get("role", "") or ""),
                keywords=[str(k) for k in (obj.get("keywords") or []) if k],
                location=str(obj.get("location", "") or ""),
                remote=obj.get("remote") if isinstance(obj.get("remote"), bool) else None,
                industry=str(obj.get("industry", "") or ""),
                seniority=str(obj.get("seniority", "") or ""),
            )

    # Heuristic fallback.
    remote = bool(_REMOTE_RE.search(query))
    loc_match = _LOCATION_RE.search(query)
    location = loc_match.group(1).strip() if loc_match else ""
    role = query
    if loc_match:
        role = query[: loc_match.start()].strip()
    role = _REMOTE_RE.sub("", role).strip(" ,.-")
    return SearchFilters(role=role or query, location=location, remote=remote or None)


# ── LinkedIn single URL → candidate ──────────────────────────────────────────
async def candidate_from_linkedin_url(url: str) -> Candidate:
    # /company/<slug> → company name from slug.
    m = re.search(r"/company/([^/?#]+)", url)
    if m:
        slug = m.group(1)
        return Candidate(
            company_name=_humanize(slug),
            source="linkedin",
            company_linkedin_url=url,
        )

    # Job URL: the search actor can't fetch one specific posting, so read the
    # public guest page directly and parse the company from it.
    page = await fetch_one(url)
    name, company_li = _parse_linkedin_company(page.html)
    return Candidate(
        company_name=name,
        source="linkedin",
        source_job_url=url,
        company_linkedin_url=company_li,
    )


def _parse_linkedin_company(html: str) -> tuple[str, str]:
    if not html:
        return "", ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    company, company_li = "", ""
    # Company link on the job topcard.
    a = soup.find("a", href=re.compile(r"/company/"))
    if a:
        company = a.get_text(strip=True)
        company_li = a.get("href", "")
    if not company:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            # "Job Title hiring <Company> in <loc>" or "Title - Company"
            txt = og["content"]
            parts = re.split(r" - | at | hiring ", txt)
            if len(parts) >= 2:
                company = parts[-1].strip()
    return company, company_li


# ── Apify item normalisation ─────────────────────────────────────────────────
def _first(item: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):  # nested {name: ...}
            for nk in ("name", "title", "url"):
                if isinstance(v.get(nk), str) and v[nk].strip():
                    return v[nk].strip()
    return default


def _normalize_linkedin_item(item: dict, fallback_source_url: str = "") -> Candidate:
    return Candidate(
        company_name=_first(item, "companyName", "company", "company_name", "organization"),
        source="linkedin",
        source_job_url=_first(item, "jobUrl", "url", "link", "jobPostingUrl", default=fallback_source_url),
        company_linkedin_url=_first(item, "companyUrl", "companyLinkedinUrl", "companyLink"),
        company_website=_first(item, "companyWebsite", "website"),
    )


# ── Web fallback ─────────────────────────────────────────────────────────────
_NON_COMPANY = ("linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
                "wikipedia.org", "crunchbase.com", "builtin.com", "wellfound.com")


async def _web_fallback(filters: SearchFilters) -> list[Candidate]:
    q = f"{filters.role} jobs {filters.location} careers".strip()
    results = await tavily_search(q, max_results=10)
    out: list[Candidate] = []
    for r in results:
        host = (urlparse(r.url).hostname or "").lower()
        if not host or any(bad in host for bad in _NON_COMPANY):
            continue
        name = _company_from_host(host)
        out.append(Candidate(
            company_name=name,
            source="web",
            source_job_url=r.url,
            company_website=f"https://{host}/",
        ))
    return out


def _company_from_host(host: str) -> str:
    core = host.lstrip("www.").split(".")[0]
    return _humanize(core)


def _humanize(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


# ── Orchestrated discovery ───────────────────────────────────────────────────
async def discover(filters: SearchFilters, *, limit: int = 12) -> list[Candidate]:
    candidates: list[Candidate] = []

    items = await apify_linkedin_jobs(filters.to_linkedin_query(), filters.location, rows=limit)
    for it in items:
        cand = _normalize_linkedin_item(it)
        if cand.company_name:
            candidates.append(cand)

    if len(candidates) < 3:  # thin → widen with the web fallback
        candidates.extend(await _web_fallback(filters))

    candidates = _dedupe(candidates)
    candidates = _rank(candidates, filters)
    return candidates[:limit]


def _dedupe(cands: list[Candidate]) -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    for c in cands:
        key = re.sub(r"[^a-z0-9]", "", c.company_name.lower())
        if not key:
            continue
        # Prefer the entry that already has more info.
        if key not in seen or (not seen[key].source_job_url and c.source_job_url):
            seen[key] = c
    return list(seen.values())


def _rank(cands: list[Candidate], filters: SearchFilters) -> list[Candidate]:
    if not cands:
        return cands

    if llm.available:
        listing = [{"i": i, "company": c.company_name, "source": c.source} for i, c in enumerate(cands)]
        obj = llm.complete_json(
            system="You score job-search relevance. Return only JSON.",
            user=(
                f"Query filters: {filters.model_dump()}\n"
                f"Candidates: {listing}\n"
                'Score each candidate 0..1 for relevance to the query. '
                'Respond as JSON: {"scores": [{"i": 0, "score": 0.0}, ...]}.'
            ),
        )
        if obj and isinstance(obj.get("scores"), list):
            for s in obj["scores"]:
                try:
                    cands[int(s["i"])].relevance = max(0.0, min(1.0, float(s["score"])))
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
            return sorted(cands, key=lambda c: c.relevance, reverse=True)

    # Heuristic: keyword overlap with role/keywords, LinkedIn source bonus.
    terms = {t.lower() for t in ([filters.role] + filters.keywords) if t}
    for c in cands:
        name = c.company_name.lower()
        overlap = sum(1 for t in terms if t and t in name)
        c.relevance = min(1.0, 0.3 + 0.1 * overlap + (0.2 if c.source == "linkedin" else 0.0))
    return sorted(cands, key=lambda c: c.relevance, reverse=True)
