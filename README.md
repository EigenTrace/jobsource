# AI Job Source Agent

Turn a LinkedIn hiring signal into a **direct** link to a live job on the company's own
career site — and discover those signals from a natural-language search.

Built for Jobnova's AI Engineer take-home, Part 2.

```
search query ─▶ discovery (LinkedIn + web) ─▶ ranked companies
                                              └▶ per company: website ─▶ careers page ─▶ open position
output per result: company_name, career_page_url, open_position_url
```

## Why it's "generic"

Every stage uses **cheap deterministic parsing first, the LLM only where formats vary**:

- Careers-page discovery scores nav/footer links and recognises known ATS hosts
  (Greenhouse, Lever, Ashby, Workday, Breezy, …); DeepSeek only disambiguates a shortlist.
- Job extraction detects embedded ATS boards and posting-shaped URLs; DeepSeek only picks
  among candidates when several exist.
- Missing API keys degrade gracefully to heuristics instead of crashing.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # one-time browser download

cp .env.example .env                 # then add your keys (all optional)
```

Keys (all optional — see `.env.example`):
- `DEEPSEEK_API_KEY` — the LLM brain (OpenAI-compatible).
- `APIFY_API_TOKEN` — LinkedIn job search / company lookup.
- `TAVILY_API_KEY` — web-search fallback + official-website lookup.

## Run

Web UI (recommended for the demo):
```bash
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

CLI:
```bash
python -m app.pipeline "https://www.linkedin.com/jobs/view/4012345678"   # single-link mode
python -m app.pipeline "Senior AI engineers at fintech startups, remote"  # search mode
```

## Demo script (for the go-through video)

1. **Search mode** — type a natural-language query, click *Parse to filters* (DeepSeek fills
   editable fields), then *Run search*. Watch progress stream stage-by-stage; the top few
   companies resolve to a direct career page + open position, the rest stay shallow with a
   *Resolve deeply* button.
2. **Single-link mode** — paste a LinkedIn job URL and resolve one company end-to-end.
3. **Genericness** — run it on 3–4 different site styles (a Greenhouse site, a Lever site, a
   Workday site, a bespoke careers page) to show it isn't hard-coded.

## Layout

```
app/
  config.py            env/config + has_* capability flags
  schemas.py           pydantic data contract
  llm.py               DeepSeek client (strict JSON, no-key fallback)
  browser.py           Playwright session (+ httpx fallback)
  parsing.py           pure heuristics: link scoring, ATS detection, job extraction
  search_sources.py    Tavily + Apify I/O
  discovery.py         NL→filters, search, dedupe, rank
  stageA_company.py    company → website
  stageB_careers.py    website → careers page
  stageC_position.py   careers page → one open position
  pipeline.py          resolve one candidate (A→B→C) + CLI
  orchestrator.py      search → depth policy → results
  main.py              FastAPI UI + SSE streaming
templates/index.html   two-mode UI
tests/                 offline unit tests on HTML fixtures
```

## Tests

```bash
pytest -q          # runs offline; no API keys or network required
```

## Notes & limitations

- LinkedIn blocks direct scraping; the reliable path is the Apify actor. Without it, single-link
  mode falls back to a best-effort guest-page parse and search uses the Tavily web fallback.
- `deepseek-chat` is valid until 2026-07-24; set `DEEPSEEK_MODEL=deepseek-v4-flash` after that.
- Tune `DEEP_RESOLVE_TOP_N` (how many results get the full pipeline) and `BROWSER_HEADLESS`
  in `.env`.
```
