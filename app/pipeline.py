"""Resolution pipeline: a Candidate → a ResolvedResult (career page + position).

Also exposes `resolve_linkedin_url` for single-link mode and a small CLI.
"""
from __future__ import annotations

import asyncio
import json
import sys

from .browser import BrowserSession
from .progress import Emit, emit
from .schemas import Candidate, ResolvedResult
from .stageA_company import resolve_website
from .stageB_careers import find_careers_page
from .stageC_position import find_open_position


async def resolve_candidate(
    candidate: Candidate,
    session: BrowserSession,
    sink: Emit = None,
    *,
    deep: bool = True,
) -> ResolvedResult:
    """Run Stages A→B→C. If `deep` is False, return a shallow result."""
    result = ResolvedResult(
        company_name=candidate.company_name,
        source_job_url=candidate.source_job_url,
        relevance=candidate.relevance,
        depth="deep" if deep else "shallow",
    )
    if not deep:
        result.notes = "shallow (not resolved)"
        return result

    notes: list[str] = []

    website = await resolve_website(candidate, sink)
    if not website:
        result.notes = "could not resolve website"
        return result

    careers_url, note_b = await find_careers_page(website, session, sink)
    notes.append(f"B:{note_b}")
    result.career_page_url = careers_url
    if not careers_url:
        result.notes = "; ".join(notes)
        return result

    position_url, note_c = await find_open_position(careers_url, session, sink)
    notes.append(f"C:{note_c}")
    result.open_position_url = position_url
    result.notes = "; ".join(notes)
    return result


async def resolve_linkedin_url(linkedin_url: str, sink: Emit = None) -> ResolvedResult:
    """Single-link mode: a LinkedIn job/company URL → resolved result."""
    from .discovery import candidate_from_linkedin_url

    await emit(sink, "discovery", f"Reading LinkedIn signal: {linkedin_url}")
    candidate = await candidate_from_linkedin_url(linkedin_url)
    async with BrowserSession() as session:
        return await resolve_candidate(candidate, session, sink, deep=True)


# ── CLI ──────────────────────────────────────────────────────────────────────
def _print(result: ResolvedResult) -> None:
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))


async def _main(arg: str) -> None:
    async def log(ev) -> None:
        print(f"  [{ev.stage}] {ev.message}", file=sys.stderr)

    if "linkedin.com" in arg:
        result = await resolve_linkedin_url(arg, log)
        _print(result)
    else:
        # Treat the argument as a search query.
        from .orchestrator import run_search

        results = await run_search(arg, sink=log)
        print(json.dumps([r.model_dump() for r in results], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m app.pipeline "<linkedin url>" | "<search query>"', file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(_main(sys.argv[1]))
