"""Offline tests for discovery helpers (heuristic paths, no API keys needed)."""
import asyncio

from app.discovery import (
    _dedupe,
    _humanize,
    _rank,
    candidate_from_linkedin_url,
    parse_query,
)
from app.schemas import Candidate, SearchFilters


def test_parse_query_heuristic():
    f = parse_query("Senior AI engineers in New York remote")
    assert "engineer" in f.role.lower()
    assert f.remote is True
    # location capture is best-effort; if present it should mention New York
    if f.location:
        assert "New York" in f.location


def test_humanize():
    assert _humanize("acme-robotics") == "Acme Robotics"
    assert _humanize("openai") == "Openai"


def test_dedupe_keeps_richer_record():
    cands = [
        Candidate(company_name="Acme", source="web"),
        Candidate(company_name="acme", source="linkedin", source_job_url="https://x/y"),
    ]
    out = _dedupe(cands)
    assert len(out) == 1
    assert out[0].source_job_url == "https://x/y"


def test_rank_heuristic_orders_by_relevance():
    cands = [
        Candidate(company_name="Random Co", source="web"),
        Candidate(company_name="AI Engineer Labs", source="linkedin"),
    ]
    ranked = _rank(cands, SearchFilters(role="AI Engineer", keywords=["AI"]))
    assert ranked[0].relevance >= ranked[-1].relevance


def test_candidate_from_company_url():
    cand = asyncio.run(candidate_from_linkedin_url("https://www.linkedin.com/company/acme-robotics/"))
    assert cand.company_name == "Acme Robotics"
    assert cand.company_linkedin_url.endswith("/company/acme-robotics/")
