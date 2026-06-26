"""FastAPI app: two-mode UI (search + single-link) with SSE progress streaming."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .discovery import candidate_from_linkedin_url, parse_query
from .orchestrator import resolve_one, run_search
from .pipeline import resolve_candidate
from .progress import emit
from .schemas import Candidate, ProgressEvent, SearchFilters
from .browser import BrowserSession

BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="AI Job Source Agent")

templates = Jinja2Templates(directory=str(BASE / "templates"))
static_dir = BASE / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(runner) -> StreamingResponse:
    """Bridge an emitting coroutine to an SSE response via a queue."""
    queue: asyncio.Queue = asyncio.Queue()

    async def sink(ev: ProgressEvent) -> None:
        await queue.put({"type": "progress", "stage": ev.stage, "message": ev.message, "data": ev.data})

    async def run() -> None:
        try:
            results = await runner(sink)
            payload = results if isinstance(results, list) else [results]
            await queue.put({"type": "result", "results": [r.model_dump() for r in payload]})
        except Exception as exc:  # surface errors to the UI
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put({"type": "__end__"})

    async def gen():
        task = asyncio.create_task(run())
        # advertise which integrations are live so the UI can warn the user
        yield _sse({"type": "meta", "deepseek": settings.has_deepseek,
                    "apify": settings.has_apify, "tavily": settings.has_tavily})
        while True:
            item = await queue.get()
            if item.get("type") == "__end__":
                break
            yield _sse(item)
        await task

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "settings": settings})


@app.post("/api/parse")
async def api_parse(payload: dict):
    """NL query → editable filters."""
    filters = parse_query(payload.get("query", ""))
    return JSONResponse(filters.model_dump())


@app.get("/api/search/stream")
async def api_search(q: str = "", role: str = "", location: str = "",
                     keywords: str = "", industry: str = "", seniority: str = "",
                     remote: str = ""):
    if role or location or keywords:
        filters = SearchFilters(
            role=role, location=location,
            keywords=[k.strip() for k in keywords.split(",") if k.strip()],
            industry=industry, seniority=seniority,
            remote=True if remote == "true" else False if remote == "false" else None,
        )
    else:
        filters = parse_query(q)

    async def runner(sink):
        return await run_search(q or filters.to_linkedin_query(), filters=filters, sink=sink)

    return await _stream(runner)


@app.get("/api/single/stream")
async def api_single(url: str):
    async def runner(sink):
        await emit(sink, "discovery", f"Reading LinkedIn signal: {url}")
        candidate = await candidate_from_linkedin_url(url)
        async with BrowserSession() as session:
            return await resolve_candidate(candidate, session, sink, deep=True)

    return await _stream(runner)


@app.post("/api/resolve")
async def api_resolve(payload: dict):
    """On-demand deep-resolve of a shallow candidate."""
    candidate = Candidate(**payload)
    result = await resolve_one(candidate)
    return JSONResponse(result.model_dump())


@app.get("/api/health")
async def health():
    return {"ok": True, "deepseek": settings.has_deepseek,
            "apify": settings.has_apify, "tavily": settings.has_tavily}
