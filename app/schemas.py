"""Pydantic models: the shared data contract across discovery + resolution."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Structured filters parsed from a natural-language query (editable in UI)."""

    role: str = ""
    keywords: list[str] = Field(default_factory=list)
    location: str = ""
    remote: Optional[bool] = None
    industry: str = ""
    seniority: str = ""

    def to_linkedin_query(self) -> str:
        parts = [self.role] + self.keywords
        if self.industry:
            parts.append(self.industry)
        return " ".join(p for p in parts if p).strip()


class Candidate(BaseModel):
    """A company/job surfaced by the discovery layer, pre-resolution."""

    company_name: str
    source: Literal["linkedin", "web"] = "linkedin"
    source_job_url: str = ""
    company_linkedin_url: str = ""
    company_website: str = ""
    relevance: float = 0.0  # 0..1, ranked by the LLM (or heuristic)


class ResolvedResult(BaseModel):
    """The per-result output contract."""

    company_name: str
    career_page_url: str = ""
    open_position_url: str = ""
    source_job_url: str = ""
    relevance: float = 0.0
    depth: Literal["deep", "shallow"] = "shallow"
    notes: str = ""  # human-readable trace of how it resolved / why it didn't

    @property
    def ok(self) -> bool:
        return bool(self.career_page_url or self.open_position_url)


class ProgressEvent(BaseModel):
    """Streamed to the UI over SSE."""

    stage: str
    message: str
    data: dict = Field(default_factory=dict)
