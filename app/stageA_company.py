"""Stage A — company → official website."""
from __future__ import annotations

from .progress import Emit, emit
from .schemas import Candidate
from .search_sources import find_official_website


async def resolve_website(candidate: Candidate, sink: Emit = None) -> str:
    if candidate.company_website:
        await emit(sink, "A", f"Website already known: {candidate.company_website}")
        return candidate.company_website

    await emit(sink, "A", f"Resolving official website for {candidate.company_name}…")
    website = await find_official_website(candidate.company_name)
    if website:
        await emit(sink, "A", f"Found website: {website}", website=website)
    else:
        await emit(sink, "A", f"Could not resolve a website for {candidate.company_name}.")
    return website
