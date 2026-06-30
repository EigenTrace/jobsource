"""External search clients: Tavily (web) and Apify (LinkedIn jobs).

Both are optional. With no key, functions return empty results and callers fall
back. This module holds the *I/O*; ranking/parsing logic lives elsewhere.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import settings

logger = logging.getLogger(__name__)

# Hosts that are never a company's own website.
_NON_COMPANY_HOSTS = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "crunchbase.com", "wikipedia.org", "glassdoor.com", "indeed.com",
    "bloomberg.com", "youtube.com", "github.com", "medium.com",
)


@dataclass
class WebResult:
    title: str
    url: str
    content: str = ""
    score: float = 0.0


# ── Tavily web search ────────────────────────────────────────────────────────
async def tavily_search(query: str, *, max_results: int = 6, depth: str = "basic") -> list[WebResult]:
    if not settings.has_tavily:
        return []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": depth,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            WebResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=float(r.get("score", 0.0) or 0.0),
            )
            for r in data.get("results", [])
        ]
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Tavily search failed: %s", exc)
        return []


def _homepage(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}/"


async def find_official_website(company_name: str) -> str:
    """Best-effort official website for a company, via Tavily then LLM fallback."""
    if not company_name:
        return ""
    results = await tavily_search(f'"{company_name}" official company website', max_results=8)
    for r in results:
        host = (urlparse(r.url).hostname or "").lower()
        if host and not any(bad in host for bad in _NON_COMPANY_HOSTS):
            return _homepage(r.url)

    # LLM fallback: ask DeepSeek for the domain.
    from .llm import llm

    if llm.available:
        obj = llm.complete_json(
            system="You return only JSON.",
            user=(
                f'What is the official company website homepage URL for "{company_name}"? '
                'Respond as JSON: {"website": "https://..."}. If unsure, use "".'
            ),
        )
        if obj:
            site = (obj.get("website") or "").strip()
            if site.startswith("http"):
                return _homepage(site)
    return ""


# ── Apify LinkedIn jobs search ───────────────────────────────────────────────
async def apify_linkedin_jobs(query: str, location: str = "", *, rows: int = 12) -> list[dict]:
    """Run the configured Apify LinkedIn-jobs actor synchronously and return items.

    Input is tailored to `valig/linkedin-jobs-scraper` (keyword-based,
    pay-per-result): it expects `title`, `location`, and `limit`. If you switch
    to a different actor, adjust `payload` to that actor's input schema.
    Returns the raw dataset items (list of dicts).
    """
    if not settings.has_apify or not query.strip():
        return []
    try:
        import httpx

        actor = settings.apify_linkedin_actor
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        payload = {
            "title": query,                          # role / skill / company
            "location": location or "United States",
            "limit": max(10, rows),                  # valig's count field
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                url,
                params={"token": settings.apify_api_token},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, list) else data.get("items", [])
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Apify LinkedIn search failed: %s", exc)
        return []
