"""Top-level orchestration: query → ranked, depth-policed results.

`run_search` is what both the CLI and the FastAPI UI call. Top-N candidates are
resolved deeply (full pipeline); the rest are returned shallow and can be
upgraded on demand via `resolve_one`.
"""
from __future__ import annotations

from typing import Optional

from .browser import BrowserSession
from .config import settings
from .discovery import discover, parse_query
from .pipeline import resolve_candidate
from .progress import Emit, emit
from .schemas import Candidate, ResolvedResult, SearchFilters


async def run_search(
    query: str,
    *,
    filters: Optional[SearchFilters] = None,
    top_n: Optional[int] = None,
    sink: Emit = None,
) -> list[ResolvedResult]:
    top_n = settings.deep_resolve_top_n if top_n is None else top_n
    filters = filters or parse_query(query)
    await emit(sink, "discovery", f"Parsed filters: {filters.model_dump()}", filters=filters.model_dump())

    candidates = await discover(filters)
    await emit(sink, "discovery", f"Found {len(candidates)} candidate companies.",
               count=len(candidates))

    results: list[ResolvedResult] = []
    async with BrowserSession() as session:
        for i, cand in enumerate(candidates):
            deep = i < top_n
            await emit(sink, "resolve",
                       f"{'Resolving' if deep else 'Listing'} {cand.company_name} "
                       f"({i + 1}/{len(candidates)})…",
                       company=cand.company_name, deep=deep)
            results.append(await resolve_candidate(cand, session, sink, deep=deep))
    await emit(sink, "done", "Search complete.", total=len(results))
    return results


async def resolve_one(candidate: Candidate, sink: Emit = None) -> ResolvedResult:
    """Deep-resolve a single (previously shallow) candidate — for the UI button."""
    async with BrowserSession() as session:
        return await resolve_candidate(candidate, session, sink, deep=True)
