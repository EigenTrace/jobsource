"""Sanity-check the Apify LinkedIn actor end to end.

Run inside your activated env, from the project root:

    python check_apify.py
    python check_apify.py "data scientist" "London"

It prints whether the call succeeded, the raw field names the actor returns,
and how those map into our Candidate. If `company_name` comes back empty, the
actor uses different output keys — paste the printed field list and I'll adjust
`_normalize_linkedin_item`.
"""
from __future__ import annotations

import asyncio
import json
import sys

from app.config import settings
from app.discovery import _normalize_linkedin_item
from app.search_sources import apify_linkedin_jobs


async def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "AI engineer"
    location = sys.argv[2] if len(sys.argv) > 2 else "United States"

    print(f"Apify token present : {settings.has_apify}")
    print(f"Actor               : {settings.apify_linkedin_actor}")
    print(f"Query               : title={title!r} location={location!r}\n")

    if not settings.has_apify:
        print("✗ No APIFY_API_TOKEN in .env — add it and re-run.")
        return

    items = await apify_linkedin_jobs(title, location, rows=5)
    print(f"Items returned      : {len(items)}")

    if not items:
        print(
            "\n✗ Zero items. Likely causes:\n"
            "  - actor name wrong or not accessible on your plan\n"
            "  - out of free credit\n"
            "  - input rejected (then it's an input-schema mismatch)\n"
            "Open the actor's last run at https://console.apify.com/actors/runs to see the error."
        )
        return

    first = items[0]
    print("\nRaw field names in the first item:")
    print(" ", sorted(first.keys()))

    print("\nFirst item (truncated to 1200 chars):")
    print(json.dumps(first, indent=2, ensure_ascii=False)[:1200])

    cand = _normalize_linkedin_item(first)
    print("\nNormalized into our Candidate:")
    print(json.dumps(cand.model_dump(), indent=2, ensure_ascii=False))

    if cand.company_name:
        print(f"\n✓ Mapping works. company_name = {cand.company_name!r}")
    else:
        print(
            "\n⚠ company_name is EMPTY → the actor's output keys differ from the "
            "normalizer. Copy the 'Raw field names' list above and share it; "
            "I'll wire _normalize_linkedin_item to the real keys."
        )


if __name__ == "__main__":
    asyncio.run(main())
