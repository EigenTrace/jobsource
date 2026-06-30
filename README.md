# AI Job Source Agent

Turn a LinkedIn hiring signal into a **direct link to a live job on the company's own career
site** — and discover those signals from a plain-English search.

> Built for Jobnova's AI Engineer take-home, Part 2. LinkedIn is the hiring *signal*; the agent's
> value is everything after it — autonomously navigating from that signal to the real open role on
> the employer's own site, across whatever format that site happens to use.

```
search query ─▶ discovery (LinkedIn + web) ─▶ ranked companies
                                              └─▶ per company:  website ─▶ careers page ─▶ open position
output per result:  company_name, career_page_url, open_position_url
```

---

## What it does

Two entry points, one engine:

- **Search mode** — a natural-language query ("Senior AI engineers at fintech startups, remote") is
  parsed into editable filters, searched against LinkedIn (with a web fallback), and ranked. The top
  few companies are resolved all the way to a direct career page + open position; the rest are
  listed shallow and can be resolved on demand.
- **Single-link mode** — paste one LinkedIn job/company URL and resolve that single company
  end-to-end.

Per result it returns the three required fields plus a trace of how it got there:

```json
{ "company_name": "Stripe",
  "career_page_url": "https://stripe.com/jobs/search",
  "open_position_url": "https://stripe.com/jobs/listing/.../1234567",
  "source_job_url": "https://www.linkedin.com/jobs/view/...",
  "relevance": 0.91, "depth": "deep",
  "notes": "B:heuristic score 5.0; C:LLM picked from postings" }
```

## Why it's generic (the design idea)

The graded requirement is *"works across very different website formats."* The approach is a
**hybrid that uses the right tool for each kind of subtask**, and falls back gracefully:

| Subtask | Best tool | Where |
|---|---|---|
| Understand fuzzy language (query → filters) | **LLM** (DeepSeek) | `discovery.parse_query` |
| Look up a fact (company → website) | **Web search** (Tavily), LLM as backup | Stage A |
| Recognize stable patterns (ATS hosts, job-URL shapes, careers links) | **Heuristics / regex** | `parsing.py` |
| Break a tie among vetted options (which careers link? which posting?) | **LLM on a shortlist** | Stage B / C |

Concretely, each stage is a **confidence-tiered decision ladder**: a free deterministic shortcut
first (e.g. detecting a Greenhouse/Lever/Ashby/Workday ATS by URL), then a heuristic pick if it's
confident, then a single cheap LLM call to choose among a *shortlist* of candidate links (never raw
HTML), then path-probing as a backstop. Cheap and reliable on the common case; smart only when it
needs to be. Missing any API key degrades to heuristics instead of crashing.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # (or a conda env with Python 3.11)
pip install -r requirements.txt
playwright install chromium                            # one-time headless-browser download

cp .env.example .env                                   # then add your keys
```

Keys (all optional — the app runs degraded without them; see `.env.example`):

- `DEEPSEEK_API_KEY` — the LLM "brain" (OpenAI-compatible; swap `DEEPSEEK_MODEL`/`DEEPSEEK_BASE_URL`
  to use any compatible provider).
- `APIFY_API_TOKEN` — LinkedIn job search. Default actor `valig~linkedin-jobs-scraper`
  (keyword-based, pay-per-result ~$0.32/1k, covered by Apify's free monthly credit).
- `TAVILY_API_KEY` — web-search fallback + official-website lookup (1,000 free credits/month).

## Run

Web UI (best for the demo):

```bash
uvicorn app.main:app --reload          # then open http://127.0.0.1:8000
```

CLI:

```bash
python -m app.pipeline "https://www.linkedin.com/jobs/view/4432254692"        # single-link
python -m app.pipeline "Senior AI engineers at fintech startups, remote"      # search
```

Verify the Apify integration end to end (prints the actor's real fields and how they map):

```bash
python check_apify.py
python check_apify.py "data scientist" "London"
```

## How it works

```
app/
  config.py            env + capability flags (has_deepseek / has_apify / has_tavily)
  schemas.py           pydantic data contract: SearchFilters → Candidate → ResolvedResult
  llm.py               DeepSeek client (strict JSON out, returns None when unavailable)
  browser.py           Playwright session (renders JS; httpx fallback)
  parsing.py           pure heuristics: link scoring, ATS detection, job-URL extraction
  search_sources.py    Tavily (web) + Apify (LinkedIn) I/O
  discovery.py         NL→filters, search, dedupe, relevance ranking
  stageA_company.py    company  → official website
  stageB_careers.py    website  → careers page   (heuristic ladder + LLM tiebreak)
  stageC_position.py   careers  → one open position (ATS-aware + LLM tiebreak)
  pipeline.py          resolve one candidate (A→B→C) + CLI
  orchestrator.py      search → rank → depth policy → results
  main.py              FastAPI UI + SSE progress streaming
templates/index.html   two-mode UI with live progress + on-demand resolve
tests/                 offline unit tests on HTML fixtures (no keys/network needed)
```

## Tests

```bash
pytest -q          # runs fully offline
```

## Limitations & next steps

- **LinkedIn blocks direct scraping**, so single-link on a *job* URL is best-effort; the reliable
  paths are a `/company/...` URL or the Apify actor for search. (This is why the brief allows a
  third-party crawler.)
- **`applyUrl` shortcut** — when a LinkedIn item has `applyType: "EXTERNAL"`, its `applyUrl` is often
  the employer's own posting; capturing it could skip Stages B/C entirely for many results.
- **Richer ranking** — the relevance ranker currently scores on company name; feeding the job
  `title`/`sector`/`description` (already in the Apify payload) would sharpen it.
- **Concurrency** — candidates are resolved sequentially; since the work is I/O-bound,
  `asyncio.gather` would parallelize a search for a large speedup.
- **More ATS coverage** — detection covers the major providers; niche ATSs fall back to the generic
  + LLM path.

## Notes

- `deepseek-chat` is valid until 2026-07-24; set `DEEPSEEK_MODEL=deepseek-v4-flash` after that.
- Tune `DEEP_RESOLVE_TOP_N` (how many results get the full pipeline) and `BROWSER_HEADLESS` in `.env`.
