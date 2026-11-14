"""Request and response shapes. LLM output is validated against these; nothing is defaulted."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_TRANSCRIPT = 120_000
MAX_CLAIM = 600


class TranscriptIn(BaseModel):
    transcript: str = Field(min_length=40, max_length=MAX_TRANSCRIPT)

    @field_validator("transcript")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 40:
            raise ValueError("transcript is too short to analyze")
        return v


class SummarizeIn(TranscriptIn):
    length: Literal["short", "long"] = "short"


class ClaimsIn(TranscriptIn):
    pass


class AnalyzeIn(TranscriptIn):
    summary_length: Literal["short", "long"] = "short"


class CheckIn(BaseModel):
    claim: str = Field(min_length=8, max_length=MAX_CLAIM)


class SummaryOut(BaseModel):
    """What the model must return for a summary."""

    summary: str = Field(min_length=1)
    key_points: list[str] = Field(default_factory=list, max_length=8)


class ErrorOut(BaseModel):
    status: Literal["error"] = "error"
    error: str
    message: str
