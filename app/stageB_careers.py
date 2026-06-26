"""Stage B — website → careers page (the hard, "generic" part).

Order: deterministic link scoring → LLM disambiguation (if available) →
common-path probing. Returns (careers_url, note).
"""
from __future__ import annotations

from .browser import BrowserSession
from .llm import llm
from .parsing import (
    COMMON_CAREERS_PATHS,
    Link,
    detect_ats,
    extract_links,
    rank_careers_links,
)
from .progress import Emit, emit

# Confident enough to take the top heuristic pick without asking the LLM.
_STRONG_SCORE = 3.0


async def find_careers_page(website_url: str, session: BrowserSession, sink: Emit = None) -> tuple[str, str]:
    if not website_url:
        return "", "no website"

    # If the website itself is already an ATS board, that *is* the careers page.
    if detect_ats(website_url):
        return website_url, "website is an ATS board"

    await emit(sink, "B", f"Loading homepage {website_url}…")
    page = await session.fetch(website_url)
    if not page.ok or not page.html:
        # Even without HTML we can still probe common paths.
        probed = await _probe_common_paths(website_url, session, sink)
        return (probed, "probed common path (homepage unreachable)") if probed else ("", f"homepage error: {page.error}")

    links = extract_links(page.html, page.url)
    ranked = rank_careers_links(links)

    if ranked and ranked[0][1] >= _STRONG_SCORE:
        best = ranked[0][0]
        await emit(sink, "B", f"Careers link (heuristic): {best.href}", url=best.href)
        return best.href, f"heuristic score {ranked[0][1]:.1f}"

    # Ambiguous → let the LLM pick from a shortlist of links.
    if llm.available and ranked:
        choice = _llm_pick_careers(ranked[:12], website_url)
        if choice:
            await emit(sink, "B", f"Careers link (LLM): {choice}", url=choice)
            return choice, "LLM picked from shortlist"

    # Weak heuristic pick, if any.
    if ranked:
        best = ranked[0][0]
        await emit(sink, "B", f"Careers link (weak heuristic): {best.href}", url=best.href)
        return best.href, f"weak heuristic score {ranked[0][1]:.1f}"

    # Last resort: probe well-known paths.
    probed = await _probe_common_paths(website_url, session, sink)
    if probed:
        return probed, "probed common path"
    return "", "no careers link found"


def _llm_pick_careers(ranked: list[tuple[Link, float]], website_url: str) -> str:
    shortlist = [{"text": lk.text[:80], "url": lk.href} for lk, _ in ranked]
    obj = llm.complete_json(
        system="You are a precise web navigator. Return only JSON.",
        user=(
            f"From this list of links on {website_url}, pick the single one most likely to be "
            "the company's CAREERS / JOBS page (where open positions are listed). "
            'Respond as JSON: {"url": "<chosen url or empty string>"}.\n\n'
            f"LINKS:\n{shortlist}"
        ),
    )
    if obj:
        url = (obj.get("url") or "").strip()
        if url.startswith("http"):
            return url
    return ""


async def _probe_common_paths(website_url: str, session: BrowserSession, sink: Emit) -> str:
    from urllib.parse import urljoin

    await emit(sink, "B", "Probing common careers paths…")
    for path in COMMON_CAREERS_PATHS:
        candidate = urljoin(website_url, path)
        page = await session.fetch(candidate)
        if page.ok and page.html and len(page.html) > 500:
            # Heuristic: a careers page usually mentions "job" or "position".
            low = page.html.lower()
            if any(w in low for w in ("job", "position", "vacanc", "role", "career")):
                return page.url
    return ""
