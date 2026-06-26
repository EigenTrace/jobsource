"""Stage C — careers page → one open position URL.

Order: ATS-aware / generic posting-link extraction → follow embedded ATS iframe
if the page is just a shell → LLM choice among candidates. Returns
(position_url, note).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .browser import BrowserSession
from .llm import llm
from .parsing import Link, detect_ats, extract_job_links, looks_like_job_url
from .progress import Emit, emit


async def find_open_position(careers_url: str, session: BrowserSession, sink: Emit = None) -> tuple[str, str]:
    if not careers_url:
        return "", "no careers url"

    await emit(sink, "C", f"Loading careers page {careers_url}…")
    page = await session.fetch(careers_url)
    if not page.ok or not page.html:
        return "", f"careers page error: {page.error}"

    postings = extract_job_links(page.html, page.url)

    # The careers page may embed an ATS in an iframe; follow it once.
    if not postings:
        iframe_src = _find_ats_iframe(page.html, page.url)
        if iframe_src:
            await emit(sink, "C", f"Following embedded ATS iframe → {iframe_src}")
            inner = await session.fetch(iframe_src)
            if inner.ok and inner.html:
                postings = extract_job_links(inner.html, inner.url)

    if not postings:
        return "", "no postings found on careers page"

    # One obvious posting → done.
    if len(postings) == 1:
        url = postings[0].href
        await emit(sink, "C", f"Open position: {url}", url=url)
        return url, "single posting"

    # Several → let the LLM pick a concrete, currently-open role if it can.
    if llm.available:
        choice = _llm_pick_position(postings[:20], careers_url)
        if choice:
            await emit(sink, "C", f"Open position (LLM): {choice}", url=choice)
            return choice, "LLM picked from postings"

    # Otherwise take the first posting that looks like an individual role.
    url = postings[0].href
    await emit(sink, "C", f"Open position (first match): {url}", url=url)
    return url, f"first of {len(postings)} postings"


def _find_ats_iframe(html: str, base_url: str) -> str:
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["iframe", "script"]):
        src = tag.get("src") or tag.get("data-src") or ""
        if src and detect_ats(src):
            return urljoin(base_url, src)
    # Greenhouse/Lever embeds sometimes reference the board host in scripts.
    m = re.search(r"https?://(?:boards|job-boards)\.greenhouse\.io/[\w-]+", html or "")
    if m:
        return m.group(0)
    return ""


def _llm_pick_position(postings: list[Link], careers_url: str) -> str:
    shortlist = [{"text": lk.text[:80], "url": lk.href} for lk in postings]
    obj = llm.complete_json(
        system="You are a precise web navigator. Return only JSON.",
        user=(
            f"From this list of links on the careers page {careers_url}, pick ONE that is an "
            "individual OPEN JOB POSTING (not a category, filter, or the listing index). "
            'Respond as JSON: {"url": "<chosen url or empty string>"}.\n\n'
            f"LINKS:\n{shortlist}"
        ),
    )
    if obj:
        url = (obj.get("url") or "").strip()
        if url.startswith("http") and looks_like_job_url(url):
            return url
    return ""
