"""Offline unit tests for the deterministic parsing layer (no network/LLM)."""
from pathlib import Path

from app.parsing import (
    detect_ats,
    extract_job_links,
    looks_like_job_url,
    rank_careers_links,
    extract_links,
    same_site,
)

FIX = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_rank_careers_prefers_real_careers_link():
    links = extract_links(_html("homepage.html"), "https://acme.com/")
    ranked = rank_careers_links(links)
    top_urls = [lk.href for lk, _ in ranked[:2]]
    # The greenhouse board and /careers should outrank the blog post.
    assert any("greenhouse.io/acmerobotics" in u for u in top_urls)
    assert any(u.endswith("/careers") for u in top_urls)
    blog = next((s for lk, s in ranked if "/blog/" in lk.href), None)
    careers = next(s for lk, s in ranked if lk.href.endswith("/careers"))
    if blog is not None:
        assert careers > blog


def test_detect_ats():
    assert detect_ats("https://boards.greenhouse.io/acme") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc-123") == "lever"
    assert detect_ats("https://acme.myworkdayjobs.com/External/job/x") == "workday"
    assert detect_ats("https://acme.com/careers") is None


def test_looks_like_job_url():
    assert looks_like_job_url("https://jobs.lever.co/acme/2b1c3d4e-1111-2222-3333-444455556666")
    assert looks_like_job_url("https://boards.greenhouse.io/acme/jobs/123456")
    assert looks_like_job_url("https://acme.com/careers/software-engineer-backend")
    assert not looks_like_job_url("https://acme.com/about")


def test_extract_job_links_generic():
    jobs = extract_job_links(_html("careers_generic.html"), "https://acme.com/careers")
    hrefs = [j.href for j in jobs]
    assert "https://acme.com/careers/software-engineer-backend" in hrefs
    assert "https://acme.com/careers/ml-engineer" in hrefs
    # The plain "/about" link must not be treated as a posting.
    assert all("/about" not in h for h in hrefs)


def test_same_site():
    assert same_site("https://www.acme.com/", "https://careers.acme.com/x")
    assert not same_site("https://acme.com", "https://greenhouse.io/acme")
